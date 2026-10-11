"""比赛元数据与生命周期（§6.1 competitions、§10.1 比赛状态机）。

比赛详情页承载信息（§2.2 阶段一）：展示图片、名称、办赛学校、比赛地点、人员安排。
"""

from django.conf import settings
from django.db import models


class Competition(models.Model):
    class Status(models.TextChoices):
        CREATED = 'CREATED', '已创建'
        PACKAGE_IMPORTED = 'PACKAGE_IMPORTED', '已导入比赛包'
        ENROLLING = 'ENROLLING', '报名中'
        RUNNING = 'RUNNING', '进行中'
        SETTLING = 'SETTLING', '结算中'
        CLOSED = 'CLOSED', '已结束'

    # §10.1 生命周期转移表
    TRANSITIONS = {
        Status.CREATED: {Status.PACKAGE_IMPORTED},
        Status.PACKAGE_IMPORTED: {Status.ENROLLING},
        Status.ENROLLING: {Status.RUNNING},
        Status.RUNNING: {Status.SETTLING},
        Status.SETTLING: {Status.CLOSED},
    }

    name = models.CharField('比赛名称', max_length=120)
    code = models.CharField(
        '比赛代码（统一编号用，D13）', max_length=32, unique=True, blank=True,
    )
    cover_image = models.TextField('展示图片', blank=True)
    host_school = models.ForeignKey(
        'schools.School', verbose_name='办赛学校', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='hosted_competitions',
    )
    location = models.CharField('比赛地点', max_length=200, blank=True)
    staffing_info = models.TextField('人员安排信息', blank=True)
    status = models.CharField('状态', max_length=32, choices=Status.choices, default=Status.CREATED)
    db_name = models.CharField('比赛库名', max_length=64, unique=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='创建人', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='created_competitions',
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '比赛'
        verbose_name_plural = '比赛'
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def can_transition_to(self, target) -> bool:
        return target in self.TRANSITIONS.get(self.Status(self.status), set())

    def transition_to(self, target):
        """推进生命周期；非法转移抛 ValueError。"""
        if target not in self.Status.values:
            raise ValueError(f'未知状态：{target}')
        if not self.can_transition_to(target):
            raise ValueError(f'不允许从 {self.status} 转移到 {target}')
        self.status = target
        self.save(update_fields=['status', 'updated_at'])
