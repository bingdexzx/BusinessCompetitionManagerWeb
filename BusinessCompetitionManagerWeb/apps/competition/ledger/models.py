"""落账与冻结（§6.2 contract_freezes、§7.4 冻结）。

冻结口径（2026-11 调整）：**仅在合同处于修改流程（申请中/修改中）时冻结**，
且冻结的是参与方公司的**全部资源**（``field_key='*'`` 哨兵）——修改完成或驳回后解冻；
平时落账不再冻结字段，手工修改不受影响。
"""

from django.db import models


class ContractFreeze(models.Model):
    contract = models.ForeignKey('contracts.Contract', on_delete=models.CASCADE, related_name='freezes')
    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT, related_name='freezes')
    field_key = models.CharField('字段键', max_length=64)
    frozen_at = models.DateTimeField('冻结时间', auto_now_add=True)
    unfrozen_at = models.DateTimeField('解冻时间', null=True, blank=True)
    reason = models.CharField('原因', max_length=200, blank=True)

    class Meta:
        verbose_name = '合同冻结'
        verbose_name_plural = '合同冻结'
        indexes = [models.Index(fields=['company', 'field_key', 'unfrozen_at'])]

    @property
    def is_active(self):
        return self.unfrozen_at is None
