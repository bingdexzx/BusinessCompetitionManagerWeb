"""比赛包 API（§12：POST .../package 上传→建库→导入，返回报告）。"""

import os
import tempfile

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import (
    IsSystemOrCompetitionSuperAdmin, IsSystemSuperAdmin, get_membership,
)
from apps.competition.contracts.services import contract_types_for_competition
from apps.global_.competitions.models import Competition
from apps.global_.packages import importer
from apps.global_.packages.models import Package
from apps.global_.plugins.models import PluginRegistry


def _package_data(p: Package) -> dict:
    return {
        'id': p.id,
        'fileName': p.file_name,
        'sha256': p.sha256,
        'status': p.status,
        'report': p.import_report,
        'createdBy': p.created_by,
        'createdByUsername': p.created_by_username,
        'createdAt': p.created_at.isoformat(),
    }


class PackageUploadView(APIView):
    """上传比赛包（multipart: file）→ 解析/建库/导入 → 返回导入报告。

    权限：系统超管 / 本比赛超管（§15.2；M1 阶段上传权限严格管控，§5.4 护栏 1）。
    """

    permission_classes = [IsSystemOrCompetitionSuperAdmin]

    def post(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        upload = request.FILES.get('file')
        if upload is None:
            return Response({'code': 400, 'message': '缺少上传文件（file）', 'details': ''}, status=400)
        if not upload.name.lower().endswith('.zip'):
            return Response({'code': 400, 'message': '比赛包必须是 .zip 压缩包', 'details': ''}, status=400)

        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
            for chunk in upload.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        try:
            package = importer.import_package(
                competition=competition, zip_path=tmp_path,
                file_name=upload.name, user=request.user,
            )
        except importer.ImportFailure as exc:
            return Response({
                'code': 422, 'message': '比赛包导入失败', 'details': exc.report,
            }, status=422)
        finally:
            os.unlink(tmp_path)

        return Response(_package_data(package), status=status.HTTP_201_CREATED)


class PackageListView(APIView):
    """比赛包导入历史（含报告）。"""

    permission_classes = [IsSystemOrCompetitionSuperAdmin]

    def get(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        packages = competition.packages.all()[:20]
        return Response([_package_data(p) for p in packages])


class ContractTypeListView(APIView):
    """导入后自动暴露的合同类型接口（§12：GET .../contract-types，含 schema）。

    可见性与比赛详情一致（系统超管或本比赛成员）——参赛代表创建合同需要 schema。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        if not (request.user.is_superuser or get_membership(request.user, cid)):
            return Response({'code': 403, 'message': '无权查看该比赛', 'details': ''}, status=403)
        return Response(contract_types_for_competition(competition))


class PluginRegistryView(APIView):
    """插件管理：已注册的不可变插件版本（§13 系统/插件管理，仅系统超管）。"""

    permission_classes = [IsSystemSuperAdmin]

    def get(self, request):
        qs = PluginRegistry.objects.all()
        if request.query_params.get('kind'):
            qs = qs.filter(kind=request.query_params['kind'].upper())
        return Response([
            {
                'id': p.id, 'kind': p.kind, 'key': p.key, 'name': p.name,
                'version': p.version, 'sha256': p.sha256, 'fileName': p.file_name,
                'numberPrefix': p.number_prefix,
                'uploadedBy': p.uploaded_by, 'uploadedByUsername': p.uploaded_by_username,
                'auditTrail': p.audit_trail, 'createdAt': p.created_at.isoformat(),
            }
            for p in qs[:200]
        ])
