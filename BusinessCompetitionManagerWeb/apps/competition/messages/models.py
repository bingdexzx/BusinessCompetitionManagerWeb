"""比赛内消息（§6.2 messages）。M0 建表占位，M6 完整实现消息中心与实时通知。"""

from django.db import models


class Message(models.Model):
    to_user_id = models.BigIntegerField('接收人（全局库用户 ID）')
    kind = models.CharField('消息类型', max_length=64, blank=True)  # 合同确认提醒 / 修改申请审核 ...
    title = models.CharField('标题', max_length=200, blank=True)
    body = models.TextField('内容', blank=True)
    payload = models.JSONField('附加数据', default=dict, blank=True)
    read_at = models.DateTimeField('阅读时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '比赛内消息'
        verbose_name_plural = '比赛内消息'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['to_user_id', 'created_at'])]
