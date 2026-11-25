"""公司（§6.2 companies）：队伍映射出的参赛主体。比赛库模型。

注意：跨库引用（teamId / 用户）一律存全局库的整数 ID，不建外键（多库架构 §5.2）。
"""

from django.db import models


class Company(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', '参赛中'
        WITHDRAWN = 'WITHDRAWN', '退赛'
        ARCHIVED = 'ARCHIVED', '归档'

    name = models.CharField('公司名称', max_length=120)
    industry_key = models.CharField('产业类型', max_length=64, blank=True)  # 来自产业插件
    team_id = models.BigIntegerField('队伍 ID（全局库）', null=True, blank=True)
    region = models.ForeignKey(
        'regions.Region', verbose_name='区域', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='companies')
    status = models.CharField('状态', max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '公司'
        verbose_name_plural = '公司'
        ordering = ['id']

    def __str__(self):
        return self.name
