"""比赛内身份（§6.1 competition_memberships、§15.1 身份模型，决策 D3/D9）。

一个账号可持多个比赛身份（A 在比赛 1 是管理员、在比赛 2 是参赛代表），共用一套用户名密码。
2026-11 决策：取消「比赛超级管理员」身份，其权限并入**超级管理员**；
保留「管理员（主席团）」，按所辖公司管理。
"""

from django.conf import settings
from django.db import models, transaction


class CompetitionMembership(models.Model):
    class Identity(models.TextChoices):
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
    # 纪念券票号：比赛内自增，从 1 开始（展示时补足 5 位）
    ticket_no = models.PositiveIntegerField('纪念券票号', null=True, blank=True)
    # 纪念票快照（左侧票面）：加入比赛时定格，比赛改名/换票图不影响已发出的票
    ticket_snapshot = models.JSONField('纪念票快照', default=dict, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '比赛内身份'
        verbose_name_plural = '比赛内身份'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'competition'], name='uniq_user_competition_membership',
            ),
            models.UniqueConstraint(
                fields=['competition', 'ticket_no'],
                name='uniq_membership_competition_ticket_no',
            ),
        ]

    def capture_ticket(self, *, user_name: str = '') -> dict:
        """生成并保存纪念票快照（左侧票面），返回快照内容。"""
        from django.utils import timezone

        competition = self.competition
        snapshot = {
            'competitionId': self.competition_id,
            'competitionName': competition.name,
            'ticketNo': self.ticket_no,
            'ticketImage': competition.ticket_image,
            'identity': self.identity,
            'identityLabel': self.get_identity_display(),
            'userName': user_name,
            'joinedAt': (self.created_at or timezone.now()).isoformat(),
        }
        self.ticket_snapshot = snapshot
        self.save(update_fields=['ticket_snapshot'])
        return snapshot

    def save(self, *args, **kwargs):
        # 没票号就现取：锁住比赛行后取当前最大值 +1，保证同一比赛内不重复
        if self.ticket_no is None and self.competition_id:
            alias = self._state.db or 'default'
            with transaction.atomic(using=alias):
                competition_model = self._meta.get_field('competition').remote_field.model
                competition_model.objects.using(alias).select_for_update().filter(
                    pk=self.competition_id,
                ).first()
                current = type(self).objects.using(alias).filter(
                    competition_id=self.competition_id,
                ).aggregate(models.Max('ticket_no'))['ticket_no__max'] or 0
                self.ticket_no = current + 1
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.user} @ {self.competition} ({self.identity})'
