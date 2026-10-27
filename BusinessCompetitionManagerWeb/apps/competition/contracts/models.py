"""合同与状态机（§3 合同状态机、§6.2 contracts 系列表）。比赛库模型。

状态（§3.2）：DRAFT → PENDING_PARTY_1..N → PENDING_EXEC → EXECUTED → POSTED
修改环：POSTED → MOD_APPLYING → MOD_EDITING → PENDING_EXEC（回滚旧落账后重新执行）
补录：BACKFILL_REVIEW（超管审核，§3.4）→ DRAFT 确认链
执行失败：EXEC_FAILED（§7.5，不落半账）

业务引擎（M3/M4）在 plugins_runtime + ledger 中实现；本模块先落数据模型。
"""

from django.contrib.postgres.indexes import GinIndex
from django.db import models


class Contract(models.Model):
    class Status(models.TextChoices):
        BACKFILL_REVIEW = 'BACKFILL_REVIEW', '补录审核中'
        DRAFT = 'DRAFT', '草稿'
        PENDING_PARTY = 'PENDING_PARTY', '待参与方确认'
        PENDING_EXEC = 'PENDING_EXEC', '待执行'
        EXECUTED = 'EXECUTED', '已执行'
        POSTED = 'POSTED', '已落账'
        MOD_APPLYING = 'MOD_APPLYING', '修改申请中'
        MOD_EDITING = 'MOD_EDITING', '修改中'
        EXEC_FAILED = 'EXEC_FAILED', '执行失败'
        CANCELLED = 'CANCELLED', '已取消'

    contract_type_key = models.CharField('合同类型', max_length=64)
    plugin_version = models.CharField('插件版本', max_length=32, blank=True)
    name = models.CharField('合同名称', max_length=200, blank=True)
    status = models.CharField('状态', max_length=32, choices=Status.choices, default=Status.DRAFT)
    pending_party_index = models.PositiveSmallIntegerField('当前待确认参与方序号', default=0)
    parties = models.JSONField(
        '参与方', default=list, blank=True,
        # [{"role": "buyer", "companyId": 1, "confirmOrder": 0, "confirmAt": null}, ...]
    )
    inputs = models.JSONField('合同输入', default=dict, blank=True)
    unified_number = models.CharField('统一编号', max_length=64, blank=True)  # 类别前缀-比赛代码-财年-流水号（D13）
    numbered_at = models.DateTimeField('编号时间', null=True, blank=True)
    executed_at = models.DateTimeField('执行时间', null=True, blank=True)
    posted_at = models.DateTimeField('落账时间', null=True, blank=True)
    round_no = models.PositiveIntegerField('落账轮次', default=0)  # 修改一次 +1（§7.2）
    is_backfill = models.BooleanField('补录合同', default=False)  # 决策 D14
    # 比赛包重导入去重：同一条合同（类型+名称+参与方+输入）的指纹，已存在则跳过
    import_fingerprint = models.CharField(
        '导入指纹（重导入去重）', max_length=64, blank=True, db_index=True,
    )
    fiscal_year = models.ForeignKey(
        'fiscal.FiscalYear', verbose_name='所属财年', null=True, blank=True,
        on_delete=models.PROTECT, related_name='contracts',
    )
    created_by = models.BigIntegerField('创建人（全局库用户 ID）')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    deleted_at = models.DateTimeField('删除时间', null=True, blank=True)

    class Meta:
        verbose_name = '合同'
        verbose_name_plural = '合同'
        ordering = ['-created_at']
        indexes = [
            # 增量同步（按 updated_at 拉取变更）+ 状态列表组合查询
            models.Index(fields=['updated_at'], name='idx_contract_updated_at'),
            models.Index(fields=['status', 'updated_at'], name='idx_contract_status_updated'),
            # 可见性过滤（JSONB containment：parties @> [{"companyId": N}]），2000+ 合同必备
            GinIndex(fields=['parties'], name='idx_contract_parties_gin',
                     opclasses=['jsonb_path_ops']),
        ]

    def __str__(self):
        return f'{self.unified_number or self.contract_type_key} [{self.status}]'


class ContractConfirmation(models.Model):
    """逐方确认链记录（§6.2 contract_confirmations）：**谁在什么时候点击了确认**。"""

    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='confirmations')
    party_role = models.CharField('参与方角色', max_length=64)
    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT, null=True, blank=True)
    confirmed_by = models.BigIntegerField('确认人（全局库用户 ID）')
    confirmed_by_username = models.CharField('确认人用户名', max_length=150, blank=True)
    confirmed_at = models.DateTimeField('确认时间')
    device_snapshot = models.JSONField('设备快照', default=dict, blank=True)
    ip = models.GenericIPAddressField('IP', null=True, blank=True)
    trace_id = models.CharField('请求关联 ID', max_length=64, blank=True)

    class Meta:
        verbose_name = '合同确认'
        verbose_name_plural = '合同确认'
        ordering = ['confirmed_at']


