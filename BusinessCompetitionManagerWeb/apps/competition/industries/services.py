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
    module, problems = loader.load_plugin(default_storage.path(link.plugin.file_path))
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
