"""JWT 认证（§12：REST + JWT；tokenVersion 顶号失效，§17 风险对策）。"""

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from apps.common import context as ctx


class GipfelJWTAuthentication(JWTAuthentication):
    """在标准 JWT 认证上追加 tokenVersion 校验，并把用户回填到日志上下文。"""

    def get_validated_token(self, raw_token):
        validated = super().get_validated_token(raw_token)
        return validated

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        token_version = validated_token.get('tv')
        if token_version is not None and int(token_version) != user.token_version:
            raise InvalidToken('令牌已失效（tokenVersion 不匹配）')
        # 网络日志归属当前请求用户（§14.1）
        ctx.set_log_user(user)
        return user
