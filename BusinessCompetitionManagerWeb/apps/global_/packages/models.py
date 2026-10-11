"""比赛包上传与导入报告（§6.1 packages）。"""

from django.db import models


class Package(models.Model):
    class Status(models.TextChoices):
        SUCCESS = 'SUCCESS', '导入成功'
        FAILED = 'FAILED', '导入失败'

    competition = models.ForeignKey(
        'competitions.Competition', verbose_name='比赛',
        on_delete=models.CASCADE, related_name='packages',
    )
    file_name = models.CharField('文件名', max_length=255)
    file_path = models.CharField('存储路径', max_length=500)
    sha256 = models.CharField('SHA-256', max_length=64, db_index=True)
    status = models.CharField('结果', max_length=8, choices=Status.choices, default=Status.SUCCESS)
    import_report = models.JSONField('导入报告', default=dict, blank=True)
    created_by = models.BigIntegerField('上传人（全局库用户 ID）', null=True, blank=True)
    created_by_username = models.CharField('上传人用户名', max_length=150, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '比赛包'
        verbose_name_plural = '比赛包'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.file_name} [{self.status}]'


class PackagePlugin(models.Model):
    """比赛 ↔ 插件版本 关联（一个比赛暴露哪些合同/产业类型）。"""

    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name='package_plugins')
    plugin = models.ForeignKey('plugins.PluginRegistry', on_delete=models.PROTECT, related_name='package_links')
    kind = models.CharField('类型', max_length=16)
    key = models.CharField('插件键', max_length=64)
    version = models.CharField('版本', max_length=32)

    class Meta:
        verbose_name = '比赛包插件'
        verbose_name_plural = '比赛包插件'
        constraints = [
            models.UniqueConstraint(fields=['package', 'plugin'], name='uniq_package_plugin'),
        ]
