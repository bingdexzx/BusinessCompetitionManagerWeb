"""学校 API（§12：GET/POST /api/schools、GET/PATCH/DELETE /api/schools/<pk>）。

学校是组织主数据，由办赛方（系统超管）维护：
- 读（列表/搜索/详情）：公开——注册页与个人档案选学校时未登录/任意角色都要能搜到；
- 写（新建/修改/删除）：仅系统超管。

删除学校不删账号：``User.school`` 为 ``SET_NULL``，仅把账号的学校置空。
"""

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsSystemSuperAdmin
from apps.global_.schools.models import School

NAME_MAX_LENGTH = 120


def _error(message: str, code: int = 400) -> Response:
    return Response({'code': code, 'message': message, 'details': ''}, status=code)


def _school_data(school: School) -> dict:
    return {'id': school.id, 'name': school.name, 'region': school.region}


def _clean_name(raw):
    """清洗学校名称；返回 (name, 错误响应)。"""
    name = (raw or '').strip() if isinstance(raw, str) else ''
    if not name:
        return None, _error('学校名称必填')
    if len(name) > NAME_MAX_LENGTH:
        return None, _error(f'学校名称最长 {NAME_MAX_LENGTH} 个字符')
    return name, None


class SchoolListCreateView(APIView):
    """GET /api/schools?q= 列表搜索；POST /api/schools 新建（系统超管）。"""

    def get_permissions(self):
        return [AllowAny()] if self.request.method == 'GET' else [IsSystemSuperAdmin()]

    def get(self, request):
        keyword = (request.query_params.get('q') or '').strip()
        qs = School.objects.all()
        if keyword:
            qs = qs.filter(name__icontains=keyword)
        return Response([_school_data(s) for s in qs[:200]])

    def post(self, request):
        name, error = _clean_name(request.data.get('name'))
        if error is not None:
            return error
        if School.objects.filter(name=name).exists():
            return _error('学校名称已存在')
        school = School.objects.create(
            name=name, region=(request.data.get('region') or '').strip())
        return Response(_school_data(school), status=201)


class SchoolDetailView(APIView):
    """GET /api/schools/<pk>；PATCH 改名/地区、DELETE 删除（写操作仅系统超管）。"""

    def get_permissions(self):
        return [AllowAny()] if self.request.method == 'GET' else [IsSystemSuperAdmin()]

    def get(self, request, pk):
        school = School.objects.filter(pk=pk).first()
        if school is None:
            return _error('学校不存在', 404)
        return Response(_school_data(school))

    def patch(self, request, pk):
        school = School.objects.filter(pk=pk).first()
        if school is None:
            return _error('学校不存在', 404)
        if 'name' in request.data:
            name, error = _clean_name(request.data.get('name'))
            if error is not None:
                return error
            if School.objects.filter(name=name).exclude(pk=pk).exists():
                return _error('学校名称已存在')
            school.name = name
        if 'region' in request.data:
            school.region = (request.data.get('region') or '').strip()
        school.save()
        return Response(_school_data(school))

    def delete(self, request, pk):
        school = School.objects.filter(pk=pk).first()
        if school is None:
            return _error('学校不存在', 404)
        school.delete()  # User.school 走 SET_NULL：账号保留，仅清空学校
        return Response({'ok': True})
