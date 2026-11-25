"""把旧版 SQLite 库（dist/db.sqlite3）中的 产业类型 / 合同类型 / 合同实例 转换为新版比赛包。

旧版合同是可视化 DSL（conditions + effects + graph），本脚本把 DSL 忠实翻译为
新版合同的 Python 插件（check/apply + 内嵌求值器），并生成 industries.xlsx / contracts.xlsx。

范围（2026-11 决策）：包含不依赖「清单聚合」的合同类型（18 类）；依赖 basedata 聚合
（仓库容量/路线距离/载具/基建/科技/物料清单等）的 16 类列入报告，需后续移植。

用法：
    .venv\\Scripts\\python.exe scripts\\convert_old_db_to_package.py
输出：
    dist/old_backup_package/                     （包目录）
    dist/old_backup_competition_package.zip      （可直接导入的比赛包）
    dist/old_backup_package/CONVERSION_REPORT.md （转换报告）
"""

import hashlib
import json
import pprint
import sqlite3
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import yaml


def pl(obj) -> str:
    """Python 字面量（json 的 true/null 不是合法 Python，统一用 pprint）。"""
    return pprint.pformat(obj, width=100, sort_dicts=False)

REPO = Path(__file__).resolve().parent.parent
OLD_DB = REPO / 'dist' / 'db.sqlite3'
OUT = REPO / 'dist' / 'old_backup_package'
ZIP = REPO / 'dist' / 'old_backup_competition_package.zip'
PKG_NAME = '旧版数据迁移'

# 依赖 basedata 清单聚合的标记：出现这些就跳过（列入报告）
AGGREGATE_MARKERS = [
    'CARBON', 'ROUTE_DISTANCE', 'ROUTE_PATH_TYPES', 'ROUTE_START_NODE_NAME',
    'ROUTE_END_NODE_NAME', 'ROUTE_DISTANCE_BY_TYPE', 'PART_MATERIALS',
    'PART_MATERIAL_TOTAL_QTY', 'PRODUCT_PARTS', 'PRODUCT_PARTS_TOTAL_QTY',
    'PART_TECH_NODES', 'PRODUCT_TECH_NODES', 'PRICE', 'MATERIAL_TOTAL_QTY',
    'PART_TOTAL_QTY', 'PRODUCT_TOTAL_QTY', 'FUEL_TOTAL_QTY', 'INFRA_TOTAL_QTY',
    'VEHICLE_TOTAL_PRICE', 'VEHICLE_MATERIAL_CARGO', 'VEHICLE_PART_CARGO',
    'VEHICLE_PRODUCT_CARGO', 'VEHICLE_FUEL_PER_KM', 'VEHICLE_CARBON',
    'FUEL_TOTAL_PRICE', 'WAREHOUSE_STORAGE', 'WAREHOUSE_TOTAL_PRICE',
    'PRODUCTION_LINE_PRICE', 'PRODUCTION_LINE_LABOR', 'PRODUCTION_LINE_CAPACITY',
    'TECH_PREREQUISITES', 'TECH_RESEARCH_COST',
    'INFRA_PRICE', 'INFRA_FOOTPRINT', 'INFRA_EMPLOYMENT', 'INFRA_POPULATION',
    'INFRA_HIGHQUALITY', 'INFRA_HAPPINESS', 'INFRA_INCOME', 'INFRA_CARBON',
    'INFRA_ACTIVATION_PRICE',
]

# 旧字段类型 → 新插件类型
FIELD_TYPE_MAP = {
    'NUMBER': 'NUMBER', 'INTEGER': 'NUMBER', 'FLOAT': 'NUMBER',
    'STRING': 'TEXT', 'TEXT': 'TEXT', 'DICTIONARY': 'TEXT', 'DICT': 'TEXT',
    'BOOLEAN': 'BOOL', 'BOOL': 'BOOL', 'LIST': 'TEXT',
}

