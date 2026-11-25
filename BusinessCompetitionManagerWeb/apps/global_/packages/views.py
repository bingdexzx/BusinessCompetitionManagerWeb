"""比赛包 API（§12：POST .../package 上传→建库→导入，返回报告）。"""

import os
import tempfile
import uuid

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

    权限：系统超级管理员 / 本比赛超级管理员（§15.2；M1 阶段上传权限严格管控，§5.4 护栏 1）。
    """

    permission_classes = [IsSystemOrCompetitionSuperAdmin]

    def post(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        upload = request.FILES.get('file')
        if upload is None:
            return Response({'code': 400, 'message': '缺少上传文件（file）', 'details': ''}, status=400)
        if not upload.name.lower().endswith('.zip'):
            return Response({'code': 400, 'message': '比赛包必须是 .zip 压缩包', 'details': ''}, status=400)

        # 后台导入：先把 zip 落盘，再入队（导入可能建库+迁移，耗时长）
        async_flag = str(request.data.get('async') or '').lower() in ('1', 'true', 'yes')
        if async_flag:
            from django.core.files.base import ContentFile
            from django.core.files.storage import default_storage

            from apps.global_.jobs import services as job_services

            stored = default_storage.save(
                f'packages/pending/{uuid.uuid4().hex}.zip',
                ContentFile(b''.join(upload.chunks())),
            )
            job = job_services.enqueue(
                kind='PACKAGE_IMPORT', competition_id=competition.id,
                user=request.user,
                payload={'storedPath': stored, 'fileName': upload.name},
            )
            return Response({'job': job_services.serialize(job)}, status=status.HTTP_202_ACCEPTED)

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

    可见性与比赛详情一致（系统超级管理员或本比赛成员）——参赛代表创建合同需要 schema。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        if not (request.user.is_superuser or get_membership(request.user, cid)):
            return Response({'code': 403, 'message': '无权查看该比赛', 'details': ''}, status=403)
        return Response(contract_types_for_competition(competition))


class IndustryListView(APIView):
    """本比赛**已导入**的产业插件（组队分配公司时「选择产业」的下拉数据）。

    只列已导入的产业：只有它们才了解对应的产业插件，能给公司初始化字段值；
    手工乱填产业标识会导致公司建出来却没有字段数据。

    可见性与合同类型一致（系统超级管理员或本比赛成员）。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        if not (request.user.is_superuser or get_membership(request.user, cid)):
            return Response({'code': 403, 'message': '无权查看该比赛', 'details': ''}, status=403)
        from apps.global_.packages.models import PackagePlugin

        seen, rows = set(), []
        links = (
            PackagePlugin.objects
            .filter(package__competition=competition, kind='INDUSTRY')
            .select_related('plugin')
            .order_by('-id')
        )
        for link in links:
            if link.key in seen:
                continue
            seen.add(link.key)
            rows.append({
                'key': link.key,
                'name': link.plugin.name or link.key,
                'version': link.version,
            })
        rows.sort(key=lambda r: r['name'])
        return Response(rows)


class PluginRegistryView(APIView):
    """插件管理：已注册的不可变插件版本（§13 系统/插件管理，仅系统超级管理员）。

    ``?competitionId=<cid>`` 时只返回该比赛导入过的插件（经 PackagePlugin 关联），
    实现「合同/产业插件按比赛隔离」。
    """

    permission_classes = [IsSystemSuperAdmin]

    def get(self, request):
        qs = PluginRegistry.objects.all()

        competition_id = request.query_params.get('competitionId') or request.query_params.get('cid')
        if competition_id:
            try:
                competition_id = int(competition_id)
            except (TypeError, ValueError):
                return Response(
                    {'code': 400, 'message': 'competitionId 非法', 'details': ''}, status=400)
            qs = qs.filter(
                package_links__package__competition_id=competition_id).distinct()

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
