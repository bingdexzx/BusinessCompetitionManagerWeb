"""比赛包表格解析（《比赛包格式规范》§5–§7）。

- 支持 xlsx（openpyxl）与 csv；第 1 行表头，列名大小写不敏感；
- 标准列 → 模型字段；**扩展列**原样入 meta JSON 并报警告；
- 校验：必填列、code 唯一、REF 引用、JSON 列可解析。
"""

import csv
import json

from pathlib import Path


# ---------------------------------------------------------------- 表格规格

# sheet 列名 → 模型字段名；未列出的列 = 扩展列 → meta
BASEDATA_SPECS = {
    'fuels': {
        'model': ('basedata', 'Fuel'),
        'required': ['code', 'name'],
        'columns': {'code': 'code', 'name': 'name', 'unit': 'unit',
                    'energyvalue': 'energy_value', 'price': 'price', 'notes': 'notes'},
        'floats': ['energyvalue', 'price'],
        'refs': {},
    },
    'warehouses': {
        'model': ('basedata', 'Warehouse'),
        'required': ['code', 'name'],
        'columns': {'code': 'code', 'name': 'name', 'capacity': 'capacity',
                    'regioncode': 'region_code', 'notes': 'notes'},
        'floats': ['capacity'],
        'refs': {'regioncode': ('maps', 'code')},
    },
    'vehicles': {
        'model': ('basedata', 'Vehicle'),
        'required': ['code', 'name'],
        'columns': {'code': 'code', 'name': 'name', 'vehicletype': 'vehicle_type',
                    'loadcapacity': 'load_capacity', 'speed': 'speed',
                    'fuelcode': 'fuel_code', 'fuelconsumption': 'fuel_consumption', 'notes': 'notes'},
        'floats': ['loadcapacity', 'speed', 'fuelconsumption'],
        'refs': {'fuelcode': ('fuels', 'code')},
    },
    'maps': {
        'model': ('basedata', 'MapRegion'),
        'required': ['code', 'name'],
        'columns': {'code': 'code', 'name': 'name', 'regiontype': 'region_type',
                    'adjacentcodes': 'adjacent_codes', 'distance': 'distance', 'notes': 'notes'},
        'floats': ['distance'],
        'refs': {},
    },
    'materials': {
        'model': ('basedata', 'Material'),
        'required': ['code', 'name'],
        'columns': {'code': 'code', 'name': 'name', 'unit': 'unit',
                    'baseprice': 'base_price', 'notes': 'notes'},
        'floats': ['baseprice'],
        'refs': {},
    },
    'products': {
        'model': ('basedata', 'Product'),
        'required': ['code', 'name'],
        'columns': {'code': 'code', 'name': 'name', 'unit': 'unit',
                    'baseprice': 'base_price', 'notes': 'notes'},
        'floats': ['baseprice'],
        'refs': {},
    },
    'parts': {
        'model': ('basedata', 'Part'),
        'required': ['code', 'name'],
        'columns': {'code': 'code', 'name': 'name', 'unit': 'unit',
                    'baseprice': 'base_price', 'compatibletypes': 'compatible_types', 'notes': 'notes'},
        'floats': ['baseprice'],
        'refs': {},
    },
    'infrastructures': {
        'model': ('basedata', 'Infrastructure'),
        'required': ['code', 'name'],
        'columns': {'code': 'code', 'name': 'name', 'infratype': 'infra_type',
                    'buildcost': 'build_cost', 'maintenancecost': 'maintenance_cost',
                    'effect': 'effect', 'notes': 'notes'},
        'floats': ['buildcost', 'maintenancecost'],
        'jsons': ['effect'],
        'refs': {},
    },
    'tech_tree': {
        'model': ('basedata', 'TechNode'),
        'required': ['code', 'name'],
        'columns': {'code': 'code', 'name': 'name',
                    'prerequisitecodes': 'prerequisite_codes', 'researchcost': 'research_cost',
                    'effect': 'effect', 'notes': 'notes'},
        'floats': ['researchcost'],
        'jsons': ['effect'],
        'refs': {},
    },
    'production_lines': {
        'model': ('basedata', 'ProductionLine'),
        'required': ['code', 'name'],
        'columns': {'code': 'code', 'name': 'name', 'inputs': 'inputs', 'outputs': 'outputs',
                    'capacity': 'capacity', 'buildcost': 'build_cost', 'notes': 'notes'},
        'floats': ['capacity', 'buildcost'],
        'jsons': ['inputs', 'outputs'],
        'refs': {},
    },
}

