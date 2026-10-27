"""财年 API（§12：开启/结束财年、备份记录、补录合同入口）。"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_manage_competition, user_company_ids, user_membership
from apps.competition.fiscal import services as fiscal_services
from apps.competition.fiscal.models import FiscalYear, FiscalYearBackup


def _require_member(user, cid) -> bool:
    """读权限：本比赛成员（系统超管恒通过；对齐 basedata.views._require_member）。"""
    if user is not None and user.is_authenticated:
        if user.is_superuser:
            return True
        if user_membership(user, cid) is not None:
            return True
        if user_company_ids(user, cid):
            return True
    return False


class FiscalYearListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not _require_member(request.user, cid):
            return Response({'code': 403, 'message': '需要比赛成员身份', 'details': ''}, status=403)
        years = FiscalYear.objects.all().order_by('year')
        return Response([
            {
                'id': fy.id, 'year': fy.year, 'status': fy.status,
                'statusLabel': fy.get_status_display(),
                'openedAt': fy.opened_at.isoformat(),
                'closedAt': fy.closed_at.isoformat() if fy.closed_at else None,
                'backupCount': fy.backups.count(),
            }
            for fy in years
        ])


class FiscalYearOpenView(APIView):
    """开启财年（超级管理员，§10.2）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return Response({'code': 403, 'message': '需要超级管理员权限', 'details': ''}, status=403)
        try:
            fy = fiscal_services.open_fiscal_year(user=request.user)
        except fiscal_services.FiscalError as exc:
            return Response({'code': 400, 'message': str(exc), 'details': ''}, status=400)
        return Response({'id': fy.id, 'year': fy.year, 'status': fy.status}, status=201)


class FiscalYearCloseView(APIView):
    """结束财年（自动备份各公司字段数据表，§2.2 阶段五）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return Response({'code': 403, 'message': '需要超级管理员权限', 'details': ''}, status=403)
        try:
            fy = fiscal_services.close_fiscal_year(user=request.user)
        except fiscal_services.FiscalError as exc:
            return Response({'code': 400, 'message': str(exc), 'details': ''}, status=400)
        return Response({'id': fy.id, 'year': fy.year, 'status': fy.status})


class FiscalYearBackupListView(APIView):
    """备份记录（财年末数据表快照）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid, fy_id):
        if not _require_member(request.user, cid):
            return Response({'code': 403, 'message': '需要比赛成员身份', 'details': ''}, status=403)
        backups = FiscalYearBackup.objects.filter(fiscal_year_id=fy_id).select_related('company')
        return Response([
            {
                'id': b.id, 'companyId': b.company_id, 'companyName': b.company.name,
                'snapshot': b.snapshot, 'createdAt': b.created_at.isoformat(),
            }
            for b in backups
        ])
