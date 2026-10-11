"""字段日志（§14.2 field_logs，比赛库，只增不删，随比赛归档）。

记录两类事件（决策 D17）：
1. 值变更（VALUE_CHANGE）——含变更前后值、来源动作、操作者；
2. 结构变更（SCHEMA_CHANGE）——产业字段定义/结构变更（插件迁移）。

所有日志必含**用户（系统级）、设备信息、时间**（§14.1）；与
contract_field_effects 按 traceId 互链（合同视角 ↔ 字段视角）。
"""

from django.db import models


class FieldLog(models.Model):
    class Event(models.TextChoices):
        VALUE_CHANGE = 'VALUE_CHANGE', '值变更'
        SCHEMA_CHANGE = 'SCHEMA_CHANGE', '结构变更'

    class Source(models.TextChoices):
        CONTRACT_POST = 'CONTRACT_POST', '合同落账'
        CONTRACT_ROLLBACK = 'CONTRACT_ROLLBACK', '合同回滚'
        CONTRACT_REPOST = 'CONTRACT_REPOST', '合同重落账'
        BACKFILL_SYNC = 'BACKFILL_SYNC', '补录同步'
        FY_TIMER = 'FY_TIMER', '财年定时器'
        CALC = 'CALC', '公式重算'
        MANUAL = 'MANUAL', '手工修改'
        SCHEMA_MIGRATE = 'SCHEMA_MIGRATE', '结构迁移'

    company = models.ForeignKey(
        'companies.Company', on_delete=models.PROTECT, null=True, blank=True,
        related_name='field_logs',
    )  # 结构变更（SCHEMA_CHANGE）可不指向单个公司
    field_key = models.CharField('字段键', max_length=64)
    data_table = models.CharField('数据表归属', max_length=16, blank=True)  # ENTITY / FINANCE
    event = models.CharField('事件类型', max_length=16, choices=Event.choices)
    op = models.CharField('操作', max_length=16, blank=True)  # ADD / SUB / SET / MIGRATE ...
    before_raw = models.JSONField('变更前值', null=True, blank=True)
    after_raw = models.JSONField('变更后值', null=True, blank=True)
    source = models.CharField('来源动作', max_length=32, choices=Source.choices)
    contract = models.ForeignKey(
        'contracts.Contract', on_delete=models.SET_NULL, null=True, blank=True, related_name='field_logs',
    )
    round_no = models.PositiveIntegerField('轮次', default=0)
    operator_id = models.BigIntegerField('操作者（全局库用户 ID）', null=True, blank=True)
    operator_username = models.CharField('操作者用户名', max_length=150, blank=True)
    device_snapshot = models.JSONField('设备快照', default=dict, blank=True)
    ip = models.GenericIPAddressField('IP', null=True, blank=True)
    trace_id = models.CharField('请求关联 ID', max_length=64, blank=True, db_index=True)
    occurred_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '字段日志'
        verbose_name_plural = '字段日志'
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['company', 'field_key', 'occurred_at']),
            models.Index(fields=['contract']),
            models.Index(fields=['operator_id', 'occurred_at']),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError('字段日志只增不删（禁止更新）')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('字段日志只增不删（禁止删除）')
