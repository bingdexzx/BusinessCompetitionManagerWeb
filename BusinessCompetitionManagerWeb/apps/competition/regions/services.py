"""区域域服务：消费者需求变更后的联动重算。"""

from __future__ import annotations


def recompute_region_demands(region_id: int | None) -> int:
    """消费者需求变更后重算该区域公司的公式字段（旧 `_recompute_dependent_fields` 语义）。

    公式可引用 `consumerDemand` 特殊键（该区域需求总量，见 industries.services）。
    返回受影响公司数。区域不存在/无公司时返回 0。

    回归约定（Decision 4.3）：`consumerDemand` 取值为该区域全部 ConsumerDemand
    的 `quantity` 求和（industries.services._consumer_demand_total，缺省 0），
    而非需求条数；变更任一需求后都按区域触发一次公司公式重算。
    """
    if not region_id:
        return 0
    from apps.competition.companies.models import Company
    from apps.competition.industries.services import recompute_company_fields

    count = 0
    for company in Company.objects.filter(region_id=region_id):
        recompute_company_fields(company)
        count += 1
    return count
