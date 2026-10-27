"""产业字段迁移服务（§8.2：插件定义字段/公式/数据类型/初始值；字段变化只迁本比赛库）。

- 插件 ``FIELDS`` → ``industry_fields``（字段级迁移：新增/更新定义、回填默认值）；
- 每次定义变化写**字段日志 SCHEMA_CHANGE**（§14.2，值变更 + 结构变更都记）；
- ``initial_values()`` 为公司初始化字段值（公司建档时调用，M2 汇入）；
- 公式重算：``evaluate_formula`` / ``recompute_company_fields``（§8.2 recompute）。
"""

import ast

from apps.competition.fieldlogs.models import FieldLog
from apps.competition.industries.models import CompanyFieldValue, IndustryField

TYPE_MAP = {
    'NUMBER': IndustryField.FieldType.NUMBER,
    'TEXT': IndustryField.FieldType.TEXT,
    'BOOL': IndustryField.FieldType.BOOL,
    'REF': IndustryField.FieldType.REF,
    'DATE': IndustryField.FieldType.DATE,
}
TABLE_MAP = {
    'entity': IndustryField.DataTable.ENTITY,
    'finance': IndustryField.DataTable.FINANCE,
}


def _field_defaults(spec: dict, plugin_key: str, plugin_version: str) -> dict:
    formula = spec.get('formula') or ''
    return {
        'name': spec.get('name') or spec['key'],
        'field_type': TYPE_MAP.get(spec.get('type'), IndustryField.FieldType.NUMBER),
        'default_value': spec.get('default'),
        'formula': formula,
        'data_table': TABLE_MAP.get(spec.get('table'), IndustryField.DataTable.ENTITY),
        'is_calculated': bool(spec.get('isCalculated')) or bool(formula),
        'timer_enabled': bool(spec.get('timerEnabled')),
        'timer_trigger': spec.get('timerTrigger') or '',
        'plugin_key': plugin_key,
        'plugin_version': plugin_version,
    }


# 「所在地」字段键：区域总览按「公司所在地 == 该区域下的地图节点名」把公司归入区域（旧系统口径）
LOCATION_FIELD_KEY = 'location'


def ensure_location_field(*, plugin_key='', plugin_version='', operator=None):
    """确保存在「所在地」字段（``field_key=location``）。

    旧系统在创建产业类型时自动补这个字段；新系统在产业插件字段迁移时补建，
    否则区域总览的「区域内公司」永远匹配不到公司（数据框就选不了公司）。
    产业插件自己定义了 ``location`` 时不覆盖。
    """
    if IndustryField.objects.filter(field_key=LOCATION_FIELD_KEY).exists():
        return None
    field = IndustryField.objects.create(
        field_key=LOCATION_FIELD_KEY,
        name='所在地',
        field_type=IndustryField.FieldType.TEXT,
        data_table=IndustryField.DataTable.ENTITY,
        industry_key=plugin_key,
        plugin_key=plugin_key,
        plugin_version=plugin_version,
        meta={'isLocation': True},
    )
    FieldLog.objects.create(
        company=None,
        field_key=LOCATION_FIELD_KEY,
        data_table=IndustryField.DataTable.ENTITY,
        event=FieldLog.Event.SCHEMA_CHANGE,
        op='MIGRATE',
        before_raw=None,
        after_raw={'key': LOCATION_FIELD_KEY, 'name': '所在地',
                   'type': IndustryField.FieldType.TEXT, 'isLocation': True},
        source=FieldLog.Source.SCHEMA_MIGRATE,
        operator_id=getattr(operator, 'id', None),
        operator_username=getattr(operator, 'username', ''),
    )
    return field


def apply_industry_fields(specs, *, plugin_key, plugin_version, operator=None):
    """把产业插件 FIELDS 同步到本比赛库（须在比赛上下文中）。返回迁移摘要。"""
    added = updated = 0
    for spec in specs:
        key = spec.get('key')
        if not key:
            continue
        defaults = _field_defaults(spec, plugin_key, plugin_version)
        obj, created = IndustryField.objects.update_or_create(field_key=key, defaults=defaults)
        if created:
            added += 1
            before = None
        else:
            updated += 1
            before = {'name': obj.name, 'type': obj.field_type}
        FieldLog.objects.create(
            company=None,
            field_key=key,
            data_table=defaults['data_table'],
            event=FieldLog.Event.SCHEMA_CHANGE,
            op='MIGRATE',
            before_raw=before,
            after_raw={'key': key, **{k: v for k, v in defaults.items() if k != 'default_value'},
                       'default': defaults['default_value']},
            source=FieldLog.Source.SCHEMA_MIGRATE,
            operator_id=getattr(operator, 'id', None),
            operator_username=getattr(operator, 'username', ''),
        )
    # 旧系统口径：产业建好后必有「所在地」字段，区域总览据此把公司归入区域
    ensure_location_field(
        plugin_key=plugin_key, plugin_version=plugin_version, operator=operator)
    return {'industryKey': plugin_key, 'added': added, 'updated': updated, 'total': len(specs)}


