"""合同插件试跑（dry-run，2026-11）：用比赛里的真实公司字段构造上下文跑 check/apply，**不写库**。

用途：比赛包作者/运营在启用合同类型前，先确认 check 会不会误报、apply 会产出哪些效果。
"""

from apps.competition.contracts import engine
from apps.competition.contracts.errors import ContractError
from apps.competition.contracts.services import contract_module_for
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from plugins_runtime.api import ContractContext


def _synthesize_inputs(schema, provided: dict | None) -> dict:
    """按 INPUT_SCHEMA 造一组可用输入（调用方给了就用调用方的）。"""
    provided = provided or {}
    values = {}
    for item in schema or []:
        key = item.get('key')
        if key in provided:
            values[key] = provided[key]
            continue
        field_type = str(item.get('type') or 'TEXT').upper()
        if field_type.startswith('LIST'):
            sample_row = {'item': _sample_ref(item.get('itemType'))}
            for field in (item.get('fields') or []):
                if str(field.get('type') or '').upper().startswith('NUMBER'):
                    minimum = field.get('min')
                    sample_row[field['key']] = (
                        minimum if isinstance(minimum, (int, float)) else 1)
                else:
                    sample_row[field['key']] = '试跑'
            values[key] = [sample_row]
            continue
        if field_type.startswith('NUMBER'):
            minimum = item.get('min')
            values[key] = minimum if isinstance(minimum, (int, float)) else 1
        elif field_type.startswith('BOOL'):
            values[key] = True
        elif field_type.startswith('REF'):
            values[key] = ''
        else:
            values[key] = '试跑'
    return values


def _sample_ref(item_type) -> str:
    """给 LIST 输入挑一个真实存在的引用值（原料/产品/零件/节点）。"""
    table = str(item_type or '').split(':', 1)[-1].strip().lower()
    if not table:
        table = 'materials'
    try:
        if table == 'materials':
            from apps.competition.basedata.models import Material

            name = Material.objects.values_list('name', flat=True).first()
            return name or '试跑原料'
        if table == 'products':
            from apps.competition.basedata.models import Product

            name = Product.objects.values_list('name', flat=True).first()
            return name or '试跑产品'
        if table == 'parts':
            from apps.competition.basedata.models import Part

            name = Part.objects.values_list('name', flat=True).first()
            return name or '试跑零件'
        if table == 'map_nodes':
            from apps.competition.basedata.models import MapNode

            name = MapNode.objects.values_list('name', flat=True).first()
            return name or '试跑节点'
        if table == 'fuels':
            from apps.competition.basedata.models import Fuel

            name = Fuel.objects.values_list('name', flat=True).first()
            return name or '试跑燃料'
        if table == 'tech_nodes':
            from apps.competition.basedata.models import TechNode

            name = TechNode.objects.values_list('name', flat=True).first()
            return name or '试跑科技'
        if table == 'infrastructures':
            from apps.competition.basedata.models import Infrastructure

            name = Infrastructure.objects.values_list('name', flat=True).first()
            return name or '试跑基建'
        if table == 'warehouses':
            from apps.competition.basedata.models import Warehouse

            name = Warehouse.objects.values_list('name', flat=True).first()
            return name or '试跑仓库'
        if table == 'production_lines':
            from apps.competition.basedata.models import ProductionLine

            name = ProductionLine.objects.values_list('name', flat=True).first()
            return name or '试跑生产线'
    except Exception:  # noqa: BLE001 —— 样例值取不到不影响试跑
        pass
    return '试跑'


def _company_field_values(companies) -> dict:
    """取公司字段值：优先无财年行，其次最新财年行（与引擎取数口径一致）。"""

    rows = (CompanyFieldValue.objects
            .filter(company_id__in=[c.id for c in companies])
            .select_related('fiscal_year'))
    buckets = {}
    for row in rows:
        buckets.setdefault((row.company_id, row.field_key), []).append(row)

    values = {}
    for company in companies:
        snapshot = {}
        for key in IndustryField.objects.values_list('field_key', flat=True):
            candidates = buckets.get((company.id, key), [])
            if not candidates:
                continue
            base = [r for r in candidates if r.fiscal_year_id is None]
            if base:
                snapshot[key] = base[0].value
            else:
                latest = max(candidates, key=lambda r: (r.fiscal_year.year if r.fiscal_year else 0))
                snapshot[key] = latest.value
        values[company.id] = snapshot
    return values


def dry_run_contract_plugin(*, contract_type_key: str, plugin_version: str = '',
                            inputs: dict | None = None,
                            company_ids: list | None = None) -> dict:
    """跑一次 check/apply 并回报结果；任何插件异常都转成可读信息，不抛 500。"""
    from apps.competition.companies.models import Company

    try:
        module = contract_module_for(contract_type_key, plugin_version)
    except Exception as exc:  # noqa: BLE001 —— 未注册/插件文件缺失都转成业务错误
        raise ContractError(
            f'合同类型 {contract_type_key} 未在本比赛启用（{type(exc).__name__}: {exc}）') from exc
    if module is None:
        raise ContractError(f'合同类型 {contract_type_key} 未在本比赛启用')

    roles = list(getattr(module, 'PARTY_ROLES', []) or [])
    schema = list(getattr(module, 'INPUT_SCHEMA', []) or [])
    run_inputs = _synthesize_inputs(schema, inputs)

    if company_ids:
        companies = list(Company.objects.filter(pk__in=company_ids))
    else:
        needed = max(len(roles), 1)
        companies = list(Company.objects.order_by('id')[:needed])
    if not companies:
        raise ContractError('本比赛还没有公司，无法试跑')

    fields = _company_field_values(companies)
    party_fields, industries, parties = {}, {}, {}
    for index, role in enumerate(roles):
        if not companies:
            break
        company = companies[min(index, len(companies) - 1)]
        parties[role.get('role')] = company.name
        industries[role.get('role')] = company.industry_key
        for key, value in (fields.get(company.id) or {}).items():
            party_fields[(role.get('role'), key)] = value

    from apps.competition.contracts.engine import node_maps

    node_maps = node_maps()
    context = ContractContext(parties=parties, inputs=run_inputs,
                              fields=party_fields, industries=industries,
                              node_regions=node_maps['region'],
                              node_cities=node_maps['city'])

    problems, error = [], ''
    try:
        problems = [str(p) for p in (engine._call_plugin(module.check, context, 'check') or [])]
    except ContractError as exc:
        error = str(exc)

    effects, warnings = [], []
    if not error:
        try:
            raw_effects = engine._call_plugin(module.apply, context, 'apply') or []
        except ContractError as exc:
            error = str(exc)
            raw_effects = []
        for effect in raw_effects:
            effects.append({
                'company': getattr(effect, 'company', ''),
                'field': getattr(effect, 'field', ''),
                'op': getattr(effect, 'op', ''),
                'value': getattr(effect, 'value', None),
                'region': getattr(effect, 'region', '') or '',
            })
            company_name = parties.get(getattr(effect, 'company', '')) \
                or getattr(effect, 'company', '')
            known = set(IndustryField.objects.values_list('field_key', flat=True))
            if not getattr(effect, 'region', '') and getattr(effect, 'field', '') not in known:
                warnings.append(
                    f'效果指向未定义字段「{getattr(effect, "field", "")}」'
                    f'（公司 {company_name}），落账会失败')

    return {
        'contractTypeKey': contract_type_key,
        'pluginVersion': plugin_version,
        'parties': parties,
        'inputs': run_inputs,
        'problems': problems,
        'effects': effects,
        'warnings': warnings,
        'error': error,
    }
