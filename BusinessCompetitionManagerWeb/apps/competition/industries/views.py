"""产业字段只读视图（比赛域）：给前端做 key → 中文名 的展示映射。"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_read_competition
from apps.competition.industries.models import IndustryField


def _err(code: int, message: str) -> Response:
    return Response({'code': code, 'message': message, 'details': ''}, status=code)


class IndustryFieldListView(APIView):
    """GET /api/competitions/{cid}/industry-fields —— 本比赛全部产业字段元数据。

    前端只用它把 `cash` / `capacity` 这类字段键换成中文名（字段名取自插件 FIELDS[].name）。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not can_read_competition(request.user, cid):
            return _err(403, '需要比赛成员身份')
        rows = IndustryField.objects.all().order_by('id')
        return Response([
            {
                'id': f.id,
                'key': f.field_key,
                'name': f.name or f.field_key,
                'fieldType': f.field_type,
                'dataTable': f.data_table,
                'pluginKey': f.plugin_key,
            }
            for f in rows
        ])
