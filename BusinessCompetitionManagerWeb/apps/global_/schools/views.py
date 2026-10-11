"""学校 API（§12：GET/POST /api/schools）。"""

from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsSystemSuperAdmin
from apps.global_.schools.models import School


class SchoolListCreateView(APIView):
    def get_permissions(self):
        return [AllowAny()] if self.request.method == 'GET' else [IsSystemSuperAdmin()]

    def get(self, request):
        keyword = request.query_params.get('q', '').strip()
        qs = School.objects.all()
        if keyword:
            qs = qs.filter(name__icontains=keyword)
        return Response([
            {'id': s.id, 'name': s.name, 'region': s.region}
            for s in qs[:200]
        ])

    def post(self, request):
        name = (request.data.get('name') or '').strip()
        region = (request.data.get('region') or '').strip()
        if not name:
            return Response({'code': 400, 'message': '学校名称必填', 'details': ''}, status=400)
        school, created = School.objects.get_or_create(name=name, defaults={'region': region})
        return Response(
            {'id': school.id, 'name': school.name, 'region': school.region},
            status=201 if created else 200,
        )
