"""落账与冻结（§6.2 contract_freezes、§7.4 冻结）。

冻结为**字段级**（决策 D10）：仅锁合同效果触及的（公司, 字段），其余字段照常可改；
修改申请经超管通过 → 解冻 → 重新落账后再冻结。
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
