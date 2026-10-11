"""比赛内审计（§6.2 audit_logs）。M0 建表占位，M6 完整审计流水。"""

from django.db import models


class AuditLog(models.Model):
    action = models.CharField('动作', max_length=100)
    actor_id = models.BigIntegerField('操作者（全局库用户 ID）', null=True, blank=True)
    actor_username = models.CharField('操作者用户名', max_length=150, blank=True)
    target = models.CharField('对象', max_length=200, blank=True)
    payload = models.JSONField('详情', default=dict, blank=True)
    trace_id = models.CharField('请求关联 ID', max_length=64, blank=True, db_index=True)
    occurred_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '比赛内审计'
        verbose_name_plural = '比赛内审计'
        ordering = ['-occurred_at']
        indexes = [models.Index(fields=['actor_id', 'occurred_at'])]
