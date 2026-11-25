"""合同落账审计：字段日志写入（公司字段 / 区域字段共用）。"""

from apps.common import context as ctx
from apps.competition.fieldlogs.models import FieldLog
from apps.competition.industries.models import IndustryField


def write_field_log(*, company, field_key, op, before, after, source, contract,
                    round_no, operator, event=FieldLog.Event.VALUE_CHANGE, region=None):
    """写字段日志：区域字段落 ``REGION`` 数据表，公司字段取产业字段定义的数据表。"""
    if region is not None:
        data_table = 'REGION'
    else:
        definition = IndustryField.objects.filter(field_key=field_key).first()
        data_table = definition.data_table if definition else ''
    snapshot = ctx.get_device_snapshot() or {}
    return FieldLog.objects.create(
        company=company,
        region=region,
        field_key=field_key,
        data_table=data_table,
        event=event,
        op=op,
        before_raw=before,
        after_raw=after,
        source=source,
        contract=contract,
        round_no=round_no,
        operator_id=getattr(operator, 'id', None),
        operator_username=getattr(operator, 'username', ''),
        device_snapshot=snapshot,
        ip=snapshot.get('ip'),
        trace_id=ctx.get_trace_id() or '',
    )
