"""文件上传服务 API（通用上传 / 文件读取 / 地图背景 / 消息图片）。

文件都在 MEDIA_ROOT 下，对外 URL 为 ``/api/files/view/<相对路径>``，错误响应统一中文 JSON。"""

import json
import mimetypes
import os
import uuid
from pathlib import Path

from django.conf import settings
from django.http import FileResponse
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_manage_competition
from apps.global_.competitions.models import Competition
from apps.global_.files.models import MapBackground

MAX_UPLOAD_SIZE = settings.UPLOAD_MAX_BYTES
MESSAGE_IMAGE_MAX_SIZE = settings.MESSAGE_IMAGE_MAX_BYTES

ALLOWED_UPLOAD_EXTENSIONS = set(settings.UPLOAD_ALLOWED_EXTENSIONS)
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# 文件读取白名单：仅允许读取 MEDIA_ROOT 下这些子目录（plugins/、packages/ 等一律拒绝）
ALLOWED_VIEW_DIRS = ('uploads/', 'map_backgrounds/', 'messages/')

_CONTENT_TYPE_BY_EXT = {
    'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
    'gif': 'image/gif', 'webp': 'image/webp', 'pdf': 'application/pdf',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'csv': 'text/csv', 'zip': 'application/zip', 'txt': 'text/plain', 'md': 'text/markdown',
}


def _error(code: int, message: str) -> Response:
    return Response({'code': code, 'message': message, 'details': ''}, status=code)


def _extension(file_name: str) -> str:
    return Path(file_name or '').suffix.lstrip('.').lower()


def _content_type_for(ext: str, fallback: str = '') -> str:
    guessed, _ = mimetypes.guess_type(f'x.{ext}')
    return _CONTENT_TYPE_BY_EXT.get(ext) or guessed or fallback or 'application/octet-stream'


def _media_root() -> Path:
    return Path(settings.MEDIA_ROOT).resolve()


def _view_url(relative_path: str) -> str:
    return f'/api/files/view/{relative_path}'


def _store_upload(upload, subdir: str) -> str:
    """把上传文件存到 MEDIA_ROOT/<subdir>/<uuid>.<ext>，返回相对路径（POSIX 分隔）。"""
    ext = _extension(upload.name)
    directory = _media_root() / subdir
    directory.mkdir(parents=True, exist_ok=True)
    name = f'{uuid.uuid4().hex}.{ext}' if ext else uuid.uuid4().hex
    target = directory / name
    with open(target, 'wb') as fh:
        for chunk in upload.chunks():
            fh.write(chunk)
    return f'{subdir}/{name}'


def _delete_media_file(relative_path: str) -> None:
    """尽力删除磁盘文件（失败不影响业务）；带路径穿越防护。"""
    try:
        media_root = _media_root()
        target = (media_root / (relative_path or '')).resolve()
        if target.is_relative_to(media_root) and target.is_file():
            os.remove(target)
    except OSError:
        pass


def _parse_transform(raw):
    """解析 transform（dict 或 JSON 字符串）→ {scale, x, y} 或 None；非法输入抛 ValueError。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
        try:
            raw = json.loads(raw)
        except ValueError:
            raise ValueError('transform 需为 JSON 对象（{scale, x, y}）')
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError('transform 需为 JSON 对象（{scale, x, y}）')
    try:
        scale = float(raw.get('scale', 1))
        x = float(raw.get('x', 0))
        y = float(raw.get('y', 0))
    except (TypeError, ValueError):
        raise ValueError('transform 的 scale/x/y 需为数字')
    return {'scale': scale, 'x': x, 'y': y}


def _map_background_data(bg: MapBackground | None) -> dict:
    if bg is None:
        return {'url': '', 'transform': None}
    return {'url': bg.url, 'transform': bg.transform}


class FileUploadView(APIView):
    """`POST /api/files/upload`：通用文件上传（≤100MB、扩展名白名单，落 uploads/YYYY/MM/）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        upload = request.FILES.get('file')
        if upload is None:
            return _error(400, '缺少上传文件（file）')
        ext = _extension(upload.name)
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            return _error(400, '不支持的文件类型，仅允许 png/jpg/jpeg/gif/webp/pdf/xlsx/csv/zip/txt/md')
        if upload.size > MAX_UPLOAD_SIZE:
            return _error(400, '上传文件过大，单个文件不能超过 100MB')

        now = timezone.localtime()
        relative = _store_upload(upload, f'uploads/{now:%Y/%m}')
        return Response({
            'url': _view_url(relative),
            'fileName': upload.name,
            'size': upload.size,
            'contentType': _content_type_for(ext, upload.content_type),
            'uploadedAt': now.isoformat(),
        }, status=201)


