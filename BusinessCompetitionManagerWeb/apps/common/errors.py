"""统一业务错误响应：{code, message, details} —— **message 一律中文**（面向最终用户）。

DRF 默认异常文案是英文（Not found. / Authentication credentials were not provided. 等），
这里按异常类型/状态码翻译成简洁中文；details 保留原始信息供排查。
"""

from rest_framework import exceptions as drf_exceptions
from rest_framework.views import exception_handler

# 状态码 → 简洁中文兜底（异常类型未命中时使用）
_STATUS_MESSAGES = {
    400: '请求参数有误',
    401: '请先登录',
    403: '没有权限执行此操作',
    404: '请求的内容不存在',
    405: '不支持的请求方法',
    409: '操作冲突，请刷新后重试',
    413: '上传内容过大',
    415: '不支持的内容类型',
    429: '请求过于频繁，请稍后再试',
    500: '服务器内部错误，请稍后重试',
    502: '网关错误，请稍后重试',
    503: '服务器繁忙，请稍后重试',
    504: '服务器响应超时，请稍后重试',
}

# 异常类型 → 中文文案（优先于状态码兜底）
_EXCEPTION_MESSAGES = {
    drf_exceptions.NotAuthenticated: '请先登录',
    drf_exceptions.AuthenticationFailed: '登录已过期，请重新登录',
    drf_exceptions.PermissionDenied: '没有权限执行此操作',
    drf_exceptions.NotFound: '请求的内容不存在',
    drf_exceptions.MethodNotAllowed: '不支持的请求方法',
    drf_exceptions.NotAcceptable: '不支持的返回格式',
    drf_exceptions.UnsupportedMediaType: '不支持的上传类型',
    drf_exceptions.Throttled: '请求过于频繁，请稍后再试',
    drf_exceptions.ValidationError: '请求参数有误',
    drf_exceptions.ParseError: '请求数据格式错误',
}


def _chinese_message(exc, status_code: int) -> str:
    for exc_type, message in _EXCEPTION_MESSAGES.items():
        if isinstance(exc, exc_type):
            return message
    return _STATUS_MESSAGES.get(status_code, '请求失败')


def _collect_texts(detail) -> list:
    """把 DRF 校验错误（``{字段: [消息]}`` 可嵌套）摊平成文本列表。"""
    if isinstance(detail, dict):
        texts = []
        for value in detail.values():
            texts.extend(_collect_texts(value))
        return texts
    if isinstance(detail, (list, tuple)):
        texts = []
        for value in detail:
            texts.extend(_collect_texts(value))
        return texts
    if isinstance(detail, str) and detail.strip():
        return [detail.strip()]
    return []


def gipfel_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None
    data = response.data
    # 认证/权限类异常形如 {"detail": "..."}；序列化器校验错误则是 {字段: [消息]}。
    # 旧实现一律取 .get('detail')，导致字段级错误被丢成 details=None（用户只看到
    # 「请求参数有误」，看不到"缺什么/哪里不对"），这里按结构分别处理。
    if isinstance(data, dict) and set(data.keys()) == {'detail'}:
        detail = data['detail']
    else:
        detail = data

    message = _chinese_message(exc, response.status_code)
    # 校验类错误：把字段级中文原因直接作为 message（一眼可见），原始结构保留在 details
    if isinstance(exc, drf_exceptions.ValidationError):
        texts = list(dict.fromkeys(_collect_texts(detail)))
        if texts:
            message = '；'.join(texts)[:200]
    response.data = {
        'code': response.status_code,
        'message': message,
        # details 保留原始信息（字段级错误结构/英文 detail）供前端定位与排查
        'details': detail,
    }
    return response
