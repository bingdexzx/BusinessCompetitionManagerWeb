"""比赛内身份（§6.1 competition_memberships、§15.1 身份模型，决策 D3/D9）。

一个账号可持多个比赛身份（A 在比赛 1 是管理员、在比赛 2 是参赛代表），共用一套用户名密码。
"""

from django.conf import settings
from django.db import models


class CompetitionMembership(models.Model):
    class Identity(models.TextChoices):
        COMP_SUPER_ADMIN = 'COMP_SUPER_ADMIN', '比赛超级管理员'
        ADMIN = 'ADMIN', '管理员（主席团）'
        PLAYER = 'PLAYER', '参赛代表'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='用户',
        on_delete=models.CASCADE, related_name='memberships',
    )
    competition = models.ForeignKey(
        'competitions.Competition', verbose_name='比赛',
        on_delete=models.CASCADE, related_name='memberships',
    )
    identity = models.CharField('比赛内身份', max_length=32, choices=Identity.choices)
    managed_companies = models.JSONField('所辖公司', default=list, blank=True)  # 管理员（主席团）所辖公司
    is_active = models.BooleanField('有效', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '比赛内身份'
        verbose_name_plural = '比赛内身份'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'competition'], name='uniq_user_competition_membership',
            ),
        ]

    def __str__(self):
        return f'{self.user} @ {self.competition} ({self.identity})'
