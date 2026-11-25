"""静态校验插件源码（不起 Django，编辑器/终端都能用）。

    python -m bcm_plugin_sdk check plugins/contract_x.py

返回问题列表；也可以在自己的脚本里调用 ``validate_source``。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

FORBIDDEN_MODULES = {
    'os', 'sys', 'subprocess', 'socket', 'shutil', 'pathlib', 'importlib',
    'ctypes', 'pickle', 'builtins', 'requests', 'urllib', 'http',
    'django', 'apps', 'plugins_runtime',
}
FORBIDDEN_CALLS = {
    'eval', 'exec', 'compile', 'open', '__import__', 'getattr', 'setattr',
    'globals', 'locals', 'vars', 'input', 'breakpoint',
}
VALID_FIELD_TYPES = {
    'NUMBER', 'TEXT', 'BOOLEAN', 'BOOL',
}
VALID_TABLES = {
    'materials', 'parts', 'products', 'map_nodes', 'cities', 'vehicles',
    'companies', 'regions', 'fuels', 'tech_nodes', 'infrastructures',
    'warehouses', 'production_lines',
}


from . import schema as _schema

_BUILDERS = {
    name: getattr(_schema, name)
    for name in ('number_field', 'text_field', 'bool_field', 'ref_field',
                 'list_field', 'list_sub_field', 'party_role', 'industry_field')
}


def _safe_eval(node):
    """优先 literal_eval；遇到 SDK 构造函数则调用同名函数求值。"""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        pass
    if isinstance(node, ast.List):
        return [_safe_eval(item) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_safe_eval(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return {_safe_eval(k): _safe_eval(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_safe_eval(node.operand)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        builder = _BUILDERS.get(node.func.id)
        if builder is not None:
            args = [_safe_eval(arg) for arg in node.args]
            kwargs = {kw.arg: _safe_eval(kw.value) for kw in node.keywords if kw.arg}
            return builder(*args, **kwargs)
    raise ValueError('unsupported expression')


def _literal_constants(tree: ast.Module) -> dict:
    values: dict = {}
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


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _check_signature(problems: list[str], name: str, function: ast.FunctionDef) -> None:
    if len(function.args.args) != 1:
        problems.append(f'{name}(ctx) 需要且只需要一个参数 ctx')
    if function.args.vararg or function.args.kwarg:
        problems.append(f'{name}(ctx) 不支持 *args/**kwargs')


def _check_field(problems: list[str], where: str, field) -> None:
    if not isinstance(field, dict):
        problems.append(f'{where} 必须是对象')
        return
    if not field.get('key'):
        problems.append(f'{where}.key 不能为空')
    if not field.get('label'):
        problems.append(f'{where}.label 不能为空')
    field_type = str(field.get('type') or '')
    if field_type.upper() in VALID_FIELD_TYPES:
        return
    prefix, _, table = field_type.partition(':')
    if prefix.upper() not in ('REF', 'LIST') or table not in VALID_TABLES:
        problems.append(f'{where}.type 非法：{field_type!r}（NUMBER/TEXT/BOOLEAN/REF:<表>/LIST:<表>）')
        return
    if prefix.upper() == 'LIST':
        if not field.get('itemLabel'):
            problems.append(f'{where}.itemLabel 建议填写（清单条目的中文名）')
        for index, sub in enumerate(field.get('fields') or []):
            if not isinstance(sub, dict) or not sub.get('key'):
                problems.append(f'{where}.fields[{index}] 缺少 key')
            elif str(sub.get('type', 'NUMBER')).upper() != 'NUMBER':
                problems.append(f'{where}.fields[{index}].type 目前只支持 NUMBER')


def validate_source(source: str, filename: str = '<plugin>') -> list[str]:
    """校验一段插件源码，返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [f'语法错误：{exc}']

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] in FORBIDDEN_MODULES:
                    problems.append(f'禁止 import {alias.name}')
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split('.')[0] in FORBIDDEN_MODULES:
                problems.append(f'禁止 from {node.module} import ...')
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                problems.append(f'禁止调用 {node.func.id}()')
        elif isinstance(node, ast.Attribute) and node.attr.startswith('__'):
            problems.append(f'禁止访问 {node.attr}')

    constants = _literal_constants(tree)
    functions = _functions(tree)

    if 'CONTRACT_KEY' in constants:
        for name in ('CONTRACT_NAME', 'PARTY_ROLES', 'INPUT_SCHEMA'):
            if not constants.get(name):
                problems.append(f'合同插件缺少常量 {name}')
        for name in ('check', 'apply'):
            if name not in functions:
                problems.append(f'合同插件缺少函数 {name}(ctx)')
            else:
                _check_signature(problems, name, functions[name])
        roles = constants.get('PARTY_ROLES') or []
        if not isinstance(roles, list) or not roles:
            problems.append('PARTY_ROLES 必须是非空列表')
        else:
            seen = set()
            for index, role in enumerate(roles):
                if not isinstance(role, dict) or not role.get('role'):
                    problems.append(f'PARTY_ROLES[{index}] 缺少 role')
                    continue
                if role['role'] in seen:
                    problems.append(f'参与方角色重复：{role["role"]}')
                seen.add(role['role'])
        schema = constants.get('INPUT_SCHEMA') or []
        if not isinstance(schema, list):
            problems.append('INPUT_SCHEMA 必须是列表')
        else:
            keys = set()
            for index, field in enumerate(schema):
                _check_field(problems, f'INPUT_SCHEMA[{index}]', field)
                if isinstance(field, dict) and field.get('key') in keys:
                    problems.append(f'输入项 key 重复：{field["key"]}')
                if isinstance(field, dict):
                    keys.add(field.get('key'))
    elif 'INDUSTRY_KEY' in constants:
        for name in ('INDUSTRY_NAME', 'FIELDS'):
            if not constants.get(name):
                problems.append(f'产业插件缺少常量 {name}')
        fields = constants.get('FIELDS') or []
        if not isinstance(fields, list) or not fields:
            problems.append('FIELDS 必须是非空列表')
        else:
            keys = set()
            for index, field in enumerate(fields):
                if not isinstance(field, dict) or not field.get('key'):
                    problems.append(f'FIELDS[{index}] 缺少 key')
                    continue
                if field['key'] in keys:
                    problems.append(f'字段 key 重复：{field["key"]}')
                keys.add(field['key'])
                if field.get('table') not in ('entity', 'finance'):
                    problems.append(f'FIELDS[{index}].table 必须是 entity|finance')
    else:
        problems.append('既不是合同插件（CONTRACT_KEY）也不是产业插件（INDUSTRY_KEY）')
    return problems


def validate_file(path: Path) -> list[str]:
    try:
        source = path.read_text(encoding='utf-8')
    except OSError as exc:
        return [f'读取失败：{exc}']
    return validate_source(source, str(path))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help'):
        print('用法：python -m bcm_plugin_sdk check <插件.py> [更多文件...]')
        print('      python -m bcm_plugin_sdk check --all <目录>')
        return 0
    if argv[0] == 'check':
        argv = argv[1:]
    if argv and argv[0] == '--all':
        directory = Path(argv[1] if len(argv) > 1 else '.')
        files = sorted(directory.rglob('*.py'))
    else:
        files = [Path(item) for item in argv]
    failed = 0
    for path in files:
        problems = validate_file(path)
        if problems:
            failed += 1
            print(f'✗ {path}')
            for problem in problems:
                print(f'    - {problem}')
        else:
            print(f'✓ {path}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
