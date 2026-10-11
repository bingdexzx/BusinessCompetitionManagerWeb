"""脱敏（决策 D18：密码 / token / 邀请码原文一律不入日志，写 [REDACTED]）。"""

import json

from django.conf import settings

REDACTED = '[REDACTED]'


def _is_sensitive_key(key: str) -> bool:
    k = str(key).lower()
    if k in {s.lower() for s in settings.LOG_REDACTED_KEYS}:
        return True
    # 常见敏感词根兜底
    return any(part in k for part in ('password', 'token', 'secret', 'authorization'))


def redact(obj, depth: int = 0):
    """递归脱敏 dict / list / 标量。"""
    if depth > 6:
        return '...'
    if isinstance(obj, dict):
        return {
            k: (REDACTED if _is_sensitive_key(k) else redact(v, depth + 1))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [redact(v, depth + 1) for v in obj[:50]]
    return obj


def digest(raw, max_length=None):
    """把请求/响应体转成脱敏摘要文本（不存完整报文）。

    - JSON 体：脱敏后序列化；
    - 无法解析的文本体：只记录长度占位，避免敏感原文入库。
    """
    max_length = max_length or settings.LOG_DIGEST_MAX_LENGTH
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode('utf-8', errors='replace')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return f'<unparsed text, {len(raw)} chars>'
    try:
        text = json.dumps(redact(raw), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return f'<unserializable {type(raw).__name__}>'
    return text[:max_length]
