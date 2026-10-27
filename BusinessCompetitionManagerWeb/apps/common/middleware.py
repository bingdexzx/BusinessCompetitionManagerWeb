"""中间件：比赛上下文解析 + 网络日志（§14.3）+ 数据库背压（过载保护）。"""

import re
import threading
import time
import uuid

from django.conf import settings
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

from apps.common import context as ctx
from apps.common.devices import device_snapshot, client_ip
from apps.common.redaction import digest

_COMPETITION_URL_RE = re.compile(r'^/api/competitions/(\d+)(?:/|$)')


class DatabaseBackpressureMiddleware(MiddlewareMixin):
    """数据库背压：并发请求排队，防止打爆 PostgreSQL 连接数。

    每请求最多 2 条连接，60 并发 × 2 ≈ 120 > PG 默认 100 → ``too many clients``。信号量只能
    进程内共享，故把全局预算按 ``WEB_CONCURRENCY`` 分摊到每 worker（加核不放大峰值）；
    排队超 ``DB_BACKPRESSURE_TIMEOUT`` 秒则 503 + Retry-After，避免整机假死。
    """

    _semaphore = None

    @classmethod
    def _sem(cls):
        if cls._semaphore is None:
            limit = getattr(
                settings, 'DB_MAX_CONCURRENT_REQUESTS_PER_WORKER',
                getattr(settings, 'DB_MAX_CONCURRENT_REQUESTS', 32))
            cls._semaphore = threading.BoundedSemaphore(max(1, limit))
        return cls._semaphore

    def process_request(self, request):
        if not request.path.startswith('/api/'):
            return None
        timeout = getattr(settings, 'DB_BACKPRESSURE_TIMEOUT', 10.0)
        if not self._sem().acquire(timeout=timeout):
            return JsonResponse(
                {'code': 503, 'message': '服务器繁忙，请稍后重试', 'details': ''},
                status=503, headers={'Retry-After': '2'})
        request._gipfel_backpressure = True
        return None

    def process_response(self, request, response):
        if getattr(request, '_gipfel_backpressure', False):
            try:
                self._sem().release()
            except ValueError:  # pragma: no cover —— 防御性
                pass
        return response


class ApiErrorHtmlMiddleware(MiddlewareMixin):
    """/api/* 的 HTML 错误页 → 简洁中文 JSON（DEBUG 的 404/500 调试页不直接抛给前端）。"""

    _MESSAGES = {404: '接口不存在', 500: '服务器内部错误，请稍后重试'}

    def process_response(self, request, response):
        if not request.path.startswith('/api/'):
            return response
        if response.status_code < 400:
            return response
        content_type = response.get('Content-Type', '')
        if 'text/html' not in content_type:
            return response
        return JsonResponse(
            {
                'code': response.status_code,
                'message': self._MESSAGES.get(response.status_code, '请求失败，请稍后重试'),
                'details': request.path,
            },
            status=response.status_code,
        )


class CompetitionContextMiddleware(MiddlewareMixin):
    """解析比赛上下文（URL 参数 / X-Competition-Id 头），注册比赛库 alias。

    比赛域模型由 CompetitionDatabaseRouter 依此路由到 comp_<id>（§5.2）。"""

    def process_request(self, request):
        competition_id = None
        from_path = False
        m = _COMPETITION_URL_RE.match(request.path)
        if m:
            competition_id = int(m.group(1))
            from_path = True
        else:
            header = request.META.get('HTTP_X_COMPETITION_ID', '')
            if str(header).isdigit():
                competition_id = int(header)
        request.competition_id = competition_id
        if competition_id:
            from apps.global_.competitions.models import Competition
            from apps.competition import provisioning

            competition = Competition.objects.filter(pk=competition_id).first()
            if competition is None:
                # 比赛不存在/已删除：URL 明确指向该比赛的接口直接 404，否则视图内
                # 比赛域模型会因无上下文 RuntimeError 500。仅带头的全局接口不拦，避旧头误伤。
                if from_path:
                    return JsonResponse(
                        {'code': 404, 'message': '比赛不存在或已删除', 'details': ''},
                        status=404)
                return None
            alias = provisioning.ensure_competition_db(competition.db_name)
            ctx.set_competition_context(competition_id, alias)

    def process_response(self, request, response):
        ctx.clear_request_context()
        return response


