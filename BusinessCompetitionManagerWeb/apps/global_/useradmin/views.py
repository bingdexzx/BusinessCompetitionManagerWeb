"""用户管理 API（仅超级管理员）：账号列表 / 新建 / 详情 / 修改 / 删除 / 重置密码。

错误响应统一 ``{'code': 400|403|404, 'message': '中文提示', 'details': ''}``
（风格见 apps.common.errors 与 apps.global_.accounts.views）。对外字段全部 camelCase。
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsSystemSuperAdmin
from apps.global_.schools.models import School
from apps.global_.useradmin.serializers import UserSerializer, memberships_by_user

User = get_user_model()

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
USERNAME_MAX_LENGTH = 150  # AbstractUser.username
DISPLAY_NAME_MAX_LENGTH = 100  # User.display_name
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


# ---------------------------------------------------------------- 基础工具


def _error(message, code=400, details=''):
    """统一错误响应 {code, message, details}（message 一律中文）。"""
    return Response({'code': code, 'message': message, 'details': details}, status=code)


def _clean_str(data, key):
    value = (data or {}).get(key)
    return '' if value is None else str(value).strip()


def _int_param(raw, default, minimum=None, maximum=None):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _validate_password(password):
    """密码校验（8-128 位）；返回中文错误信息或 None。"""
    if not isinstance(password, str) or not password:
        return '密码必填'
    if len(password) < PASSWORD_MIN_LENGTH or len(password) > PASSWORD_MAX_LENGTH:
        return f'密码长度需为 {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} 位'
    return None


def _check_email_unique(email, exclude_pk=None):
    """邮箱唯一校验（忽略大小写）；返回中文错误信息或 None。"""
    qs = User.objects.filter(email__iexact=email)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        return '该邮箱已被使用'
    return None


def _normalize_email(raw):
    """清洗邮箱：空 → None；非法格式 → (None, 错误信息)。"""
    email = '' if raw is None else str(raw).strip()
    if not email:
        return None, None
    try:
        validate_email(email)
    except DjangoValidationError:
        return None, '邮箱格式不正确'
    return email, None


def _normalize_school_id(raw):
    """清洗 schoolId：空 → None（清空学校）；无效 → (None, 错误信息)。"""
    if raw is None or raw == '':
        return None, None
    try:
        school_id = int(raw)
    except (TypeError, ValueError):
        return None, '学校不存在'
    if not School.objects.filter(pk=school_id).exists():
        return None, '学校不存在'
    return school_id, None


def _normalize_bool(raw, label):
    """清洗布尔字段；非法 → (None, 错误信息)。"""
    if isinstance(raw, bool):
        return raw, None
    return None, f'{label}需为布尔值'


def _user_detail(user):
    """账号详情载荷（同列表项字段 + memberships）。"""
    return Response(UserSerializer(user).data)


# ---------------------------------------------------------------- 视图


class UserListCreateView(APIView):
    """GET /api/users 分页列表（q 模糊搜索）；POST /api/users 新建账号。"""

    permission_classes = [IsSystemSuperAdmin]

    def get(self, request):
        page = _int_param(request.query_params.get('page'), 1, minimum=1)
        page_size = _int_param(
            request.query_params.get('pageSize'), DEFAULT_PAGE_SIZE,
            minimum=1, maximum=MAX_PAGE_SIZE,
        )
        keyword = (request.query_params.get('q') or '').strip()

        qs = User.objects.select_related('school').order_by('-date_joined', '-id')
        if keyword:
            qs = qs.filter(
                Q(username__icontains=keyword)
                | Q(display_name__icontains=keyword)
                | Q(email__icontains=keyword)
            )
        total = qs.count()
        items = list(qs[(page - 1) * page_size: page * page_size])
        serializer = UserSerializer(
            items, many=True, context={'memberships_by_user': memberships_by_user(items)},
        )
        return Response({
            'items': serializer.data,
            'total': total,
            'page': page,
            'pageSize': page_size,
        })

    def post(self, request):
        data = request.data or {}
        username = _clean_str(data, 'username')
        password = data.get('password')
        display_name = _clean_str(data, 'displayName')
        email_raw = data.get('email')
        school_raw = data.get('schoolId')
        superuser_raw = data.get('isSuperuser')

        if not username:
            return _error('用户名必填')
        if len(username) > USERNAME_MAX_LENGTH:
            return _error(f'用户名最长 {USERNAME_MAX_LENGTH} 个字符')
        if User.objects.filter(username=username).exists():
            return _error('用户名已存在')

        password_error = _validate_password(password)
        if password_error:
            return _error(password_error)

        if not display_name:
            return _error('显示名必填')
        if len(display_name) > DISPLAY_NAME_MAX_LENGTH:
            return _error(f'显示名最长 {DISPLAY_NAME_MAX_LENGTH} 个字符')

        email, email_error = _normalize_email(email_raw)
        if email_error:
            return _error(email_error)
        if email:
            unique_error = _check_email_unique(email)
            if unique_error:
                return _error(unique_error)

        school_id, school_error = _normalize_school_id(school_raw)
        if school_error:
            return _error(school_error)

        is_superuser = False
        if superuser_raw is not None:
            is_superuser, bool_error = _normalize_bool(superuser_raw, '是否超级管理员')
            if bool_error:
                return _error(bool_error)

        user = User(
            username=username,
            display_name=display_name,
            email=email,
            school_id=school_id,
            is_superuser=is_superuser,
            is_staff=is_superuser,
        )
        user.set_password(password)
        user.save()
        return Response(UserSerializer(user).data, status=201)


class UserDetailView(APIView):
    """GET/PATCH/DELETE /api/users/<pk>：详情 / 修改 / 删除。"""

    permission_classes = [IsSystemSuperAdmin]

    def get(self, request, pk):
        user = User.objects.select_related('school').filter(pk=pk).first()
        if user is None:
            return _error('用户不存在', 404)
        return _user_detail(user)

    def patch(self, request, pk):
        user = User.objects.select_related('school').filter(pk=pk).first()
        if user is None:
            return _error('用户不存在', 404)
        data = request.data or {}
        was_superuser = user.is_superuser
        was_active = user.is_active

        if 'displayName' in data:
            display_name = _clean_str(data, 'displayName')
            if not display_name:
                return _error('显示名必填')
            if len(display_name) > DISPLAY_NAME_MAX_LENGTH:
                return _error(f'显示名最长 {DISPLAY_NAME_MAX_LENGTH} 个字符')
            user.display_name = display_name

        if 'email' in data:
            email, email_error = _normalize_email(data.get('email'))
            if email_error:
                return _error(email_error)
            if email:
                unique_error = _check_email_unique(email, exclude_pk=user.pk)
                if unique_error:
                    return _error(unique_error)
            user.email = email  # 空邮箱置空（None）

        if 'schoolId' in data:
            school_id, school_error = _normalize_school_id(data.get('schoolId'))
            if school_error:
                return _error(school_error)
            user.school_id = school_id

        if 'isActive' in data:
            is_active, bool_error = _normalize_bool(data.get('isActive'), '是否启用')
            if bool_error:
                return _error(bool_error)
            user.is_active = is_active

        if 'isSuperuser' in data:
            is_superuser, bool_error = _normalize_bool(data.get('isSuperuser'), '是否超级管理员')
            if bool_error:
                return _error(bool_error)
            user.is_superuser = is_superuser
            user.is_staff = is_superuser

        # 权限收窄（取消超级管理员 / 停用账号）保护 + 顶号：
        # 最后一个活跃超级管理员不允许被降级/停用（否则系统无人可管理）。
        demoted = was_superuser and not user.is_superuser
        deactivated = was_active and not user.is_active
        if demoted or deactivated:
            if (was_superuser and was_active
                    and not User.objects.filter(is_superuser=True, is_active=True)
                    .exclude(pk=user.pk).exists()):
                if demoted:
                    return _error('不能取消最后一个超级管理员')
                return _error('不能停用最后一个超级管理员')

        user.save()
        if demoted or deactivated:
            user.bump_token_version()  # 顶号：该账号已发 JWT 全部失效（tokenVersion +1）
        return _user_detail(user)

    def delete(self, request, pk):
        user = User.objects.filter(pk=pk).first()
        if user is None:
            return _error('用户不存在', 404)
        # 两条删除保护都强制生效；顺序仅影响命中哪条中文提示：
        # 1) 目标是最后一个系统超级管理员（含「唯一超级管理员删除自己」的场景，此时先命中本条）；
        # 2) 目标是当前登录账号（不能删自己）。
        if user.is_superuser and User.objects.filter(is_superuser=True).count() <= 1:
            return _error('不能删除最后一个超级管理员')
        if user.pk == request.user.pk:
            return _error('不能删除当前登录账号')
        user.delete()
        return Response({'ok': True})


class UserPasswordResetView(APIView):
    """POST /api/users/<pk>/password：重置密码并顶号（已发 JWT 全部失效）。"""

    permission_classes = [IsSystemSuperAdmin]

    def post(self, request, pk):
        user = User.objects.filter(pk=pk).first()
        if user is None:
            return _error('用户不存在', 404)
        password_error = _validate_password((request.data or {}).get('password'))
        if password_error:
            return _error(password_error)
        user.set_password((request.data or {}).get('password'))
        user.save()
        user.bump_token_version()  # 顶号：使该账号已发 JWT 全部失效（tokenVersion +1）
        return Response({'ok': True, 'message': '密码已重置'})
