"""统一业务错误响应：{code, message, details}。"""

from rest_framework.views import exception_handler


def gipfel_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None
    detail = response.data.get('detail') if isinstance(response.data, dict) else response.data
    response.data = {
        'code': response.status_code,
        'message': detail if isinstance(detail, str) else '请求失败',
        'details': response.data if not isinstance(detail, str) else detail,
    }
    return response
