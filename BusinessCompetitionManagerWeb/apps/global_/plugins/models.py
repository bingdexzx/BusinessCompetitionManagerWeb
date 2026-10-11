"""Python 插件注册表（§6.1 plugin_registry、§5.4 版本化与审计）。

不可变版本：kind + key + version + sha256 唯一；文件内容落盘 media/plugins/ 留存。
"""

from django.conf import settings
from django.db import models


class PluginRegistry(models.Model):
    class Kind(models.TextChoices):
        CONTRACT = 'CONTRACT', '合同类型'
        INDUSTRY = 'INDUSTRY', '产业类型'

    kind = models.CharField('类型', max_length=16, choices=Kind.choices)
    key = models.CharField('插件键', max_length=64)
    name = models.CharField('名称', max_length=120)
    version = models.CharField('版本', max_length=32)
    sha256 = models.CharField('SHA-256', max_length=64, db_index=True)
    file_name = models.CharField('文件名', max_length=200)
    file_path = models.CharField('存储路径', max_length=500)
    number_prefix = models.CharField('合同类别前缀（D13）', max_length=8, blank=True)
    uploaded_by = models.BigIntegerField('上传人（全局库用户 ID）', null=True, blank=True)
    uploaded_by_username = models.CharField('上传人用户名', max_length=150, blank=True)
    audit_trail = models.JSONField('审计轨迹', default=list, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '插件'
        verbose_name_plural = '插件'
        constraints = [
            models.UniqueConstraint(
                fields=['kind', 'key', 'version', 'sha256'],
                name='uniq_plugin_version',
            ),
        ]
        ordering = ['kind', 'key', '-created_at']

    def __str__(self):
        return f'{self.kind}:{self.key}@{self.version}'

    def record_audit(self, event: str, actor: str = '', detail: dict = None):
        """只增审计轨迹（§5.4 护栏 5：每次调用记录）。"""
        self.audit_trail = [*self.audit_trail, {
            'event': event, 'actor': actor, 'detail': detail or {},
        }]
        self.save(update_fields=['audit_trail'])
