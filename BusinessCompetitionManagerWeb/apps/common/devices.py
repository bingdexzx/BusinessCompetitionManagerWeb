"""设备信息解析（决策 D19：登录登记设备 UA/系统/浏览器/屏幕/IP；日志内联快照）。"""

import re

from django.conf import settings

UA_RULES = [
    # (正则, 系统, 浏览器) —— 顺序敏感，先特异后一般
    (r'Windows NT 10', 'Windows 10/11', None),
    (r'Windows NT 6\.3', 'Windows 8.1', None),
    (r'Windows NT 6\.1', 'Windows 7', None),
    (r'Windows', 'Windows', None),
    (r'Mac OS X', 'macOS', None),
    (r'Android', 'Android', None),
    (r'iPhone|iPad|iOS', 'iOS', None),
    (r'Linux', 'Linux', None),
]

BROWSER_RULES = [
    (r'Edg(?:e|A|iOS)?/', 'Edge'),
    (r'OPR/|Opera', 'Opera'),
    (r'Firefox/', 'Firefox'),
    (r'Chrome/', 'Chrome'),
    (r'Safari/', 'Safari'),
    (r'curl/', 'curl'),
    (r'python-requests', 'python-requests'),
]


def parse_user_agent(ua: str) -> dict:
    ua = ua or ''
    os_name = 'Unknown'
    for pattern, name, _ in UA_RULES:
        if re.search(pattern, ua):
            os_name = name
            break
    browser = 'Unknown'
    for pattern, name in BROWSER_RULES:
        if re.search(pattern, ua):
            browser = name
            break
    return {'os': os_name, 'browser': browser}


def client_ip(request) -> str:
    """返回客户端 IP。

    ``X-Forwarded-For`` 头可被客户端任意伪造，直接信任会让登录限流、审计日志按
    伪造 IP 计数。因此**仅当** ``settings.TRUST_X_FORWARDED_FOR`` 为 True（即部署在
    受信任的反向代理之后）时才使用它，否则一律回退 ``REMOTE_ADDR``。

    信任时取**最后一个**条目：XFF 的每一跳代理都会把自己看到的上游地址追加到
    末尾，因此最后一个条目是「离本应用最近」的一跳，最接近真实客户端，且不受
    客户端控制的中间地址污染。
    """
    if getattr(settings, 'TRUST_X_FORWARDED_FOR', False):
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded:
            parts = [p.strip() for p in forwarded.split(',') if p.strip()]
            if parts:
                return parts[-1]
    return request.META.get('REMOTE_ADDR') or ''


def device_snapshot(request) -> dict:
    """由请求构建设备快照（写日志时内联冗余，§14.4）。"""
    ua = request.META.get('HTTP_USER_AGENT', '')
    parsed = parse_user_agent(ua)
    return {
        'ua': ua[:500],
        'os': parsed['os'],
        'browser': parsed['browser'],
        'screen': request.META.get('HTTP_X_DEVICE_SCREEN', ''),
        'ip': client_ip(request),
    }
