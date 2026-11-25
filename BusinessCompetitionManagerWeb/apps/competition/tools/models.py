"""工具箱：计时器（比赛域）——按「名称 + 倒计时时长」创建。"""

from datetime import timedelta

from django.db import models
from django.utils import timezone


class CompetitionTimer(models.Model):
    """比赛里的倒计时：名称 + 时长，从创建那一刻开始倒数。"""

    name = models.CharField('名称', max_length=120)
    duration_seconds = models.PositiveIntegerField('倒计时时长（秒）', default=0)
    started_at = models.DateTimeField('开始时间', default=timezone.now)
    note = models.CharField('备注', max_length=255, blank=True, default='')
    created_by = models.BigIntegerField('创建人（全局库用户 ID）', null=True, blank=True)
    created_by_username = models.CharField('创建人用户名', max_length=150, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '计时器'
        verbose_name_plural = '计时器'
        db_table = 'competition_timers'
        ordering = ['started_at', 'id']
        indexes = [
            models.Index(fields=['started_at'], name='idx_comp_timers_started'),
        ]

    def __str__(self):
        return f'{self.name}（{self.duration_seconds}s）'

    @property
    def target_at(self):
        """结束时刻 = 开始时间 + 时长。"""
        return self.started_at + timedelta(seconds=self.duration_seconds)

    def remaining_seconds(self) -> int:
        """剩余秒数（已结束返回 0）。"""
        delta = (self.target_at - timezone.now()).total_seconds()
        return max(0, int(delta))
