"""激活码（§6.1 invite_codes、§2.2 阶段四「通过激活码加入比赛」）。

用户凭激活码加入对应比赛并**获得比赛内身份**（超级管理员 / 管理员(主席团) / 参赛代表）。
"""

from django.conf import settings
from django.db import models


class InviteCode(models.Model):
    competition = models.ForeignKey(
        'competitions.Competition', verbose_name='比赛',
        on_delete=models.CASCADE, related_name='invite_codes',
    )
    code = models.CharField('激活码', max_length=32, unique=True)
    identity = models.CharField('授予身份', max_length=32)  # CompetitionMembership.Identity
    expires_at = models.DateTimeField('过期时间', null=True, blank=True)
    max_uses = models.PositiveIntegerField('最大使用次数', default=1)
    used_count = models.PositiveIntegerField('已使用次数', default=0)
    note = models.CharField('备注', max_length=200, blank=True)
    created_by = models.BigIntegerField('创建人（全局库用户 ID）', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '激活码'
        verbose_name_plural = '激活码'
        ordering = ['-created_at']

    @property
    def is_valid(self) -> bool:
        from django.utils import timezone
        if self.used_count >= self.max_uses:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True


class InviteRedemption(models.Model):
    """激活码使用记录（审计：谁在什么时候加入比赛）。"""

    invite = models.ForeignKey(InviteCode, on_delete=models.CASCADE, related_name='redemptions')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='用户',
        on_delete=models.CASCADE, related_name='invite_redemptions',
    )
    redeemed_at = models.DateTimeField('使用时间', auto_now_add=True)

    class Meta:
        verbose_name = '激活码使用记录'
        verbose_name_plural = '激活码使用记录'
        constraints = [
            models.UniqueConstraint(fields=['invite', 'user'], name='uniq_invite_user'),
        ]
