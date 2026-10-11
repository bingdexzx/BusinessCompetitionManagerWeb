"""账号视图：注册 / 登录（含设备登记）/ 刷新 / 个人信息（一账号多身份）。"""

import hashlib

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.common import context as ctx
from apps.common.devices import device_snapshot
from apps.global_.accounts.serializers import RegisterSerializer, UserSerializer
from apps.global_.logs.models import Device

User = get_user_model()


def register_device(user, request) -> Device:
    """登录时登记/更新设备实体（决策 D19）。"""
    snap = device_snapshot(request)
    device_key = hashlib.sha256(
        f'{snap["ua"]}|{snap["screen"]}|{snap["os"]}|{snap["browser"]}'.encode()
    ).hexdigest()[:64]
    device, _ = Device.objects.get_or_create(
        user=user,
        device_key=device_key,
        defaults={
            'ua': snap['ua'], 'os': snap['os'], 'browser': snap['browser'],
            'screen': snap['screen'], 'ip': snap['ip'] or None,
        },
    )
    changed = False
    if device.ip != (snap['ip'] or None):
        device.ip = snap['ip'] or None
        changed = True
    if changed:
        device.save(update_fields=['ip'])
    ctx.set_device_snapshot(snap)
    return device


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        register_device(user, request)
        ctx.set_log_user(user)  # 网络日志归属（§14.1）
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """登录并登记设备；返回 JWT + 用户信息（含各比赛身份）。"""

    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username', '')
        password = request.data.get('password', '')
        user = User.objects.filter(username=username).first()
        if user is None or not user.check_password(password) or not user.is_active:
            return Response(
                {'code': 401, 'message': '用户名或密码错误', 'details': ''},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        register_device(user, request)
        ctx.set_log_user(user)
        refresh = RefreshToken.for_user(user)
        refresh['tv'] = user.token_version
        refresh['username'] = user.username
        refresh['is_superuser'] = user.is_superuser
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data,
        })


class GipfelTokenRefreshView(TokenRefreshView):
    """刷新访问令牌（携带 tokenVersion 校验）。"""

    permission_classes = [AllowAny]


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        user = request.user
        if 'displayName' in request.data:
            user.display_name = request.data.get('displayName') or ''
        if 'email' in request.data:
            email = (request.data.get('email') or '').strip()
            if email:
                exists = (
                    get_user_model().objects
                    .filter(email__iexact=email)
                    .exclude(pk=user.pk)
                    .exists()
                )
                if exists:
                    return Response({'code': 400, 'message': '该邮箱已被使用', 'details': ''}, status=400)
            user.email = email or None
        if 'schoolId' in request.data:
            school_id = request.data.get('schoolId')
            from apps.global_.schools.models import School
            if school_id is not None and not School.objects.filter(pk=school_id).exists():
                return Response({'code': 400, 'message': '学校不存在', 'details': ''}, status=400)
            user.school_id = school_id
        user.save()
        return Response(UserSerializer(user).data)


class MyDevicesView(APIView):
    """个人档案可查看**本人**登录设备列表（§14.4）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        devices = Device.objects.filter(user=request.user).order_by('-last_login_at')
        return Response([
            {
                'id': d.id, 'os': d.os, 'browser': d.browser, 'screen': d.screen,
                'ip': d.ip, 'ua': d.ua,
                'firstLoginAt': d.first_login_at.isoformat(),
                'lastLoginAt': d.last_login_at.isoformat(),
            }
            for d in devices
        ])
