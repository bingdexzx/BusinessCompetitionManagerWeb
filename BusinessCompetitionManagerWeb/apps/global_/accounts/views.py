"""账号视图：注册 / 登录（含设备登记）/ 刷新 / 个人信息（一账号多身份）。"""

import hashlib

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.common import context as ctx
from apps.common.devices import device_snapshot
from apps.common.permissions import IsSystemSuperAdmin
from apps.global_.accounts import throttle
from apps.global_.accounts.models import UpdateLog
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
    """登录并登记设备；返回 JWT + 用户信息（含各比赛身份）。

    带**登录失败限流**（旧系统等价能力）：同一 用户名|IP 5 分钟内失败 N 次 → 锁定，
    锁定期间即使密码正确也拒绝（429），防止爆破。
    """

    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username', '')
        password = request.data.get('password', '')

        key = throttle.throttle_key(username, request)
        until = throttle.locked_until(key)
        if until is not None:
            minutes = max(1, int((until - timezone.now()).total_seconds() // 60) + 1)
            return Response(
                {'code': 429, 'message': f'登录失败次数过多，账号已锁定，请 {minutes} 分钟后重试',
                 'details': ''},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={'Retry-After': str(int((until - timezone.now()).total_seconds()) + 1)},
            )

        user = User.objects.filter(username=username).first()
        if user is None or not user.check_password(password) or not user.is_active:
            throttle.record_failure(key)
            return Response(
                {'code': 401, 'message': '用户名或密码错误', 'details': ''},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        throttle.record_success(key)
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


class ChangePasswordView(APIView):
    """修改密码（旧密码校验）；改密后**顶号**——已发 JWT 全部失效，需重新登录。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        old_password = request.data.get('oldPassword', '')
        new_password = request.data.get('newPassword', '')
        user = request.user
        if not user.check_password(old_password or ''):
            return Response(
                {'code': 400, 'message': '原密码错误', 'details': ''},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not isinstance(new_password, str) or not (8 <= len(new_password) <= 128):
            return Response(
                {'code': 400, 'message': '新密码长度需为 8-128 位', 'details': ''},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if user.check_password(new_password):
            return Response(
                {'code': 400, 'message': '新密码不能与原密码相同', 'details': ''},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(new_password)
        user.save(update_fields=['password'])
        user.bump_token_version()  # 顶号：所有已发 JWT（含本会话）立即失效
        ctx.set_log_user(user)
        return Response({'ok': True, 'message': '密码已修改，请重新登录'})


class VersionView(APIView):
    """版本下发（旧系统 /api/version 等价）：前端轮询比对，不一致硬封锁。"""

    permission_classes = [AllowAny]

    def get(self, request):
        from django.conf import settings as dj_settings
        return Response({'version': getattr(dj_settings, 'APP_VERSION', '0.0.0')})


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
        if 'avatar' in request.data:
            avatar = str(request.data.get('avatar') or '').strip()
            if len(avatar) > 500:
                return Response(
                    {'code': 400, 'message': '头像地址过长', 'details': ''}, status=400)
            user.avatar = avatar
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


def _update_log_data(log: UpdateLog) -> dict:
    return {
        'id': log.id,
        'version': log.version,
        'title': log.title,
        'content': log.content,
        'createdByUsername': log.created_by_username,
        'publishedAt': log.published_at.isoformat(),
    }


class UpdateLogListView(APIView):
    """更新日志列表 / 发布（仅系统超级管理员）。"""

    permission_classes = [IsSystemSuperAdmin]

    def get(self, request):
        return Response([_update_log_data(log) for log in UpdateLog.objects.all()[:100]])

    def post(self, request):
        version = str(request.data.get('version') or '').strip()
        title = str(request.data.get('title') or '').strip()
        content = str(request.data.get('content') or '').strip()
        if not version:
            return Response({'code': 400, 'message': '请填写版本号', 'details': ''}, status=400)
        if not title:
            return Response({'code': 400, 'message': '请填写更新标题', 'details': ''}, status=400)
        if not content:
            return Response({'code': 400, 'message': '请填写更新内容', 'details': ''}, status=400)
        if len(version) > 40 or len(title) > 120:
            return Response({'code': 400, 'message': '版本号或标题过长', 'details': ''}, status=400)
        if UpdateLog.objects.filter(version=version).exists():
            return Response({'code': 400, 'message': '该版本号已存在', 'details': ''}, status=400)
        log = UpdateLog.objects.create(
            version=version,
            title=title,
            content=content,
            created_by=request.user,
            created_by_username=request.user.username,
        )
        # 发布人默认已读，避免下次登录看到自己刚发布的更新
        request.user.update_log_seen_id = log.id
        request.user.save(update_fields=['update_log_seen_id'])
        cache.delete('updatelog:latest:v1')
        return Response(_update_log_data(log), status=status.HTTP_201_CREATED)


class UpdateLogLatestView(APIView):
    """当前用户是否需要看最新更新（按已读游标判断）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cached = cache.get('updatelog:latest:v1')
        if cached is None:
            log = UpdateLog.objects.order_by('-published_at', '-id').first()
            cached = {
                'id': log.id if log is not None else 0,
                'data': _update_log_data(log) if log is not None else None,
            }
            cache.set('updatelog:latest:v1', cached, 15)
        seen = request.user.update_log_seen_id or 0
        return Response({
            'log': cached['data'],
            'shouldShow': bool(cached['id'] and cached['id'] > seen),
        })


class UpdateLogReadView(APIView):
    """关闭更新弹窗后推进已读游标；只前进不后退。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        log = get_object_or_404(UpdateLog, pk=pk)
        if log.id > (request.user.update_log_seen_id or 0):
            request.user.update_log_seen_id = log.id
            request.user.save(update_fields=['update_log_seen_id'])
        return Response({'seen': request.user.update_log_seen_id})

