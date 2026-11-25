"""后台任务（2026-11）：不依赖 Redis/Celery 的轻量队列，落全局库，由 run_jobs 命令消费。

用途：把「结算执行」「财年开启/结束（含定时器重算）」这类重活从请求线程挪到后台，
接口只负责入队，前端轮询进度。
"""

from django.db import models


class BackgroundJob(models.Model):
    class Kind(models.TextChoices):
        SETTLEMENT = 'SETTLEMENT', '执行结算'
        FISCAL_OPEN = 'FISCAL_OPEN', '开启财年（含定时器）'
        FISCAL_CLOSE = 'FISCAL_CLOSE', '结束财年（含备份）'
        PACKAGE_IMPORT = 'PACKAGE_IMPORT', '导入比赛包'

    class Status(models.TextChoices):
        PENDING = 'PENDING', '待执行'
        RUNNING = 'RUNNING', '执行中'
        SUCCESS = 'SUCCESS', '已完成'
        FAILED = 'FAILED', '失败'

    kind = models.CharField('任务类型', max_length=32, choices=Kind.choices)
    competition_id = models.BigIntegerField('比赛 ID')
    status = models.CharField('状态', max_length=16, choices=Status.choices,
                              default=Status.PENDING)
    progress = models.PositiveSmallIntegerField('进度（0-100）', default=0)
    message = models.CharField('当前步骤', max_length=200, blank=True)
    payload = models.JSONField('参数', default=dict, blank=True)
    result = models.JSONField('结果摘要', default=dict, blank=True)
    error = models.TextField('错误信息', blank=True)
    created_by = models.BigIntegerField('创建人（全局库用户 ID）', null=True, blank=True)
    created_by_username = models.CharField('创建人用户名', max_length=150, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    started_at = models.DateTimeField('开始时间', null=True, blank=True)
    finished_at = models.DateTimeField('结束时间', null=True, blank=True)

    class Meta:
        verbose_name = '后台任务'
        verbose_name_plural = '后台任务'
        ordering = ['-id']
        indexes = [
            models.Index(fields=['status', 'id'], name='idx_job_status_id'),
            models.Index(fields=['competition_id', 'kind'], name='idx_job_comp_kind'),
        ]

    def __str__(self):
        return f'{self.kind}#{self.pk} [{self.status}]'

    @property
    def is_active(self) -> bool:
        return self.status in (self.Status.PENDING, self.Status.RUNNING)
