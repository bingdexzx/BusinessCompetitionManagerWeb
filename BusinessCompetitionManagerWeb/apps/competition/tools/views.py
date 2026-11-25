"""工具箱计时器视图（比赛域，路由挂 /api 前缀下）。

计时器 = 名称 + **倒计时时长**：从创建时刻开始倒数，前端按秒显示剩余时间。

**按用户隔离**：每个账号只看到、只能改/删自己创建的计时器（别人的既不可见也不可操作）。
权限前提仍是本比赛成员。
"""


from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_read_competition
from apps.competition.tools.models import CompetitionTimer

# 单次倒计时上限：30 天（防止误填成超大数导致前端显示异常）
MAX_DURATION_SECONDS = settings.TIMER_MAX_DURATION_DAYS * 24 * 3600


def _err(code: int, message: str) -> Response:
    return Response({'code': code, 'message': message, 'details': ''}, status=code)


def _own_timers(request):
    """当前账号自己的计时器（按用户隔离）。"""
    return CompetitionTimer.objects.filter(created_by=getattr(request.user, 'id', None))


def _timer_data(timer: CompetitionTimer) -> dict:
    return {
        'id': timer.id,
        'name': timer.name,
        'durationSeconds': timer.duration_seconds,
        'startedAt': timer.started_at.isoformat(),
        'targetAt': timer.target_at.isoformat(),
        'remainingSeconds': timer.remaining_seconds(),
        'note': timer.note or '',
        'createdByUsername': timer.created_by_username or '',
        'createdAt': timer.created_at.isoformat(),
        'updatedAt': timer.updated_at.isoformat(),
    }


def _parse_duration(value):
    """倒计时时长（秒）：接受数字或数字字符串；非法/非正返回 None。"""
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return None
    if seconds <= 0 or seconds > MAX_DURATION_SECONDS:
        return None
    return seconds


class CompetitionTimerListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not can_read_competition(request.user, cid):
            return _err(status.HTTP_403_FORBIDDEN, '无权查看该比赛的计时器')
        rows = _own_timers(request)
        return Response({'items': [_timer_data(row) for row in rows]})

    def post(self, request, cid):
        if not can_read_competition(request.user, cid):
            return _err(status.HTTP_403_FORBIDDEN, '无权为该比赛添加计时器')
        name = str(request.data.get('name') or '').strip()
        if not name:
            return _err(status.HTTP_400_BAD_REQUEST, '请填写计时器名称')
        seconds = _parse_duration(request.data.get('durationSeconds'))
        if seconds is None:
            return _err(status.HTTP_400_BAD_REQUEST, '请填写大于 0 的倒计时时长（最长 30 天）')
        timer = CompetitionTimer.objects.create(
            name=name[:120],
            duration_seconds=seconds,
            started_at=timezone.now(),
            note=str(request.data.get('note') or '').strip()[:255],
            created_by=getattr(request.user, 'id', None),
            created_by_username=getattr(request.user, 'username', '') or '',
        )
        return Response(_timer_data(timer), status=status.HTTP_201_CREATED)


class CompetitionTimerDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, cid, pk):
        if not can_read_competition(request.user, cid):
            return None, _err(status.HTTP_403_FORBIDDEN, '无权操作该比赛的计时器')
        # 只查自己名下的：别人的计时器一律当「不存在」，不泄露是否存在
        timer = _own_timers(request).filter(pk=pk).first()
        if timer is None:
            return None, _err(status.HTTP_404_NOT_FOUND, '计时器不存在')
        return timer, None

    def patch(self, request, cid, pk):
        timer, error = self._get(request, cid, pk)
        if error is not None:
            return error
        if 'name' in request.data:
            name = str(request.data.get('name') or '').strip()
            if not name:
                return _err(status.HTTP_400_BAD_REQUEST, '请填写计时器名称')
            timer.name = name[:120]
        if 'durationSeconds' in request.data:
            seconds = _parse_duration(request.data.get('durationSeconds'))
            if seconds is None:
                return _err(status.HTTP_400_BAD_REQUEST, '请填写大于 0 的倒计时时长（最长 30 天）')
            timer.duration_seconds = seconds
            timer.started_at = timezone.now()   # 改时长 = 重新开始计时
        if 'note' in request.data:
            timer.note = str(request.data.get('note') or '').strip()[:255]
        timer.save()
        return Response(_timer_data(timer))

    def delete(self, request, cid, pk):
        timer, error = self._get(request, cid, pk)
        if error is not None:
            return error
        timer.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
