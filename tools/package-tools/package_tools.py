#!/usr/bin/env python3
"""比赛包工程工具：创建 / 校验 / 打包。

命令：
    python tools/package-tools/package_tools.py init  <目录>          # 创建包工程脚手架
    python tools/package-tools/package_tools.py check <目录|zip>      # 校验包工程/比赛包
    python tools/package-tools/package_tools.py build <目录> [--out x.zip]  # 重算 hash 并打包

校验内容：
- manifest.yaml 结构（packageVersion / plugins / sheets / competition）
- 插件文件存在、sha256 一致、kind/key/version 合法
- 插件源码：AST 危险调用扫描 + 必须有 CONTRACT_KEY/INPUT_SCHEMA/check/apply 等符号
- 插件 key 与 manifest 一致；参与方角色、输入项类型、LIST 子字段合法
- xlsx 是否存在、可读取、表头/工作表是否符合规范
- zip 是否含路径穿越文件（zip-slip）
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print('缺少 PyYAML：请先 pip install pyyaml')
    raise SystemExit(2)

try:
    from openpyxl import Workbook, load_workbook
except ImportError:  # pragma: no cover
    Workbook = None
    load_workbook = None

FORBIDDEN_MODULES = {
    'os', 'sys', 'subprocess', 'socket', 'shutil', 'pathlib', 'importlib',
    'ctypes', 'pickle', 'builtins', 'requests', 'urllib', 'http',
    'django', 'apps', 'plugins_runtime',
}
FORBIDDEN_CALLS = {
    'eval', 'exec', 'compile', 'open', '__import__', 'getattr', 'setattr',
    'globals', 'locals', 'vars', 'input', 'breakpoint',
}
INPUT_TYPES = re.compile(
    r'^(NUMBER|TEXT|BOOLEAN|BOOL|REF:[a-z_]+|LIST:[a-z_]+)$', re.IGNORECASE)
LIST_TABLES = {'materials', 'parts', 'products', 'map_nodes', 'cities',
               'vehicles', 'companies', 'regions', 'fuels', 'tech_nodes',
               'infrastructures', 'warehouses', 'production_lines'}

ERRORS: list[str] = []
WARNINGS: list[str] = []


def error(message: str) -> None:
    ERRORS.append(message)


def warn(message: str) -> None:
    WARNINGS.append(message)


def ok(message: str) -> None:
    print(f'  ✓ {message}')


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- 创建工程
CONTRACT_TEMPLATE = '''"""合同插件示例（复制后修改）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bcm_plugin_sdk import InputSchema, PartyRoles, number_field, party_role

if TYPE_CHECKING:  # 类型提示用；Effect 由引擎注入
    from bcm_plugin_sdk import ContractContext, Effect

CONTRACT_KEY = "example_purchase"
CONTRACT_NAME = "示例采购合同"
NUMBER_PREFIX = "EX"

PARTY_ROLES: PartyRoles = [
    party_role("buyer", "买方"),
    party_role("seller", "卖方"),
]

INPUT_SCHEMA: InputSchema = [
    number_field("quantity", "数量", min=1),
    number_field("unitPrice", "单价", min=0),
]


def check(ctx: ContractContext) -> list[str]:
    problems: list[str] = []
    total = ctx.input_number("quantity") * ctx.input_number("unitPrice")
    if ctx.company_field("buyer", "cash", 0) < total:
        problems.append("买方资金不足")
    return problems


def apply(ctx: ContractContext) -> list[Effect]:
    total = ctx.input_number("quantity") * ctx.input_number("unitPrice")
    return [
        Effect.sub("buyer", "cash", total),
        Effect.add("seller", "cash", total),
    ]
