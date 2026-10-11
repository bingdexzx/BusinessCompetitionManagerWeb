"""中间件：比赛上下文解析 + 网络日志（§14.3）。"""

import time
import uuid

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin

from apps.common import context as ctx
from apps.common.devices import device_snapshot, client_ip
from apps.common.redaction import digest

# 从 URL 解析比赛 id：/api/competitions/<cid>/...
import re

_COMPETITION_URL_RE = re.compile(r'^/api/competitions/(\d+)(?:/|$)')


class CompetitionContextMiddleware(MiddlewareMixin):
    """解析比赛上下文（URL 参数 / X-Competition-Id 头），注册比赛库 alias。

    比赛域模型的读写由 CompetitionDatabaseRouter 依此路由到 comp_<id>（§5.2）。
    """

    def process_request(self, request):
        competition_id = None
        m = _COMPETITION_URL_RE.match(request.path)
        if m:
            competition_id = int(m.group(1))
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
                # 交给视图返回 404；此处只清上下文
                return None
            alias = provisioning.ensure_competition_db(competition.db_name)
            ctx.set_competition_context(competition_id, alias)

    def process_response(self, request, response):
        ctx.clear_request_context()
        return response


class NetworkLogMiddleware(MiddlewareMixin):
    """记录每一次 API 交互：方法/路径/状态码/耗时/IP/设备/用户 + 脱敏摘要（§14.3）。"""

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
        return response

    # ------------------------------------------------------------ 内部

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