# 旧输入类型 → 新输入类型
INPUT_TYPE_MAP = {
    'number': ('NUMBER', None),
    'string': ('TEXT', None),
    'mapNode': ('REF:map_nodes', None),
    'techNode': ('REF:tech_nodes', None),
    'nodeRoute': ('TEXT', None),
    'infrastructureList': ('TEXT', None),
    'materialList': ('TEXT', None),
    'partList': ('TEXT', None),
    'productList': ('TEXT', None),
    'vehicleList': ('TEXT', None),
    'warehouseList': ('TEXT', None),
    'productionLineList': ('TEXT', None),
    'ratingList': ('TEXT', None),
}

EVALUATOR = '''

def _num(v, fallback=0):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.strip()
        try:
            return float(s) if any(c in s for c in ".eE") else int(s)
        except ValueError:
            return fallback
    return fallback


def _as_dict(v):
    return v if isinstance(v, dict) else {}


def _as_list(v):
    return v if isinstance(v, list) else ([] if v is None else [v])


def _deep_eq(a, b):
    try:
        return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(
            b, sort_keys=True, ensure_ascii=False)
    except TypeError:
        return a == b


def _op(op, args):
    if op == "ADD":
        return _num(args[0]) + _num(args[1])
    if op == "SUB":
        return _num(args[0]) - _num(args[1])
    if op == "MUL":
        out = 1
        for a in args:
            out *= _num(a)
        return out
    if op == "DIV":
        right = _num(args[1])
        return 0 if right == 0 else _num(args[0]) / right
    if op == "MIN":
        return min(_num(a) for a in args)
    if op == "MAX":
        return max(_num(a) for a in args)
    if op in ("CMP_EQ", "EQ"):
        a, b = args[0], args[1]
        return _deep_eq(a, b) if isinstance(a, (list, dict)) or isinstance(b, (list, dict)) else a == b
    if op in ("CMP_NE", "NEQ"):
        return not _deep_eq(args[0], args[1]) if isinstance(args[0], (list, dict)) else args[0] != args[1]
    if op == "CMP_GT":
        return _num(args[0]) > _num(args[1])
    if op == "CMP_GTE":
        return _num(args[0]) >= _num(args[1])
    if op == "CMP_LT":
        return _num(args[0]) < _num(args[1])
    if op == "CMP_LTE":
        return _num(args[0]) <= _num(args[1])
    if op == "DICT_GET":
        d, k = _as_dict(args[0]), args[1]
        return d.get(k, args[2] if len(args) > 2 else None)
    if op == "DICT_HAS_KEY":
        return args[1] in _as_dict(args[0])
    if op == "DICT_KEYS":
        return list(_as_dict(args[0]).keys())
    if op == "DICT_VALUES":
        return list(_as_dict(args[0]).values())
    if op == "DICT_APPEND":
        out = dict(_as_dict(args[0]))
        out[args[1]] = args[2]
        return out
    if op == "DICT_MERGE":
        out = {}
        for a in args:
            out.update(_as_dict(a))
        return out
    if op == "LIST_LEN":
        return len(_as_list(args[0]))
    if op == "LIST_CONTAINS":
        return any(_deep_eq(x, args[1]) for x in _as_list(args[0]))
    if op == "LIST_UNIQUE":
        out = []
        for v in _as_list(args[0]):
            if not any(_deep_eq(x, v) for x in out):
                out.append(v)
        return out
    if op == "LIST_ADD":
        out = []
        for v in _as_list(args[0]) + _as_list(args[1]):
            if not any(_deep_eq(x, v) for x in out):
                out.append(v)
        return out
    if op == "LIST_SUM_OF":
        return sum(_num(x) for x in _as_list(args[0]))
    raise RuntimeError("旧版算子未支持：" + str(op))


def _eval(spec, ctx):
    if not isinstance(spec, dict):
        return spec
    stype = spec.get("type")
    if stype == "CONST":
        v = spec.get("value")
        if isinstance(v, str):
            s = v.strip()
            if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
                try:
                    return json.loads(s)
                except ValueError:
                    return v
        return v
    if stype == "INPUT":
        return ctx.input(spec.get("key"), spec.get("default"))
    if stype == "FIELD":
        return ctx.company_field(spec.get("party"), spec.get("fieldKey"), 0)
    if stype == "PARTY_COMPANY_NAME":
        return ctx.party(spec.get("party")) or ""
    if stype == "VAR":
        return ctx.input(spec.get("name"))
    if stype == "INDUSTRY_IS":
        industry = ctx.company_industry(spec.get("party")) if hasattr(ctx, "company_industry") else None
        return industry == spec.get("industryKey")
    if stype == "OP":
        return _op(spec.get("op"), [_eval(a, ctx) for a in (spec.get("args") or [])])
    return spec.get("value")


def _compare(v1, op, v2, kind):
    if kind == "DICT_COMPARE":
        stock, need = _as_dict(v1), _as_dict(v2)
        for key, qty in need.items():
            if _num(stock.get(key, 0)) < _num(qty):
                return False
        return True
    if kind == "LIST_COMPARE":
        have, want = _as_list(v1), _as_list(v2)
        return all(any(_deep_eq(x, w) for x in have) for w in want)
    a, b = v1, v2
    if op == "GTE":
        return _num(a) >= _num(b)
    if op == "GT":
        return _num(a) > _num(b)
    if op == "LTE":
        return _num(a) <= _num(b)
    if op == "LT":
        return _num(a) < _num(b)
    if op == "EQ":
        return _deep_eq(a, b) if isinstance(a, (list, dict)) else a == b
    if op == "NEQ":
        return not _deep_eq(a, b) if isinstance(a, (list, dict)) else a != b
    return False


def _cond_true(cond, ctx):
    ctype = cond.get("type")
    if ctype == "OP":
        return bool(_op(cond.get("op"), [_eval(a, ctx) for a in (cond.get("args") or [])]))
    if ctype == "INDUSTRY_IS":
        industry = ctx.company_industry(cond.get("party")) if hasattr(ctx, "company_industry") else None
        return industry == cond.get("industryKey")
    return False


def _collect_effects(effects, ctx, out):
    for eff in effects:
        kind = eff.get("kind")
        if kind == "FIELD":
            value = _eval(eff.get("value"), ctx)
            op = eff.get("op") or "SET"
            if isinstance(value, (dict, list)):
                op = "SET"  # 字典/列表字段：整值写入（旧版 DICT_APPEND/LIST_* 语义）
            elif op in ("ADD", "SUB"):
                value = _num(value)  # 旧版数值语义：缺失/非数值按 0
            out.append(Effect(company=eff.get("party"), field=eff.get("fieldKey"),
                              op=op, value=value))
        elif kind == "IF":
            branch = eff.get("then") if _cond_true(eff.get("cond") or {}, ctx) else eff.get("else")
            _collect_effects(branch or [], ctx, out)


def check(ctx):
    problems = []
    for cond in _DEFINITION.get("conditions") or []:
        kind = cond.get("kind")
        if kind not in ("VALUE_COMPARE", "DICT_COMPARE", "LIST_COMPARE"):
            continue
        v1 = _eval(cond.get("value1"), ctx)
        v2 = _eval(cond.get("value2"), ctx)
        if not _compare(v1, cond.get("op"), v2, kind):
            problems.append(cond.get("errorMessage") or "检查未通过")
    return problems


def apply(ctx):
    effects = []
    _collect_effects(_DEFINITION.get("effects") or [], ctx, effects)
    return effects
'''


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def parse_json(raw, default):
    if raw in (None, ''):
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def parse_default(value):
    if value in (None, ''):
        return None
    if isinstance(value, str):
        s = value.strip()
        if s in ('{}', '[]') or s.startswith('{') or s.startswith('['):
            try:
                # 字典/列表默认值按 JSON 字符串保存（与 xlsx 单元格类型一致，便于对账）
                return json.dumps(json.loads(s), ensure_ascii=False)
            except ValueError:
                return value
        try:
            return float(s) if any(c in s for c in '.eE') else int(s)
        except ValueError:
            return value
    return value


