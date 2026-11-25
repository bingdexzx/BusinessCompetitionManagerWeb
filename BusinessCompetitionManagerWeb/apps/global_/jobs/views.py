"""后台任务 API（2026-11）：提交任务 + 轮询进度（结算 / 财年开启结束）。"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_manage_competition
from apps.global_.jobs import services as job_services
from apps.global_.jobs.models import BackgroundJob


def _err(message, code=400):
    return Response({'code': code, 'message': message, 'details': ''}, status=code)


class JobListCreateView(APIView):
    """POST 提交任务 / GET 最近任务列表（仅超级管理员）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _err('仅超级管理员可操作', 403)
        rows = (BackgroundJob.objects.using('default')
                .filter(competition_id=cid).order_by('-id')[:20])
        return Response([job_services.serialize(job) for job in rows])

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _err('仅超级管理员可操作', 403)
        kind = str(request.data.get('kind') or '').strip().upper()
        if not kind:
            return _err('缺少任务类型 kind')
        payload = request.data.get('payload')
        if payload is not None and not isinstance(payload, dict):
            return _err('payload 必须是对象')
        try:
            job = job_services.enqueue(kind=kind, competition_id=int(cid),
                                       user=request.user, payload=payload)
        except job_services.JobError as exc:
            return _err(str(exc))
        return Response(job_services.serialize(job), status=201)


class JobDetailView(APIView):
    """GET 单个任务状态（轮询用）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, pk):
        if not can_manage_competition(request.user, cid):
            return _err('仅超级管理员可操作', 403)
        job = (BackgroundJob.objects.using('default')
               .filter(pk=pk, competition_id=cid).first())
        if job is None:
            return _err('任务不存在', 404)
        return Response(job_services.serialize(job))
