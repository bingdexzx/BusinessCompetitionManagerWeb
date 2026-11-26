"""设备实体与网络日志（§14.3 网络日志、§14.4 设备信息、§14.5 存储与留存）。

- 网络日志存**全局库**，**只增不删**（无 UPDATE/DELETE 接口）；
- 日志写入时**内联设备快照**（设备表后续变化不影响历史可追溯性）；
- 所有日志必含**用户（系统级）、设备信息、时间**（§14.1）。
"""

from django.conf import settings
from django.db import models


class Device(models.Model):
    """登录时登记/更新的设备实体（决策 D19）。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='用户',
        on_delete=models.CASCADE, related_name='devices',
    )
    device_key = models.CharField('设备指纹', max_length=64)
    ua = models.TextField('User-Agent', blank=True)
    os = models.CharField('操作系统', max_length=64, blank=True)
    browser = models.CharField('浏览器', max_length=64, blank=True)
    screen = models.CharField('屏幕', max_length=32, blank=True)
    ip = models.GenericIPAddressField('最近 IP', null=True, blank=True)
    first_login_at = models.DateTimeField('首次登录', auto_now_add=True)
    last_login_at = models.DateTimeField('最近登录', auto_now=True)

    class Meta:
        verbose_name = '设备'
        verbose_name_plural = '设备'
        constraints = [
            models.UniqueConstraint(fields=['user', 'device_key'], name='uniq_user_device'),
        ]
        indexes = [models.Index(fields=['user', 'last_login_at'])]

    def __str__(self):
        return f'{self.user} / {self.os} {self.browser}'


class NetworkLog(models.Model):
    """网络日志：记录每一次 API 与 WebSocket 交互（§14.3）。只增不删。"""

    trace_id = models.CharField('请求关联 ID', max_length=64, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='用户', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='network_logs',
    )
    competition_id = models.BigIntegerField('比赛 ID', null=True, blank=True)
    device = models.ForeignKey(
        Device, verbose_name='设备', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='network_logs',
    )
    device_snapshot = models.JSONField('设备快照', default=dict, blank=True)
    method = models.CharField('方法', max_length=8)
    path = models.CharField('路径', max_length=500)
    query = models.TextField('查询串（脱敏）', blank=True)
    status = models.IntegerField('状态码')
    duration_ms = models.IntegerField('耗时(ms)', null=True, blank=True)
    ip = models.GenericIPAddressField('IP', null=True, blank=True)
    payload_digest = models.TextField('请求脱敏摘要', blank=True)
    response_digest = models.TextField('响应脱敏摘要', blank=True)
    occurred_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '网络日志'
        verbose_name_plural = '网络日志'
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['user', 'occurred_at']),
            models.Index(fields=['device', 'occurred_at']),
            models.Index(fields=['competition_id', 'occurred_at']),
            # 默认按时间倒序翻页；没有该索引时每次都要对全表排序
            models.Index(fields=['-occurred_at'], name='logs_networ_occurred_idx'),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError('网络日志只增不删（禁止更新）')
        if not self.device_snapshot and self.device:
            self.device_snapshot = {
                'ua': self.device.ua, 'os': self.device.os,
                'browser': self.device.browser, 'screen': self.device.screen,
                'ip': self.device.ip,
            }
        return super().save(*args, **kwargs)


class BroadcastEvent(models.Model):
    """资源变更广播流水（2026-10 决策：实时广播 resource:changed + 断线 seq 重放）。

    seq=主键（单调递增）：客户端断线后带 lastSeq 请求重放，服务端按 seq 补发遗漏事件；
    payload 只存轻量元数据（id/action 等），**推送当信号**，页面收到后自行增量重拉。
    """

    seq = models.BigAutoField('序列', primary_key=True)
    competition_id = models.BigIntegerField('比赛 ID（全局库整数）', null=True, blank=True)
    resource = models.CharField('资源', max_length=64)   # contracts / basedata / regions / ...
    action = models.CharField('动作', max_length=16)      # created / updated / deleted
    payload = models.JSONField('事件负载', default=dict, blank=True)
    created_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '广播事件'
        verbose_name_plural = '广播事件'
        ordering = ['-seq']
        indexes = [
            models.Index(fields=['competition_id', 'seq']),
        ]

    def delete(self, *args, **kwargs):
        raise ValueError('网络日志只增不删（禁止删除）')
