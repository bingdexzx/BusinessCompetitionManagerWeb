"""流量限制配置与请求计数（全局库）。

- ``RateLimitConfig``：全局单例（id=1）的 JSON 配置——登录限流 + API 每分钟限流；
- ``RequestThrottle``：API 请求按**分钟窗口**计数（多进程 worker 共享，进程内计数
  会被 worker 数摊薄，故计数落库）；键形如 ``api:<userId|ip>:<role>``。
"""

from django.db import models


class RateLimitConfig(models.Model):
    """流量限制配置（全局单例 id=1）。

    config 结构::

        {
          "login": {"failLimit": 10, "windowSeconds": 300, "lockSeconds": 900},
          "api": {"enabled": true,
                  "perMinute": {"superuser": 600, "compSuperAdmin": 300,
                                "admin": 200, "player": 120, "anonymous": 120}}
        }

    ``anonymous`` 按**客户端 IP** 计数：同一台机器的多个标签页、或同一 NAT 出口
    （学校机房 / 办公室）共享该额度，因此不能设得过低。
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
        """整体保存配置（单例 upsert），返回保存后的配置。"""
        row, _created = cls.objects.update_or_create(pk=1, defaults={'config': config})
        return row.config


class RequestThrottle(models.Model):
    """API 请求限流计数（按分钟窗口）。

    键 = ``api:<userId|ip>:<role>``（登录用户用 userId、匿名用客户端 IP，
    role ∈ superuser/compSuperAdmin/admin/player/anonymous）；
    ``locked_until`` 非空且未到期表示窗口内超限被锁（等窗口结束自动恢复）。
    """

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
