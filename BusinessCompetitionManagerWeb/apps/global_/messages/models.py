"""系统级站内信（独立于比赛，全局库）。

- **站内信**：用户互发（个人自由），支持一次多个收件人；
- **公告**：按比赛批量发送（选中比赛 → 该比赛全体成员），仅超管可发（需求方口径）；
- **系统通知**：合同确认提醒/审核提醒等自动通知统一进同一收件箱，kind=SYSTEM + 来源链接。

设计：一信多收件人（Message + MessageRecipient），阅读状态按收件人独立记录。
"""

from django.conf import settings
from django.db import models


class Message(models.Model):
    class Kind(models.TextChoices):
        PERSONAL = 'PERSONAL', '站内信'
        ANNOUNCE = 'ANNOUNCE', '公告'
        SYSTEM = 'SYSTEM', '系统通知'

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='发送人', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='sent_inmails',
    )
    sender_name = models.CharField('发送人显示名', max_length=150, blank=True)
    kind = models.CharField('类型', max_length=16, choices=Kind.choices, default=Kind.PERSONAL)
    title = models.CharField('标题', max_length=200)
    body = models.TextField('内容', blank=True)
    payload = models.JSONField(
        '附加数据（来源链接等）', default=dict, blank=True,
        # {"competitionId": 1, "contractId": 3, "link": "/competitions/1/contracts/3"}
    )
    competition_id = models.BigIntegerField('相关比赛 ID（可空）', null=True, blank=True)
    created_at = models.DateTimeField('发送时间', auto_now_add=True)

    class Meta:
        verbose_name = '站内信'
        verbose_name_plural = '站内信'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['kind', 'created_at'])]

    def __str__(self):
        return f'{self.kind}:{self.title}'


class MessageRecipient(models.Model):
    """收件人（一信多收件人；阅读状态独立）。"""

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='recipients')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='收件人',
        on_delete=models.CASCADE, related_name='inmails',
    )
    read_at = models.DateTimeField('阅读时间', null=True, blank=True)

    class Meta:
        verbose_name = '站内信收件人'
        verbose_name_plural = '站内信收件人'
        constraints = [
            models.UniqueConstraint(fields=['message', 'user'], name='uniq_inmail_recipient'),
        ]
        indexes = [models.Index(fields=['user', 'read_at'])]