def build_industry_plugin(ind, fields, key):
    lines = [
        f'"""产业类型：{ind["name"]}（旧版数据自动转换，key={key}）。"""',
        '',
        f'INDUSTRY_KEY = "{key}"',
        f'INDUSTRY_NAME = {json.dumps(ind["name"], ensure_ascii=False)}',
        '',
        'FIELDS = [',
    ]
    for f in fields:
        ftype = FIELD_TYPE_MAP.get((f['field_type'] or 'STRING').upper(), 'TEXT')
        default = parse_default(f['default_value'])
        entry = {
            'key': f['field_key'],
            'name': f['name'],
            'type': ftype,
            'default': default,
            'table': 'entity',
        }
        formula = extract_formula(f)
        if formula:
            entry['formula'] = formula
        if f['timer_enabled']:
            entry['timerEnabled'] = True
            entry['timerTrigger'] = f['timer_trigger'] or 'FY_START'
        lines.append('    ' + pl(entry) + ',')
    lines.append(']')
    lines.append('')
    return '\n'.join(lines), {
        'key': key, 'name': ind['name'], 'fields': fields,
        'plugin_name': f'industry_{key}.py',
    }


def extract_formula(field):
    """旧版公式在 calc_graph 的 FORMULA 节点里；无则空。"""
    graph = parse_json(field.get('calc_graph'), {})
    for node in (graph or {}).get('nodes') or []:
        data = node.get('data') or {}
        if data.get('kind') == 'FORMULA' and data.get('expr'):
            return data['expr']
    return field.get('formula') or ''


