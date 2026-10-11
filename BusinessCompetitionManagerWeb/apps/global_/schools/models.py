"""学校实体（§6.1 schools：一个账号对应一个学校；注册完成后选择自己的学校）。"""

from django.db import models


class School(models.Model):
    name = models.CharField('学校名称', max_length=120, unique=True)
    region = models.CharField('地区', max_length=120, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '学校'
        verbose_name_plural = '学校'
        ordering = ['name']

    def __str__(self):
        return self.name