class NetworkLogMiddleware(MiddlewareMixin):
    """记录每次 API 交互：方法/路径/状态码/耗时/IP/设备/用户 + 脱敏摘要（§14.3）。"""

    def process_request(self, request):
        trace_id = request.META.get('HTTP_X_TRACE_ID') or uuid.uuid4().hex
        snapshot = device_snapshot(request)
        ctx.set_trace_id(trace_id)
        ctx.set_device_snapshot(snapshot)
        request._gipfel_started_at = time.perf_counter()
        request._gipfel_trace_id = trace_id
        request._gipfel_device = snapshot
        return None

    def process_response(self, request, response):
        started = getattr(request, '_gipfel_started_at', None)
        try:
            self._write_log(request, response, started)
        except Exception:  # noqa: BLE001 —— 日志绝不影响业务响应
            pass
        try:
            self._broadcast_change(request, response)
        except Exception:  # noqa: BLE001 —— 广播绝不影响业务响应
            pass
        return response

    # 不广播的路径前缀：认证/个人/消息读写/日志查询/文件（非业务资源变更）
    _BROADCAST_SKIP = ('/api/auth', '/api/me', '/api/messages', '/api/logs',
                       '/api/files', '/api/version')
    _BROADCAST_ACTIONS = {'POST': 'created', 'PATCH': 'updated', 'PUT': 'updated',
                          'DELETE': 'deleted'}
    # 比赛子路径 → 广播资源名归一：package（导入）还改产业字段/合同类型/仪表盘，归一为 packages
    _COMPETITION_RESOURCE_ALIAS = {
        'meta': 'competitions',
        'transition': 'competitions',
        'package': 'packages',
    }

    def _broadcast_change(self, request, response):
        """写接口成功后广播 `resource:changed`（推信号，页面自行增量重拉）。

        资源名取自路径。**作用域按路径判定，不看 `X-Competition-Id`**：全局库资源即使带着
        比赛头也必须进 `global` 流，否则在别的比赛上下文里操作全局资源时，订阅 global 的
        页面收不到。
        """
        method = (request.method or '').upper()
        action = self._BROADCAST_ACTIONS.get(method)
        path = request.path
        if not action or not path.startswith('/api/') or path.startswith(self._BROADCAST_SKIP):
            return
        if response.status_code >= 400:
            return
        parts = [p for p in path.split('/') if p][1:]  # 去掉 'api'
        resource = parts[0] if parts else ''
        competition_id = None
        if resource == 'competitions' and len(parts) > 2 and parts[1].isdigit():
            competition_id = int(parts[1])   # 比赛级：/api/competitions/<cid>/<resource>
            resource = parts[2]
            resource = self._COMPETITION_RESOURCE_ALIAS.get(resource, resource)
        if not resource:
            return
        from apps.common.broadcast import emit_resource_changed

        emit_resource_changed(competition_id, resource, action, {'path': path[:200]})

    def _write_log(self, request, response, started):
        from apps.global_.logs.models import NetworkLog

        if request.path.startswith('/static/') or request.path == '/favicon.ico':
            return

        duration_ms = None
        if started is not None:
            duration_ms = int((time.perf_counter() - started) * 1000)

        user = None
        if getattr(request, 'user', None) is not None and request.user.is_authenticated:
            user = request.user
        if user is None:
            user = ctx.get_log_user()

        payload = self._request_digest(request)
        resp_digest = self._response_digest(response)

        NetworkLog.objects.create(
            trace_id=getattr(request, '_gipfel_trace_id', ctx.get_trace_id() or ''),
            user=user if user and getattr(user, 'pk', None) else None,
            competition_id=ctx.get_competition_id(),
            device_snapshot=getattr(request, '_gipfel_device', ctx.get_device_snapshot()) or {},
            method=request.method or '',
            path=request.path[:500],
            query=digest(dict(request.GET)) if request.GET else '',
            status=response.status_code,
            duration_ms=duration_ms,
            ip=client_ip(request),
            payload_digest=payload,
            response_digest=resp_digest,
        )

    def _request_digest(self, request):
        content_type = request.META.get('CONTENT_TYPE', '')
        length = int(request.META.get('CONTENT_LENGTH') or 0)
        if length and length <= 64 * 1024:
            if 'json' in content_type or 'x-www-form-urlencoded' in content_type:
                try:
                    return digest(request.body)
                except Exception:  # noqa: BLE001
                    return ''
        return ''

    def _response_digest(self, response):
        if getattr(response, 'streaming', False):
            return ''
        content = getattr(response, 'content', None)
        if not content:
            return ''
        try:
            return digest(content[: settings.LOG_DIGEST_MAX_LENGTH * 2])
        except Exception:  # noqa: BLE001
            return ''