class ServeFileView(APIView):
    """`GET /api/files/view/<path:name>`：读取已上传文件（FileResponse + content-type）。

    只允许白名单子目录（uploads/、map_backgrounds/、messages/），plugins/packages 与路径穿越一律拒绝。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, name):
        media_root = _media_root()
        target = (media_root / name).resolve()
        if not target.is_relative_to(media_root) or not target.is_file():
            return _error(404, '文件不存在')
        relative = target.relative_to(media_root).as_posix()
        if not relative.startswith(ALLOWED_VIEW_DIRS):
            return _error(404, '文件不存在')
        content_type, _ = mimetypes.guess_type(str(target))
        return FileResponse(
            open(target, 'rb'),
            content_type=content_type or 'application/octet-stream',
            as_attachment=False,
        )


class MapBackgroundView(APIView):
    """`/api/competitions/{cid}/files/map-background`：地图背景读取与维护。

    GET `{url, transform}`；POST 传图片或 JSON `{url, transform}`（写权限=比赛/系统超级管理员）；
    PATCH 只更新 transform；DELETE 清背景（删记录 + 尽力删盘上文件）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        bg = MapBackground.objects.filter(competition_id=cid).first()
        return Response(_map_background_data(bg))

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _error(403, '没有权限修改该比赛的地图背景')
        competition = Competition.objects.filter(pk=cid).first()
        if competition is None:
            return _error(404, '比赛不存在或已删除')

        upload = request.FILES.get('file')
        previous = MapBackground.objects.filter(competition=competition).first()
        old_file_path = previous.file_path if previous else ''

        if upload is not None:
            ext = _extension(upload.name)
            if ext not in IMAGE_EXTENSIONS:
                return _error(400, '背景图仅支持 png/jpg/jpeg/gif/webp 格式')
            if upload.size > MAX_UPLOAD_SIZE:
                return _error(400, '上传文件过大，单个文件不能超过 100MB')
            try:
                transform = _parse_transform(request.POST.get('transform'))
            except ValueError as exc:
                return _error(400, str(exc))
            relative = _store_upload(upload, f'map_backgrounds/{cid}')
            url = _view_url(relative)
            file_path = relative
        else:
            data = request.data
            if not isinstance(data, dict):
                return _error(400, '请上传背景图文件或提供图片 URL')
            url = (data.get('url') or '').strip() if isinstance(data.get('url'), str) else ''
            if not url:
                return _error(400, '请上传背景图文件或提供图片 URL')
            if len(url) > 2048:
                return _error(400, '图片 URL 过长（不超过 2048 字符）')
            try:
                transform = _parse_transform(data.get('transform'))
            except ValueError as exc:
                return _error(400, str(exc))
            file_path = ''

        bg, _created = MapBackground.objects.update_or_create(
            competition=competition,
            defaults={'url': url, 'file_path': file_path, 'transform': transform},
        )
        if old_file_path and old_file_path != file_path:
            _delete_media_file(old_file_path)  # 替换旧背景：磁盘文件尽力删除
        return Response(_map_background_data(bg))

    def patch(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _error(403, '没有权限修改该比赛的地图背景')
        bg = MapBackground.objects.filter(competition_id=cid).first()
        if bg is None:
            return _error(404, '地图背景不存在')

        data = request.data
        if isinstance(data, dict) and 'transform' in data:
            raw = data.get('transform')
        elif isinstance(data, dict) and any(k in data for k in ('scale', 'x', 'y')):
            raw = data  # 也允许直接提交 transform 对象
        else:
            return _error(400, '缺少 transform')
        try:
            transform = _parse_transform(raw)
        except ValueError as exc:
            return _error(400, str(exc))

        bg.transform = transform
        bg.save(update_fields=['transform', 'updated_at'])
        return Response(_map_background_data(bg))

    def delete(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _error(403, '没有权限修改该比赛的地图背景')
        bg = MapBackground.objects.filter(competition_id=cid).first()
        if bg is not None:
            if bg.file_path:
                _delete_media_file(bg.file_path)
            bg.delete()
        return Response({'ok': True})


class MessageImageUploadView(APIView):
    """`POST /api/messages/upload-image`：站内信图片上传（≤5MB，落 messages/YYYY/MM/，返回 `{url}`）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        upload = request.FILES.get('file')
        if upload is None:
            return _error(400, '缺少上传文件（file）')
        ext = _extension(upload.name)
        if ext not in IMAGE_EXTENSIONS:
            return _error(400, '仅支持 png/jpg/jpeg/gif/webp 图片格式')
        if upload.size > MESSAGE_IMAGE_MAX_SIZE:
            return _error(400, '图片过大，单张图片不能超过 5MB')

        now = timezone.localtime()
        relative = _store_upload(upload, f'messages/{now:%Y/%m}')
        return Response({'url': _view_url(relative)}, status=201)