INDUSTRIES_SHEET = 'industries'
CONTRACTS_SHEET = 'contracts'


# ---------------------------------------------------------------- 读取


def read_table(path):
    """读取 xlsx/csv 第一个（或指定）工作表，返回 (headers, rows[dict])。"""
    path = Path(path)
    if path.suffix.lower() == '.csv':
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return [], []
        headers = [str(h).strip() for h in rows[0]]
        return headers, [dict(zip(headers, r)) for r in rows[1:] if any(c.strip() for c in r)]

    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return [], []
    headers = [str(h).strip() if h is not None else '' for h in rows[0]]
    out = []
    for raw in rows[1:]:
        if all(c is None or str(c).strip() == '' for c in raw):
            continue
        out.append({headers[i]: ('' if i >= len(raw) or raw[i] is None else raw[i])
                    for i in range(len(headers)) if headers[i]})
    return headers, out


# ---------------------------------------------------------------- 基础数据解析


def _norm(value):
    if isinstance(value, str):
        value = value.strip()
    return value if value not in ('', None) else None


def parse_basedata_sheet(sheet_key, headers, rows):
    """解析一张基础数据表 → (model_kwargs 列表, errors, warnings)。"""
    spec = BASEDATA_SPECS[sheet_key]
    errors, warnings = [], []
    col_map = spec['columns']
    header_norm = {str(h).strip().lower(): h for h in headers}

    missing = [c for c in spec['required'] if c not in header_norm]
    if missing:
        errors.append(f'缺少标准列：{", ".join(missing)}')
        return [], errors, warnings

    known = set(col_map)
    extra_headers = [h for h in headers if str(h).strip().lower() not in known]
    if extra_headers:
        warnings.append(f'扩展列（存入 meta）：{", ".join(extra_headers)}')

    entries, seen_codes = [], set()
    for i, raw in enumerate(rows, start=2):
        values = {}
        meta = {}
        for h in headers:
            hn = str(h).strip().lower()
            value = _norm(raw.get(h))
            if hn in col_map:
                values[col_map[hn]] = value
            else:
                meta[str(h).strip()] = value

        code = values.get('code')
        if not code:
            errors.append(f'第 {i} 行：code 为空')
            continue
        code = str(code)
        if code in seen_codes:
            errors.append(f'第 {i} 行：code 重复 {code}')
            continue
        seen_codes.add(code)
        values['code'] = code

        if values.get('name'):
            values['name'] = str(values['name'])

        for fc in spec.get('floats', []):
            if fc in values and values[fc] is not None:
                try:
                    values[col_map[fc]] = float(values[fc])
                except (TypeError, ValueError):
                    errors.append(f'第 {i} 行：{fc} 不是数值（{values[fc]}）')
        for ic in spec.get('ints', []):
            if ic in values and values[ic] is not None:
                try:
                    values[col_map[ic]] = int(float(values[ic]))
                except (TypeError, ValueError):
                    errors.append(f'第 {i} 行：{ic} 不是整数（{values[ic]}）')
        for jc in spec.get('jsons', []):
            if jc in values and values[jc] is not None:
                try:
                    values[col_map[jc]] = json.loads(values[jc]) if isinstance(values[jc], str) else values[jc]
                except (TypeError, ValueError):
                    errors.append(f'第 {i} 行：{jc} 不是合法 JSON')

        values['meta'] = meta
        entries.append(values)

    # REF 引用校验（目标 = 同包其他表的 code 集合，由调用方传入 cross_refs）
    return entries, errors, warnings


def check_refs(sheet_key, entries, all_codes):
    """校验 REF 引用列（悬空引用 → 错误）。all_codes: {sheet_key: set(codes)}"""
    spec = BASEDATA_SPECS[sheet_key]
    errors = []
    for col, (target_sheet, _) in spec.get('refs', {}).items():
        field = spec['columns'][col]
        valid = all_codes.get(target_sheet, set())
        for e in entries:
            value = e.get(field)
            if value and str(value) not in valid:
                errors.append(f'{e.get("code")}：{col}={value} 在 {target_sheet} 中不存在')
    return errors
