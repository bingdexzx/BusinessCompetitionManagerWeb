"""队伍、组队码与产业志愿（§6.1 teams / team_join_codes、§2.2 阶段三，决策 D3）。

- 两条入口：直接注册账号 / **通过组队码完成组队**；
- **队长选择本队想要的产业和接受调剂的产业**；
- **比赛管理员手动调整每个队伍的产业信息**（``industry_final`` 最终由管理员定夺）；
- 一队一公司：``company_id`` 指向比赛库 companies 行（跨库存整数 ID，不建外键，§5.2）。
"""

from django.conf import settings
from django.db import models


class Team(models.Model):
    competition = models.ForeignKey(
        'competitions.Competition', verbose_name='比赛',
        on_delete=models.CASCADE, related_name='teams',
    )
    name = models.CharField('队伍名称', max_length=120)
    captain = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='队长',
        on_delete=models.CASCADE, related_name='captained_teams',
    )
    industry_choice = models.JSONField('想要的产业', default=list, blank=True)          # ["manufacturer", ...]
    industry_adjust_accepted = models.JSONField('接受调剂的产业', default=list, blank=True)
    industry_final = models.CharField('最终产业（管理员调整后）', max_length=64, blank=True)
    company_id = models.BigIntegerField('公司 ID（比赛库）', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '队伍'
        verbose_name_plural = '队伍'
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['competition', 'name'], name='uniq_team_name'),
        ]

    def __str__(self):
        return f'{self.name} @ {self.competition}'


class TeamMember(models.Model):
    class Role(models.TextChoices):
        CAPTAIN = 'CAPTAIN', '队长'
        MEMBER = 'MEMBER', '队员'

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='用户',
        on_delete=models.CASCADE, related_name='team_memberships',
    )
    role = models.CharField('角色', max_length=16, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField('加入时间', auto_now_add=True)

    class Meta:
        verbose_name = '队伍成员'
        verbose_name_plural = '队伍成员'
        constraints = [
            models.UniqueConstraint(fields=['team', 'user'], name='uniq_team_member'),
        ]


class TeamJoinCode(models.Model):
    """组队码（一次性 / 限次邀请码，§6.1 team_join_codes）。"""

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='join_codes')
    code = models.CharField('组队码', max_length=32, unique=True)
    expires_at = models.DateTimeField('过期时间', null=True, blank=True)
    max_uses = models.PositiveIntegerField('最大使用次数', default=1)
    used_count = models.PositiveIntegerField('已使用次数', default=0)
    created_by = models.BigIntegerField('创建人（全局库用户 ID）', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '组队码'
        verbose_name_plural = '组队码'
        ordering = ['-created_at']

    @property
    def is_valid(self) -> bool:
        from django.utils import timezone
        if self.used_count >= self.max_uses:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True
