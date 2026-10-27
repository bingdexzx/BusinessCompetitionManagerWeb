"""流量限制配置与请求计数（全局库）。

``RateLimitConfig``：全局单例（id=1）JSON 配置。``RequestThrottle``：API 请求按分钟窗口计数
——必须落库，进程内计数会被 worker 数摊薄；键 ``api:<userId|ip>:<role>``。"""

from django.db import models


class RateLimitConfig(models.Model):
    """流量限制配置（全局单例 id=1）。

    config 形如 {"login": {...}, "api": {"enabled": true, "perMinute": {role: 次数}}}；
    ``anonymous`` 按**客户端 IP** 计数：同机多标签页 / 同一 NAT 出口共享额度，不能设得过低。
    """

    config = models.JSONField('配置')
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '流量限制配置'
        verbose_name_plural = '流量限制配置'

    def save(self, *args, **kwargs):
        self.pk = 1  # 单例：永远只有 id=1 一行
        return super().save(*args, **kwargs)

    def __str__(self):
        return 'RateLimitConfig#1'

    @classmethod
    def load(cls):
        """返回已保存的配置 dict；从未保存过返回 None（调用方决定回退策略）。"""
        row = cls.objects.filter(pk=1).first()
        return row.config if row is not None else None

    @classmethod
    def save_config(cls, config):
        row, _created = cls.objects.update_or_create(pk=1, defaults={'config': config})
        return row.config


class RequestThrottle(models.Model):
    """API 请求限流计数（按分钟窗口），键 ``api:<userId|ip>:<role>``。

    ``locked_until`` 非空且未到期 = 窗口内超限被锁。"""

    key = models.CharField('限流键（api:用户|IP:角色）', max_length=220, unique=True)
    window_start = models.DateTimeField('窗口起点')
    count = models.PositiveIntegerField('窗口内请求数', default=0)
    locked_until = models.DateTimeField('锁定至', null=True, blank=True)
    updated_at = models.DateTimeField('最近更新', auto_now=True)

    class Meta:
        verbose_name = '请求限流计数'
        verbose_name_plural = '请求限流计数'

    def __str__(self):
        return self.key
