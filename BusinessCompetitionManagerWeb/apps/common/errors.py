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


def gipfel_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None
    detail = response.data.get('detail') if isinstance(response.data, dict) else response.data
    response.data = {
        'code': response.status_code,
        'message': _chinese_message(exc, response.status_code),
        # details 保留原始信息（校验字段级错误/英文 detail）供前端定位与排查
        'details': detail if not isinstance(detail, str) else detail,
    }
    return response