'''

INDUSTRY_TEMPLATE = '''"""产业插件示例（复制后修改）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bcm_plugin_sdk import IndustryFieldSpec, industry_field

if TYPE_CHECKING:
    from bcm_plugin_sdk import IndustryContext

INDUSTRY_KEY = "example_industry"
INDUSTRY_NAME = "示例产业"

FIELDS: list[IndustryFieldSpec] = [
    industry_field("cash", "现金", table="finance", default=100000),
    industry_field("capacity", "产能", table="entity", default=10),
]
'''

DASHBOARD_TEMPLATE = {
    'title': '经营看板',
    'components': [
        {'id': 'cash', 'type': 'number', 'title': '现金合计',
         'bind': {'table': 'finance', 'fieldKey': 'cash', 'aggregate': 'sum'}},
        {'id': 'capacity', 'type': 'gauge', 'title': '产能',
         'bind': {'table': 'entity', 'fieldKey': 'capacity',
                  'aggregate': 'latest', 'max': 100}},
        {'id': 'note', 'type': 'text', 'title': '说明', 'text': '示例仪表盘，可自行修改'},
    ],
    'industries': {
        'example_industry': {
            'title': '示例产业',
            'components': [
                {'id': 'i_cash', 'type': 'number', 'title': '产业现金',
                 'bind': {'table': 'finance', 'fieldKey': 'cash', 'aggregate': 'sum'}},
            ],
        },
    },
}

REGION_FIELDS_TEMPLATE = {
    'fields': [
        {'key': 'market_capacity', 'name': '市场容量', 'type': 'NUMBER', 'default': 100,
         'condition': {'source': 'COMPANY', 'fieldKey': 'license', 'op': 'eq', 'value': True}},
        {'key': 'license', 'name': '经营许可', 'type': 'BOOL', 'default': False},
        {'key': 'level', 'name': '等级', 'type': 'TEXT', 'default': '二线'},
    ],
}

PACKAGE_README = '''# 比赛包工程

```bash
# 校验（目录或 zip）
python tools/package-tools/package_tools.py check .

# 重算 sha256 并打包
python tools/package-tools/package_tools.py build . --out ../my_package.zip
```

结构：

```
manifest.yaml
plugins/
  contract_example.py
  industry_example.py
sheets/
  industries.xlsx
  contracts.xlsx
```

修改插件后记得重新 `build`（会重写 manifest 里的 sha256），否则导入会校验失败。
'''


def _write_xlsx(path: Path, sheets: dict[str, tuple[list, list[list]]]) -> None:
    if Workbook is None:
        print('缺少 openpyxl，无法创建 xlsx')
        raise SystemExit(2)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    first = True
    for name, (headers, rows) in sheets.items():
        worksheet = workbook.active if first else workbook.create_sheet(name)
        if first:
            worksheet.title = name
            first = False
        worksheet.append(headers)
        for row in rows:
            worksheet.append(row)
    workbook.save(path)


def cmd_init(args) -> int:
    root = Path(args.directory).resolve()
    if root.exists() and any(root.iterdir()):
        print(f'目录非空，拒绝覆盖：{root}')
        return 1
    (root / 'plugins').mkdir(parents=True, exist_ok=True)
    (root / 'sheets').mkdir(parents=True, exist_ok=True)
    (root / 'plugins' / 'contract_example.py').write_text(CONTRACT_TEMPLATE, encoding='utf-8')
    (root / 'plugins' / 'industry_example.py').write_text(INDUSTRY_TEMPLATE, encoding='utf-8')
    (root / 'README.md').write_text(PACKAGE_README, encoding='utf-8')
    (root / 'dashboard.json').write_text(
        json.dumps(DASHBOARD_TEMPLATE, ensure_ascii=False, indent=2), encoding='utf-8')
    (root / 'region-fields.json').write_text(
        json.dumps(REGION_FIELDS_TEMPLATE, ensure_ascii=False, indent=2), encoding='utf-8')

    sdk_path = str((Path(__file__).resolve().parents[2] / 'tools' / 'plugin-sdk'))
    (root / '.vscode').mkdir(exist_ok=True)
    (root / '.vscode' / 'settings.json').write_text(json.dumps({
        'python.analysis.extraPaths': [sdk_path],
        'python.analysis.typeCheckingMode': 'basic',
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    (root / 'pyrightconfig.json').write_text(json.dumps({
        'extraPaths': [sdk_path],
        'typeCheckingMode': 'basic',
        'pythonVersion': '3.12',
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    _write_xlsx(root / 'sheets' / 'industries.xlsx', {
        'industries': (
            ['industryKey', 'name', 'pluginFile', 'description'],
            [['example_industry', '示例产业', 'plugins/industry_example.py', '示例产业']],
        ),
        'fields': (
            ['industryKey', 'fieldKey', 'name', 'type', 'defaultValue', 'formula',
             'table', 'isCalculated', 'timerEnabled', 'timerTrigger'],
            [['example_industry', 'cash', '现金', 'NUMBER', 100000, '', 'finance',
              'FALSE', 'FALSE', '']],
        ),
    })
    _write_xlsx(root / 'sheets' / 'contracts.xlsx', {
        'contracts': (
            ['contractTypeKey', 'name', 'partiesJSON', 'inputsJSON', 'fiscalYear', 'notes'],
            [['example_purchase', '示例采购', '[]', '{}', '', '示例数据，可删除']],
        ),
    })

    manifest = {
        'packageVersion': '1.0',
        'dashboard': 'dashboard.json',
        'regionFields': 'region-fields.json',
        'competition': {'name': '新的比赛'},
        'plugins': [
            {'file': 'plugins/contract_example.py', 'kind': 'CONTRACT',
             'key': 'example_purchase', 'name': '示例采购合同', 'version': '1.0.0',
             'sha256': sha256_file(root / 'plugins/contract_example.py')},
            {'file': 'plugins/industry_example.py', 'kind': 'INDUSTRY',
             'key': 'example_industry', 'name': '示例产业', 'version': '1.0.0',
             'sha256': sha256_file(root / 'plugins/industry_example.py')},
        ],
        'sheets': [
            {'file': 'sheets/industries.xlsx',
             'sha256': sha256_file(root / 'sheets/industries.xlsx')},
            {'file': 'sheets/contracts.xlsx',
             'sha256': sha256_file(root / 'sheets' / 'contracts.xlsx')},
        ],
    }
    (root / 'manifest.yaml').write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding='utf-8')
    print(f'已创建比赛包工程：{root}')
    print('下一步：python tools/package-tools/package_tools.py check ' + str(root))
    return 0


# ---------------------------------------------------------------- 校验
def scan_plugin(path: Path) -> ast.Module | None:
    try:
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        error(f'{path.name}: 语法错误：{exc}')
        return None
    except OSError as exc:
        error(f'{path.name}: 读取失败：{exc}')
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split('.')[0]
                if root in FORBIDDEN_MODULES:
                    error(f'{path.name}: 禁止 import {alias.name}')
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split('.')[0]
            if root in FORBIDDEN_MODULES:
                error(f'{path.name}: 禁止 from {node.module} import ...')
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                error(f'{path.name}: 禁止调用 {node.func.id}()')
        elif isinstance(node, ast.Attribute) and node.attr.startswith('__'):
            error(f'{path.name}: 禁止访问 {node.attr}')
    return tree


try:
    from bcm_plugin_sdk import (
        bool_field, industry_bool_field, industry_field, industry_number_field,
        industry_text_field, list_field, list_sub_field, number_field,
        party_role, ref_field, text_field,
    )
except ImportError:  # 允许在没装 SDK 的环境里校验纯 dict 写法的插件
    BUILDERS: dict = {}
else:
    BUILDERS = {
        'number_field': number_field, 'text_field': text_field,
        'bool_field': bool_field, 'ref_field': ref_field,
        'list_field': list_field, 'list_sub_field': list_sub_field,
        'party_role': party_role, 'industry_field': industry_field,
        'industry_number_field': industry_number_field,
        'industry_text_field': industry_text_field,
        'industry_bool_field': industry_bool_field,
    }


def _safe_eval(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List):
        return [_safe_eval(item) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_safe_eval(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return {_safe_eval(k): _safe_eval(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_safe_eval(node.operand)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        builder = BUILDERS.get(node.func.id)
        if builder is not None:
            args = [_safe_eval(arg) for arg in node.args]
            kwargs = {kw.arg: _safe_eval(kw.value) for kw in node.keywords if kw.arg}
            return builder(*args, **kwargs)
    raise ValueError('unsupported expression')


def module_constants(tree: ast.Module) -> dict:
    values = {}
    for node in tree.body:
        targets = []
        value = None
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
            value = node.value
        for target in targets:
            if value is None:
                values[target.id] = None
                continue
            try:
                values[target.id] = _safe_eval(value)
            except (ValueError, SyntaxError):
                values[target.id] = None
    return values


def module_functions(tree: ast.Module) -> set[str]:
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def validate_plugin(path: Path, entry: dict) -> None:
    tree = scan_plugin(path)
    if tree is None:
        return
    kind = str(entry.get('kind', '')).upper()
    constants = module_constants(tree)
    functions = module_functions(tree)
    expected_key = str(entry.get('key') or '')

    if kind == 'CONTRACT':
        for name in ('CONTRACT_KEY', 'CONTRACT_NAME', 'PARTY_ROLES', 'INPUT_SCHEMA'):
            if name not in constants or constants[name] in (None, ''):
                error(f'{path.name}: 缺少常量 {name}')
        if constants.get('CONTRACT_KEY') not in (None, expected_key):
            error(f'{path.name}: CONTRACT_KEY={constants.get("CONTRACT_KEY")!r} '
                  f'与 manifest key={expected_key!r} 不一致')
        for name in ('check', 'apply'):
            if name not in functions:
                error(f'{path.name}: 缺少函数 {name}(ctx)')
        roles = constants.get('PARTY_ROLES') or []
        if not isinstance(roles, list) or not roles:
            error(f'{path.name}: PARTY_ROLES 必须是非空列表')
        else:
            seen = set()
            for role in roles:
                if not isinstance(role, dict) or not role.get('role'):
                    error(f'{path.name}: PARTY_ROLES 每项必须是 {{role,label}}')
                    continue
                if role['role'] in seen:
                    error(f'{path.name}: 参与方角色重复：{role["role"]}')
                seen.add(role['role'])
        schema = constants.get('INPUT_SCHEMA') or []
        if not isinstance(schema, list):
            error(f'{path.name}: INPUT_SCHEMA 必须是列表')
            schema = []
        seen_keys = set()
        for field in schema:
            if not isinstance(field, dict) or not field.get('key'):
                error(f'{path.name}: INPUT_SCHEMA 每项必须含 key/label/type')
                continue
            key = field['key']
            if key in seen_keys:
                error(f'{path.name}: 输入项 key 重复：{key}')
            seen_keys.add(key)
            field_type = str(field.get('type') or '')
            if not INPUT_TYPES.match(field_type):
                error(f'{path.name}: 输入项 {key} 的 type 非法：{field_type!r}')
            if field_type.upper().startswith('LIST:'):
                table = field_type.split(':', 1)[1].lower()
                if table not in LIST_TABLES:
                    error(f'{path.name}: 清单 {key} 引用了未知表 {table}')
                if not field.get('itemLabel'):
                    warn(f'{path.name}: 清单 {key} 建议提供 itemLabel')
                for sub in field.get('fields') or []:
                    if not isinstance(sub, dict) or not sub.get('key'):
                        error(f'{path.name}: 清单 {key} 子字段缺少 key')
                    elif str(sub.get('type', '')).upper() != 'NUMBER':
                        warn(f'{path.name}: 清单 {key} 子字段 {sub.get("key")} 目前只支持 NUMBER')
    elif kind == 'INDUSTRY':
        for name in ('INDUSTRY_KEY', 'INDUSTRY_NAME', 'FIELDS'):
            if name not in constants or constants[name] in (None, ''):
                error(f'{path.name}: 缺少常量 {name}')
        if constants.get('INDUSTRY_KEY') not in (None, expected_key):
            error(f'{path.name}: INDUSTRY_KEY 与 manifest key 不一致')
        fields = constants.get('FIELDS') or []
        if not isinstance(fields, list) or not fields:
            error(f'{path.name}: FIELDS 必须是非空列表')
        else:
            seen = set()
            for field in fields:
                if not isinstance(field, dict) or not field.get('key'):
                    error(f'{path.name}: FIELDS 每项必须含 key/name/type/table')
                    continue
                if field['key'] in seen:
                    error(f'{path.name}: 字段 key 重复：{field["key"]}')
                seen.add(field['key'])
                if field.get('table') not in ('entity', 'finance'):
                    error(f'{path.name}: 字段 {field["key"]} 的 table 必须是 entity/finance')
    else:
        error(f'{path.name}: 未知插件类型 {kind!r}')


def validate_manifest(root: Path) -> dict | None:
    manifest_path = root / 'manifest.yaml'
    if not manifest_path.exists():
        error('缺少 manifest.yaml')
        return None
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
    except yaml.YAMLError as exc:
        error(f'manifest.yaml 解析失败：{exc}')
        return None
    if not isinstance(manifest, dict):
        error('manifest.yaml 顶层必须是对象')
        return None
    if not manifest.get('packageVersion'):
        error('manifest.yaml 缺少 packageVersion')
    plugins = manifest.get('plugins')
    if not isinstance(plugins, list) or not plugins:
        error('manifest.yaml 缺少 plugins 列表')
        plugins = []
    seen_keys = set()
    for entry in plugins:
        if not isinstance(entry, dict):
            error('plugins 每项必须是对象')
            continue
        for key in ('file', 'kind', 'key', 'sha256'):
            if not entry.get(key):
                error(f'插件条目缺少 {key}：{entry}')
        kind = str(entry.get('kind', '')).upper()
        if kind not in ('CONTRACT', 'INDUSTRY'):
            error(f'插件 kind 非法：{kind!r}')
        if entry.get('key') in seen_keys:
            error(f'插件 key 重复：{entry.get("key")}')
        seen_keys.add(entry.get('key'))
        file_rel = entry.get('file')
        if not file_rel:
            continue
        plugin_path = root / file_rel
        if not plugin_path.exists():
            error(f'插件文件不存在：{file_rel}')
            continue
        actual = sha256_file(plugin_path)
        if entry.get('sha256') != actual:
            error(f'{file_rel}: sha256 与 manifest 不一致（文件被改过后需重新 build）')
        validate_plugin(plugin_path, entry)

    listed = {str(entry.get('file', '')).replace('\\', '/') for entry in plugins}
    plugins_dir = root / 'plugins'
    if plugins_dir.is_dir():
        for path in sorted(plugins_dir.glob('*.py')):
            rel = path.relative_to(root).as_posix()
            if rel not in listed:
                warn(f'{rel} 未列入 manifest.plugins，导入时不会生效')

    sheets = manifest.get('sheets') or []
    if not isinstance(sheets, list):
        error('sheets 必须是列表')
        sheets = []
    for entry in sheets:
        if not isinstance(entry, dict) or not entry.get('file'):
            error('sheets 条目缺少 file')
            continue
        sheet_path = root / entry['file']
        if not sheet_path.exists():
            error(f'表格不存在：{entry["file"]}')
            continue
        if entry.get('sha256') and entry['sha256'] != sha256_file(sheet_path):
            error(f'{entry["file"]}: sha256 与 manifest 不一致')
        validate_sheet(sheet_path, root, manifest)
    return manifest


def validate_sheet(path: Path, root: Path, manifest: dict) -> None:
    if load_workbook is None:
        warn('未安装 openpyxl，跳过表格校验')
        return
    try:
        workbook = load_workbook(path, read_only=True)
    except Exception as exc:  # noqa: BLE001
        error(f'{path.name}: 无法读取：{exc}')
        return
    names = set(workbook.sheetnames)
    if path.name == 'industries.xlsx':
        if 'industries' not in names:
            error(f'{path.name}: 缺少 industries 工作表')
        else:
            headers = _headers(workbook['industries'])
            for col in ('industryKey', 'name', 'pluginFile'):
                if col not in headers:
                    error(f'{path.name}: industries 缺少列 {col}')
        industry_keys = {entry.get('key') for entry in manifest.get('plugins') or []
                         if str(entry.get('kind')).upper() == 'INDUSTRY'}
        if 'industries' in names:
            sheet = workbook['industries']
            headers = _headers(sheet)
            if 'industryKey' in headers and 'pluginFile' in headers:
                index_key = _column_index(sheet, 'industryKey')
                index_file = _column_index(sheet, 'pluginFile')
                for row in sheet.iter_rows(min_row=2, values_only=True):
                    key = row[index_key] if index_key < len(row) else None
                    file_rel = row[index_file] if index_file < len(row) else None
                    if key and industry_keys and key not in industry_keys:
                        error(f'{path.name}: 产业 {key} 没有对应的 INDUSTRY 插件')
                    if file_rel and not (root / str(file_rel)).exists():
                        error(f'{path.name}: pluginFile 不存在：{file_rel}')
        if 'fields' in names:
            headers = _headers(workbook['fields'])
            for col in ('industryKey', 'fieldKey', 'name', 'type', 'table'):
                if col not in headers:
                    error(f'{path.name}: fields 缺少列 {col}')
    elif path.name == 'contracts.xlsx':
        sheet = 'contracts' if 'contracts' in names else (
            workbook.sheetnames[0] if workbook.sheetnames else '')
        if not sheet:
            error(f'{path.name}: 没有工作表')
        else:
            headers = _headers(workbook[sheet])
            for col in ('contractTypeKey', 'name', 'partiesJSON', 'inputsJSON'):
                if col not in headers:
                    error(f'{path.name}: 缺少列 {col}')
            contract_keys = {entry.get('key') for entry in manifest.get('plugins') or []
                             if str(entry.get('kind')).upper() == 'CONTRACT'}
            if 'contractTypeKey' in headers:
                index_key = _column_index(workbook[sheet], 'contractTypeKey')
                for row in workbook[sheet].iter_rows(min_row=2, values_only=True):
                    key = row[index_key] if index_key < len(row) else None
                    if key and contract_keys and key not in contract_keys:
                        error(f'{path.name}: 合同类型 {key} 没有对应的 CONTRACT 插件')
    workbook.close()


def _column_index(worksheet, name: str) -> int:
    for index, value in enumerate(next(worksheet.iter_rows(min_row=1, max_row=1,
                                                           values_only=True), ())):
        if value == name:
            return index
    return 0


def _headers(worksheet) -> set[str]:
    for row in worksheet.iter_rows(min_row=1, max_row=1, values_only=True):
        return {str(value).strip() for value in row if value is not None}
    return set()


DASHBOARD_TYPES = {'number', 'gauge', 'table', 'text'}
DASHBOARD_AGGREGATES = {'sum', 'latest', 'average'}


def _validate_dashboard_components(where: str, components) -> None:
    if not isinstance(components, list):
        error(f'{where} 必须是数组')
        return
    for index, comp in enumerate(components):
        tag = f'{where}[{index}]'
        if not isinstance(comp, dict):
            error(f'{tag} 必须是对象')
            continue
        ctype = comp.get('type')
        if ctype not in DASHBOARD_TYPES:
            error(f'{tag}.type 必须是 {"|".join(sorted(DASHBOARD_TYPES))}')
        if not comp.get('title'):
            error(f'{tag}.title 不能为空')
        if ctype == 'text':
            continue
        bind = comp.get('bind')
        if not isinstance(bind, dict):
            error(f'{tag}.bind 必须是对象')
            continue
        if bind.get('table') not in ('entity', 'finance'):
            error(f'{tag}.bind.table 必须是 entity|finance')
        if not bind.get('fieldKey'):
            error(f'{tag}.bind.fieldKey 不能为空')
        if bind.get('aggregate', 'latest') not in DASHBOARD_AGGREGATES:
            error(f'{tag}.bind.aggregate 必须是 {"|".join(sorted(DASHBOARD_AGGREGATES))}')


def validate_dashboard(root: Path, manifest: dict) -> None:
    rel = str(manifest.get('dashboard') or 'dashboard.json')
    path = root / rel
    if manifest.get('dashboard') and not path.exists():
        error(f'manifest 声明的仪表盘文件不存在：{rel}')
        return
    if not path.exists():
        return
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        error(f'{rel}: JSON 解析失败：{exc}')
        return
    if not isinstance(doc, dict):
        error(f'{rel}: 顶层必须是对象')
        return
    _validate_dashboard_components(f'{rel}.components', doc.get('components'))
    industries = doc.get('industries')
    if industries is not None and not isinstance(industries, dict):
        error(f'{rel}.industries 必须是对象')
        return
    industry_keys = {entry.get('key') for entry in manifest.get('plugins') or []
                     if str(entry.get('kind')).upper() == 'INDUSTRY'}
    for key, section in (industries or {}).items():
        if not isinstance(section, dict):
            error(f'{rel}.industries.{key} 必须是对象')
            continue
        if industry_keys and key not in industry_keys:
            error(f'{rel}.industries.{key} 没有对应的 INDUSTRY 插件')
        _validate_dashboard_components(f'{rel}.industries.{key}.components',
                                       section.get('components'))
    ok(f'{rel} 仪表盘结构合法')


REGION_FIELD_TYPES = {'NUMBER', 'TEXT', 'BOOL', 'DATE'}
REGION_CONDITION_OPS = {'eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'in'}
REGION_CONDITION_SOURCES = {'COMPANY', 'REGION'}


def validate_region_fields(root: Path, manifest: dict) -> None:
    rel = str(manifest.get('regionFields') or 'region-fields.json')
    path = root / rel
    if manifest.get('regionFields') and not path.exists():
        error(f'manifest 声明的区域字段文件不存在：{rel}')
        return
    if not path.exists():
        return
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        error(f'{rel}: JSON 解析失败：{exc}')
        return
    specs = doc.get('fields') if isinstance(doc, dict) else doc
    if not isinstance(specs, list):
        error(f'{rel}: fields 必须是数组')
        return
    seen = set()
    for index, spec in enumerate(specs):
        where = f'{rel} fields[{index}]'
        if not isinstance(spec, dict):
            error(f'{where} 必须是对象')
            continue
        key = str(spec.get('key') or '').strip()
        if not re.match(r'^[A-Za-z0-9_]{1,64}$', key):
            error(f'{where}.key 只能包含字母/数字/下划线（1-64）')
        elif key in seen:
            error(f'{where}.key 重复：{key}')
        else:
            seen.add(key)
        if not str(spec.get('name') or '').strip():
            error(f'{where}.name 不能为空')
        field_type = str(spec.get('type') or spec.get('fieldType') or 'NUMBER').upper()
        if field_type not in REGION_FIELD_TYPES:
            error(f'{where}.type 必须是 {"|".join(sorted(REGION_FIELD_TYPES))}')
        condition = spec.get('condition')
        if condition:
            if not isinstance(condition, dict):
                error(f'{where}.condition 必须是对象')
                continue
            source = str(condition.get('source') or 'COMPANY').upper()
            if source not in REGION_CONDITION_SOURCES:
                error(f'{where}.condition.source 必须是 COMPANY|REGION')
            if not str(condition.get('fieldKey') or condition.get('field') or '').strip():
                error(f'{where}.condition.fieldKey 必填')
            op = str(condition.get('op') or 'eq')
            if op not in REGION_CONDITION_OPS:
                error(f'{where}.condition.op 必须是 {"|".join(sorted(REGION_CONDITION_OPS))}')
            if 'value' not in condition:
                error(f'{where}.condition.value 必填')
    ok(f'{rel} 区域字段定义合法（{len(specs)} 个）')


def validate_optional_files(root: Path, manifest: dict) -> None:
    validate_dashboard(root, manifest)
    validate_region_fields(root, manifest)


def check_directory(root: Path) -> int:
    ERRORS.clear()
    WARNINGS.clear()
    print(f'校验包工程：{root}')
    manifest = validate_manifest(root)
    if manifest:
        validate_optional_files(root, manifest)
        ok(f'manifest.yaml：{len(manifest.get("plugins") or [])} 个插件、'
           f'{len(manifest.get("sheets") or [])} 张表')
    for message in WARNINGS:
        print(f'  ! {message}')
    if ERRORS:
        print('\n发现错误：')
        for message in ERRORS:
            print(f'  ✗ {message}')
        return 1
    print('\n校验通过 ✓')
    return 0


def extract_zip(zip_path: Path, target: Path) -> bool:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            for name in names:
                dest = (target / name).resolve()
                if not str(dest).startswith(str(target.resolve()) + '\\') and \
                        not str(dest).startswith(str(target.resolve()) + '/'):
                    error(f'压缩包含非法路径：{name}')
                    return False
            archive.extractall(target)
    except zipfile.BadZipFile as exc:
        error(f'不是合法的 zip：{exc}')
        return False
    return True


def cmd_check(args) -> int:
    source = Path(args.path).resolve()
    if source.is_dir():
        return check_directory(source)
    if source.is_file() and zipfile.is_zipfile(source):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            if not extract_zip(source, target):
                for message in ERRORS:
                    print(f'  ✗ {message}')
                return 1
            return check_directory(target)
    print(f'路径不是目录或 zip：{source}')
    return 1


# ---------------------------------------------------------------- 打包
def cmd_build(args) -> int:
    root = Path(args.directory).resolve()
    manifest_path = root / 'manifest.yaml'
    if not manifest_path.exists():
        print('缺少 manifest.yaml，请先 init')
        return 1
    manifest = yaml.safe_load(manifest_path.read_text(encoding='utf-8')) or {}
    for entry in manifest.get('plugins') or []:
        path = root / entry['file']
        if path.exists():
            entry['sha256'] = sha256_file(path)
    for entry in manifest.get('sheets') or []:
        path = root / entry['file']
        if path.exists():
            entry['sha256'] = sha256_file(path)
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding='utf-8')

    status = check_directory(root)
    if status != 0:
        print('\n校验未通过，未打包')
        return status

    out = Path(args.out).resolve() if args.out else root.parent / f'{root.name}.zip'
    out.parent.mkdir(parents=True, exist_ok=True)
    exclude = {'.vscode', 'pyrightconfig.json'}
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob('*')):
            if not path.is_file():
                continue
            if any(part in exclude for part in path.relative_to(root).parts):
                continue
            archive.write(path, path.relative_to(root))
    print(f'\n已打包：{out}')
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        # 无参数：默认检查当前目录，比只打印 usage 更实用
        argv = ['check', '.']
    elif argv[0] not in ('init', 'check', 'build') and not argv[0].startswith('-'):
        # 直接传目录/zip：等价于 check <路径>
        argv = ['check', *argv]

    parser = argparse.ArgumentParser(
        description='比赛包工程工具（init / check / build；直接传路径等价于 check）')
    sub = parser.add_subparsers(dest='command', required=True)
    init_parser = sub.add_parser('init', help='创建包工程脚手架')
    init_parser.add_argument('directory')
    check_parser = sub.add_parser('check', help='校验目录或 zip')
    check_parser.add_argument('path')
    build_parser = sub.add_parser('build', help='重算 sha256 并打包')
    build_parser.add_argument('directory')
    build_parser.add_argument('--out', help='输出 zip 路径')
    args = parser.parse_args(argv)
    if args.command == 'init':
        return cmd_init(args)
    if args.command == 'check':
        return cmd_check(args)
    if args.command == 'build':
        return cmd_build(args)
    return 1


if __name__ == '__main__':
    sys.exit(main())
