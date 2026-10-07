from django.db import models

# 在此处创建你的模型。


class Competition(models.Model):
    """比赛信息模型"""

    name = models.CharField('比赛名称', max_length=100)
    description = models.TextField('比赛简介', blank=True)
    start_date = models.DateField('开始日期', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    def __str__(self):
        return self.name
