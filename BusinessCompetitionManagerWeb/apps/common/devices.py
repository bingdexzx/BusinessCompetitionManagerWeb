"""设备信息解析（决策 D19：登录登记设备 UA/系统/浏览器/屏幕/IP；日志内联快照）。"""

import re

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
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
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