class ContractModRequest(models.Model):
    """修改流程（§6.2 contract_mod_requests、状态机 T6–T9）。"""

    class Status(models.TextChoices):
        APPLYING = 'APPLYING', '申请中'
        EDITING = 'EDITING', '修改中'
        APPROVED = 'APPROVED', '已完成'
        REJECTED = 'REJECTED', '已驳回'

    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='mod_requests')
    requested_by = models.BigIntegerField('申请人（任意一方，全局库用户 ID）')
    requested_by_username = models.CharField('申请人用户名', max_length=150, blank=True)
    reason = models.TextField('申请理由')  # 必填（T6 守卫）
    status = models.CharField('状态', max_length=16, choices=Status.choices, default=Status.APPLYING)
    reviewed_by = models.BigIntegerField('审核人（超管，全局库用户 ID）', null=True, blank=True)
    review_note = models.TextField('审核意见', blank=True)
    other_party_approvals = models.JSONField(
        '其他方确认', default=list, blank=True,
        # [{"userId": 1, "username": "x", "approved": true, "at": "...", "note": ""}, ...]
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '合同修改申请'
        verbose_name_plural = '合同修改申请'
        ordering = ['-created_at']


class ContractFieldEffect(models.Model):
    """不可变落账审计（§7.2）：回滚 = 逆序重放；修改合同时 roundNo+1 开新一轮。"""

    class Op(models.TextChoices):
        ADD = 'ADD', '增加'
        SUB = 'SUB', '减少'
        SET = 'SET', '设置'

    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='effects')
    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT, related_name='field_effects')
    field_key = models.CharField('字段键', max_length=64)
    op = models.CharField('操作', max_length=8, choices=Op.choices)
    value_raw = models.JSONField('效果值', null=True, blank=True)
    before_raw = models.JSONField('变更前值', null=True, blank=True)
    after_raw = models.JSONField('变更后值', null=True, blank=True)
    round_no = models.PositiveIntegerField('轮次', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '合同字段效果'
        verbose_name_plural = '合同字段效果'
        ordering = ['round_no', 'created_at']
        indexes = [models.Index(fields=['contract', 'round_no'])]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError('合同字段效果不可变（禁止更新）')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('合同字段效果不可变（禁止删除）')


class NumberSequence(models.Model):
    """统一编号流水（D13：类别前缀-比赛代码-财年-流水号，按 比赛+财年+类型 分段）。"""

    key = models.CharField('序列键（前缀-比赛代码-财年）', max_length=64, unique=True)
    last_value = models.PositiveIntegerField('当前流水', default=0)

    class Meta:
        verbose_name = '合同编号序列'
        verbose_name_plural = '合同编号序列'


class ContractCheck(models.Model):
    """检查记录（§7.3 四个检查点）——**落库留痕**，修改后按轮次展示当时的检查内容。

    为什么落库：check(ctx) 结果原先瞬时返回即丢弃，合同修改后界面无法还原
    「当时检查了什么、结果如何」；落库后每轮次的检查内容可追溯、与效果审计对齐。
    """

    class Checkpoint(models.TextChoices):
        SUBMIT = 'SUBMIT', '提交草稿检查'
        RECHECK = 'RECHECK', '落账前再次检查'
        MODIFY = 'MODIFY', '修改后新检查'
        BACKFILL = 'BACKFILL', '补录基准检查'

    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='checks')
    round_no = models.PositiveIntegerField('所属轮次', default=0)
    checkpoint = models.CharField('检查点', max_length=16, choices=Checkpoint.choices)
    problems = models.JSONField('检查问题列表（空=通过）', default=list, blank=True)
    passed = models.BooleanField('通过', default=True)
    basis = models.JSONField(
        '检查依据快照（当时的字段值）', default=dict, blank=True,
        # {"buyer": {"cash": 1000}, ...} —— 重演时按账本链替换为重算值展示
    )
    checked_by = models.BigIntegerField('执行人（全局库用户 ID）', null=True, blank=True)
    checked_by_username = models.CharField('执行人用户名', max_length=150, blank=True)
    checked_at = models.DateTimeField('检查时间', auto_now_add=True)

    class Meta:
        verbose_name = '合同检查记录'
        verbose_name_plural = '合同检查记录'
        ordering = ['-checked_at']
        indexes = [models.Index(fields=['contract', 'round_no', 'checkpoint'])]
