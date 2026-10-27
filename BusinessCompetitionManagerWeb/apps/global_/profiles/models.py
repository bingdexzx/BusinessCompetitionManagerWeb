"""个人档案、获奖记录与电子奖牌（§6.1 award_records / medal_assets、§11、决策 D12）。

- 结算完成后**比赛信息、获奖信息同步到个人信息**（award_records）；
- **电子奖牌仅在线展示**（个人档案内查看获奖记录与奖牌样式，不提供下载文件）。
"""

from django.conf import settings
from django.db import models


class MedalAsset(models.Model):
    """电子奖牌展示资产（仅在线展示）。"""

    award_level = models.CharField('获奖等级', max_length=32, unique=True)  # 一等奖/二等奖/三等奖...
    display_name = models.CharField('奖牌名称', max_length=100, blank=True)
    display_asset = models.TextField('奖牌样式（SVG/URL/样式描述）', blank=True)
    meta = models.JSONField('元数据', default=dict, blank=True)

    class Meta:
        verbose_name = '电子奖牌'
        verbose_name_plural = '电子奖牌'
        ordering = ['id']

    def __str__(self):
        return self.display_name or self.award_level


class AwardRecord(models.Model):
    """比赛信息、获奖信息同步到个人信息（个人档案可查看记录与电子奖牌）。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='用户',
        on_delete=models.CASCADE, related_name='award_records',
    )
    competition_id = models.BigIntegerField('比赛 ID（全局库）')
    competition_name = models.CharField('比赛名称', max_length=200, blank=True)
    team_name = models.CharField('队伍/公司', max_length=200, blank=True)
    # 奖项（人工发放）：名称 + 类型；grant_id = 比赛库 AwardGrant.id（撤销时按它定位）
    award_name = models.CharField('奖项名称', max_length=100, blank=True)
    award_kind = models.CharField('奖项类型（INDIVIDUAL/COLLECTIVE）', max_length=16, blank=True)
    grant_id = models.BigIntegerField('发放记录 ID（比赛库）', null=True, blank=True)
    rank = models.PositiveIntegerField('名次', null=True, blank=True)
    award_level = models.CharField('获奖等级', max_length=32, blank=True)
    score = models.FloatField('得分', null=True, blank=True)
    medal = models.ForeignKey(
        MedalAsset, verbose_name='电子奖牌', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='award_records',
    )
    detail = models.JSONField('详情（各财年财务报表摘要等）', default=dict, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '获奖记录'
        verbose_name_plural = '获奖记录'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'competition_id'])]
        constraints = [
            # 同一人可获多个奖（个人奖 + 集体奖 + 多个奖项）：唯一性按「一次发放」约束。
            # grant_id 为空的历史记录不参与唯一性（Postgres 视 NULL 互不相等）。
            models.UniqueConstraint(
                fields=['user', 'competition_id', 'grant_id'], name='uniq_user_comp_grant'),
        ]