def build_contract_plugin(ct, industry_key_by_id):
    roles = parse_json(ct['party_roles'], [])
    party_roles = []
    for role in roles:
        item = {'role': role.get('role'), 'label': role.get('label') or role.get('role')}
        if role.get('selectable') is False:
            item['optional'] = True
        party_roles.append(item)

    inputs = parse_json(ct['input_schema'], [])
    input_schema = []
    for item in inputs:
        kind = INPUT_TYPE_MAP.get(item.get('type'), ('TEXT', None))[0]
        entry = {'key': item.get('key'), 'label': item.get('label') or item.get('key'), 'type': kind}
        if item.get('required'):
            entry['required'] = True
        if item.get('min') is not None:
            entry['min'] = item.get('min')
        input_schema.append(entry)

    conditions = parse_json(ct['conditions'], [])
    effects = parse_json(ct['effects'], [])

    # 旧版 IF 条件引用 industryTypeId → 新插件用「产业 key」
    def rewrite(node):
        if isinstance(node, dict):
            if node.get('type') == 'INDUSTRY_IS' and node.get('industryTypeId') is not None:
                node = dict(node)
                node['industryKey'] = industry_key_by_id.get(node['industryTypeId'], '')
                node.pop('industryTypeId', None)
            return {k: rewrite(v) for k, v in node.items()}
        if isinstance(node, list):
            return [rewrite(v) for v in node]
        return node

    definition = {
        'contractTypeKey': ct['key'],
        'name': ct['name'],
        'conditions': rewrite(conditions),
        'effects': rewrite(effects),
    }

    src = f'''"""合同类型：{ct["name"]}（旧版数据自动转换：{ct["key"]}）。"""

import json

CONTRACT_KEY = {json.dumps(ct["key"], ensure_ascii=False)}
CONTRACT_NAME = {json.dumps(ct["name"], ensure_ascii=False)}

PARTY_ROLES = {pl(party_roles)}

INPUT_SCHEMA = {pl(input_schema)}

_DEFINITION = {pl(definition)}
{EVALUATOR}'''
    return src


def collect_field_types(fields):
    types = {}
    for f in fields:
        types[f['field_key']] = FIELD_TYPE_MAP.get((f['field_type'] or 'STRING').upper(), 'TEXT')
    return types