def initialize_company_values(company, initial: dict):
    """给公司回填初始值（entity 行 + finance 行挂当前财年为空）。"""
    created = 0
    for key, value in (initial or {}).items():
        _, was_created = CompanyFieldValue.objects.get_or_create(
            company=company, field_key=key, fiscal_year=None,
            defaults={'value': value, 'version': 1},
        )
        if was_created:
            created += 1
    return created


# ---------------------------------------------------------------- 产业插件（§8.2）


def get_industry_module(competition, industry_key):
    """按产业类型键加载产业插件（字段/公式/数据类型/初始值）。"""
    from apps.global_.packages.models import PackagePlugin
    from plugins_runtime import loader

    link = (
        PackagePlugin.objects
        .filter(package__competition=competition, kind='INDUSTRY', key=industry_key)
        .select_related('plugin')
        .order_by('-id')
        .first()
    )
    if link is None:
        return None
    from django.core.files.storage import default_storage
    try:
        module, problems = loader.load_plugin(default_storage.path(link.plugin.file_path))
    except Exception:  # noqa: BLE001 —— 插件文件缺失/不可读：按「取不到该产业」处理
        # 不向上抛：分配公司 / 建公司时缺插件只应导致「没有初始字段值」，不应 500。
        return None
    return None if problems else module


def industry_initial_values(competition, industry_key) -> dict:
    """产业初始值（插件 initial_values()，§8.2）。"""
    module = get_industry_module(competition, industry_key)
    if module is None:
        return {}
    func = getattr(module, 'initial_values', None)
    if callable(func):
        try:
            return func() or {}
        except Exception:  # noqa: BLE001 —— 插件异常转业务错误（§5.4）
            return {}
    return {f['key']: f.get('default') for f in module.FIELDS}


# ---------------------------------------------------------------- 公式重算（§8.2 recompute）


class FormulaError(Exception):
    pass


_ALLOWED_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b if b else 0,
    ast.Pow: lambda a, b: a ** b,
}
_ALLOWED_UNARY = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
}


def evaluate_formula(formula: str, values: dict):
    """安全的公式求值（只允许 字段键/数字/四则运算，不使用 eval）。"""
    import ast as _ast

    try:
        tree = _ast.parse(formula or '0', mode='eval')
    except SyntaxError as exc:
        raise FormulaError(f'公式语法错误：{exc}')

    def _eval(node):
        if isinstance(node, _ast.Expression):
            return _eval(node.body)
        if isinstance(node, _ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, _ast.Name):
            return float(values.get(node.id, 0) or 0)
        if isinstance(node, _ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            return _ALLOWED_BINOPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, _ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
            return _ALLOWED_UNARY[type(node.op)](_eval(node.operand))
        raise FormulaError(f'公式包含非法表达式：{_ast.dump(node)}')

    return _eval(tree)


def _consumer_demand_total(company) -> float:
    """特殊键 consumerDemand 的取值：该区域消费者需求总量（缺省 0）。

    懒导入 regions 模型避免应用间循环依赖；无区域归属直接返回 0。
    """
    region_id = getattr(company, 'region_id', None)
    if not region_id:
        return 0.0
    try:
        from django.db.models import Sum

        from apps.competition.regions.models import ConsumerDemand
        total = ConsumerDemand.objects.filter(region_id=region_id).aggregate(
            t=Sum('quantity'))['t']
        return float(total or 0)
    except Exception:  # noqa: BLE001 —— 公式重算不因需求表异常而中断
        return 0.0


def recompute_company_fields(company, *, fiscal_year=None, only_keys=None):
    """公式级联重算（插件 recompute / 字段 formula）：多轮传播至稳定。"""
    defs = {
        f.field_key: f for f in IndustryField.objects.filter(is_calculated=True)
        if f.formula and (only_keys is None or f.field_key in only_keys)
    }
    if not defs:
        return 0

    def _get(key):
        row = None
        if fiscal_year is not None:
            row = CompanyFieldValue.objects.filter(
                company=company, field_key=key, fiscal_year=fiscal_year).first()
        if row is None:
            row = CompanyFieldValue.objects.filter(
                company=company, field_key=key, fiscal_year__isnull=True).first()
        try:
            return float(row.value) if row and row.value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    changed = 0
    for _pass in range(3):  # 公式级联最多传播 3 轮
        values = {f.field_key: _get(f.field_key) for f in IndustryField.objects.all()}
        # 特殊键 consumerDemand：该区域消费者需求总量（旧 calcGraph 同名键语义，
        # 公式可直接引用；无区域/无需求时为 0）
        values['consumerDemand'] = _consumer_demand_total(company)
        pass_changed = 0
        for key, definition in defs.items():
            new_value = evaluate_formula(definition.formula, values)
            target_fy = fiscal_year if definition.data_table == IndustryField.DataTable.FINANCE else None
            row, _created = CompanyFieldValue.objects.get_or_create(
                company=company, field_key=key, fiscal_year=target_fy,
                defaults={'value': new_value, 'version': 1},
            )
            if not _created and row.value != new_value:
                row.value = new_value
                row.version += 1
                row.save(update_fields=['value', 'version', 'updated_at'])
                pass_changed += 1
        changed += pass_changed
        if not pass_changed:
            break
    del _pass
    return changed