def main():
    if not OLD_DB.exists():
        raise SystemExit(f'找不到旧库：{OLD_DB}')
    conn = sqlite3.connect(OLD_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'plugins').mkdir(exist_ok=True)
    (OUT / 'sheets').mkdir(exist_ok=True)

    industries = [dict(r) for r in cur.execute('select * from industry_types order by id')]
    industry_key_by_id = {}
    industry_plugins = []
    fields_by_industry = {}
    for ind in industries:
        key = f'industry{ind["code"] or ind["id"]}'
        industry_key_by_id[ind['id']] = key
        fields = [dict(r) for r in cur.execute(
            'select * from industry_fields where industry_type_id=? order by sort_order, id', (ind['id'],))]
        fields_by_industry[key] = fields
        src, meta = build_industry_plugin(ind, fields, key)
        plugin_file = f'plugins/{meta["plugin_name"]}'
        (OUT / plugin_file).write_text(src, encoding='utf-8')
        industry_plugins.append((plugin_file, key, ind['name'], len(fields)))

    all_fields = [f for fs in fields_by_industry.values() for f in fs]

    type_rows = [dict(r) for r in cur.execute('select * from contract_types order by id')]
    contract_plugins = []
    supported, skipped = [], []
    for ct in type_rows:
        blob = (ct['effects'] or '') + (ct['conditions'] or '')
        used = [m for m in AGGREGATE_MARKERS if f'"{m}"' in blob]
        if used:
            skipped.append((ct['key'], ct['name'], used))
            continue
        key = ct['key'] if str(ct['key']).isidentifier() else ''.join(
            c if c.isalnum() or c == '_' else '_' for c in ct['key']) or f'contract{ct["id"]}'
        ct = dict(ct)
        ct['key'] = key
        src = build_contract_plugin(ct, industry_key_by_id)
        plugin_file = f'plugins/contract_{key}.py'
        (OUT / plugin_file).write_text(src, encoding='utf-8')
        supported.append((key, ct['name']))
        contract_plugins.append((plugin_file, key, ct['name']))

    # ---------- 合同实例 ----------
    companies = {r['id']: r['name'] for r in cur.execute('select id, name from companies')}
    supported_keys = {k for k, _ in supported}
    contract_rows = []
    for row in cur.execute('select * from contracts order by id'):
        ct = next((t for t in type_rows if t['id'] == row['contract_type_id']), None)
        if ct is None:
            continue
        key = ct['key'] if str(ct['key']).isidentifier() else ''.join(
            c if c.isalnum() or c == '_' else '_' for c in ct['key'])
        if key not in supported_keys:
            continue
        parties = []
        for p in parse_json(row['parties'], []):
            company_name = companies.get(p.get('companyId')) or '主办方'
            parties.append({'role': p.get('role'), 'companyName': company_name})
        contract_rows.append([
            key,
            row['name'] or ct['name'],
            json.dumps(parties, ensure_ascii=False),
            json.dumps(parse_json(row['inputs'], {}), ensure_ascii=False),
            '',
            f'旧系统迁移（旧ID {row["id"]}，状态 {row["status"]}）',
        ])

    # ---------- xlsx ----------
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = 'industries'
    ws.append(['industryKey', 'name', 'pluginFile', 'description'])
    for ind in industries:
        key = industry_key_by_id[ind['id']]
        ws.append([key, ind['name'],
                   f'plugins/industry_{key}.py', ind.get('description') or ''])
    ws2 = wb.create_sheet('fields')
    ws2.append(['industryKey', 'fieldKey', 'name', 'type', 'defaultValue', 'formula',
                'table', 'isCalculated', 'timerEnabled', 'timerTrigger'])
    for key, fields in fields_by_industry.items():
        for f in fields:
            ftype = FIELD_TYPE_MAP.get((f['field_type'] or 'STRING').upper(), 'TEXT')
            default = parse_default(f['default_value'])
            ws2.append([key, f['field_key'], f['name'], ftype,
                        '' if default is None else default,
                        extract_formula(f), 'entity',
                        'TRUE' if f['is_calculated'] else 'FALSE',
                        'TRUE' if f['timer_enabled'] else 'FALSE',
                        f['timer_trigger'] or ''])
    wb.save(OUT / 'sheets' / 'industries.xlsx')

    wb2 = Workbook()
    ws3 = wb2.active
    ws3.title = 'contracts'
    ws3.append(['contractTypeKey', 'name', 'partiesJSON', 'inputsJSON', 'fiscalYear', 'notes'])
    for row in contract_rows:
        ws3.append(row)
    wb2.save(OUT / 'sheets' / 'contracts.xlsx')

    # ---------- manifest ----------
    plugins_meta = []
    for plugin_file, key, name in contract_plugins:
        plugins_meta.append({'file': plugin_file, 'kind': 'CONTRACT', 'key': key, 'name': name,
                             'version': '1.0.0', 'sha256': sha256_file(OUT / plugin_file)})
    for plugin_file, key, name, _count in industry_plugins:
        plugins_meta.append({'file': plugin_file, 'kind': 'INDUSTRY', 'key': key, 'name': name,
                             'version': '1.0.0', 'sha256': sha256_file(OUT / plugin_file)})

    manifest = {
        'packageVersion': '1.0',
        'competition': {
            'name': PKG_NAME,
            'coverImage': '',
            'hostSchool': '',
            'location': '',
            'staffingInfo': '',
        },
        'plugins': plugins_meta,
        'sheets': [
            {'file': f'sheets/{p.name}', 'sha256': sha256_file(p)}
            for p in sorted((OUT / 'sheets').glob('*.xlsx'))
        ],
    }
    (OUT / 'manifest.yaml').write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding='utf-8')

    # ---------- zip ----------
    with ZipFile(ZIP, 'w', ZIP_DEFLATED) as zf:
        for p in sorted(OUT.rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts:
                zf.write(p, p.relative_to(OUT))

    # ---------- 报告 ----------
    total_contracts = cur.execute('select count(*) from contracts').fetchone()[0]
    report = [
        '# 旧版数据 → 新版比赛包 转换报告',
        '',
        f'- 旧库：`{OLD_DB}`',
        f'- 输出：`{ZIP}`（包目录 `{OUT}`）',
        f'- 产业类型：{len(industries)} 个（字段 {len(all_fields)} 个）',
        f'- 合同类型：转换 {len(supported)} 类；跳过 {len(skipped)} 类（依赖清单聚合，需移植）',
        f'- 合同实例：转换 {len(contract_rows)} 条 / 旧库共 {total_contracts} 条',
        '',
        '## 已转换的合同类型',
        '',
    ]
    report += [f'- `{k}` {n}' for k, n in supported]
    report += ['', '## 跳过（依赖 basedata 清单聚合，需后续移植）', '']
    report += [f'- `{k}` {n}：{", ".join(used)}' for k, n, used in skipped]
    report += [
        '',
        '## 转换约定',
        '',
        '- **产业字段**：旧 `field_type` → 新 `NUMBER/TEXT/BOOL`；默认值按 JSON/数字解析；',
        '  `calc_graph` 里的公式表达式提取为字段 `formula`；定时器 `timer_enabled/timer_trigger` 保留；',
        '- **数据表归属**：旧库无「实体表/财务报表」概念，统一按 `entity` 转换（如需按财年记账请手工调整 `table: finance`）；',
        '- **合同类型**：DSL 的 conditions/effects 内联为插件求值器；参与方/输入项保留中文 key；',
        '  `INDUSTRY_IS` 条件已改写为新产业 key，并依赖运行时 `ctx.company_industry()`；',
        '- **合同实例**：参与方按旧公司名映射（公司名为空的主办方记为「主办方」）；输入项原样保留；',
        '  实例以 `DRAFT` 草稿态导入，`notes` 记录旧 ID 与状态。',
        '',
        '## 未覆盖项',
        '',
        '- 16 类依赖清单聚合的合同（仓库/生产设备/物流/加工/基建/科技等）需先在新运行时补 basedata 访问层；',
        '- 已计算字段的 `formula` 目前只作为元数据保留（新系统公式引擎若为空需另行实现）；',
        '- 旧版「管理员禁用」类合同（资金增减/补上限）无业务对象，已按普通合同转换。',
        '',
    ]
    (OUT / 'CONVERSION_REPORT.md').write_text('\n'.join(report), encoding='utf-8')

    print(f'已生成比赛包：{ZIP}')
    print(f'产业类型 {len(industries)} 个 / 合同类型 {len(supported)} 个 / 合同实例 {len(contract_rows)} 条')
    print(f'跳过（聚合依赖）合同类型 {len(skipped)} 个：{", ".join(k for k, _, _ in skipped)}')


if __name__ == '__main__':
    main()
