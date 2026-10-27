"""插件加载与接口签名校验（§8 合同/产业插件规范）。

加载流程：读文件 → SHA-256 → AST 扫描 → import 执行（受信任环境，决策 D2）
→ 注入受控 API（Effect/ContractContext）→ 接口签名校验。
"""

import hashlib
import importlib.util
import inspect
import sys
import uuid

from pathlib import Path

from plugins_runtime import ast_guard
from plugins_runtime.api import ContractContext, Effect, IndustryContext

__all__ = ['load_plugin', 'validate_contract_plugin', 'validate_industry_plugin',
           'sha256_file', 'ContractContext', 'Effect', 'IndustryContext']


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def load_plugin(path):
    """加载插件文件，返回 (module, problems)；problems 非空表示拒收。"""
    path = Path(path)
    source = path.read_text(encoding='utf-8')
    problems = ast_guard.scan(source, filename=str(path))
    if problems:
        return None, problems

    module_name = f'gipfel_plugin_{path.stem}_{uuid.uuid4().hex[:8]}'
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 —— 插件异常全部捕获转业务错误（§5.4）
        return None, [f'插件执行失败：{type(exc).__name__}: {exc}']
    finally:
        sys.modules.pop(module_name, None)

    # 注入受控 API（§8.1 示例中 Effect 直接可用，无需 import）
    module.Effect = Effect
    module.ContractContext = ContractContext
    module.IndustryContext = IndustryContext
    return module, []


def _require(problems, module, name, kind=None):
    if not hasattr(module, name):
        problems.append(f'缺少必备元素 {name}')
        return None
    value = getattr(module, name)
    if kind is not None and not isinstance(value, kind):
        problems.append(f'{name} 类型错误，应为 {kind.__name__}')
        return None
    return value


def validate_contract_plugin(module):
    """合同类型插件接口校验（§8.1）。返回问题列表。"""
    problems = []
    key = _require(problems, module, 'CONTRACT_KEY', str)
    display_name = _require(problems, module, 'CONTRACT_NAME', str)
    roles = _require(problems, module, 'PARTY_ROLES', list)
    schema = _require(problems, module, 'INPUT_SCHEMA', list)

    # 界面一律展示中文：缺少中文名会导致前端只能显示 key
    if isinstance(display_name, str) and not display_name.strip():
        problems.append('CONTRACT_NAME 不能为空（合同类型中文显示名）')

    if roles is not None:
        for i, role in enumerate(roles):
            if not isinstance(role, dict) or 'role' not in role:
                problems.append(f'PARTY_ROLES[{i}] 缺少 role')
            elif not str(role.get('label') or '').strip():
                problems.append(f'PARTY_ROLES[{i}]（{role.get("role")}）缺少 label（中文角色名）')
    if schema is not None:
        for i, item in enumerate(schema):
            if not isinstance(item, dict) or 'key' not in item or 'type' not in item:
                problems.append(f'INPUT_SCHEMA[{i}] 缺少 key/type')
            elif not str(item.get('label') or '').strip():
                problems.append(f'INPUT_SCHEMA[{i}]（{item.get("key")}）缺少 label（中文显示名）')

    for func_name in ('check', 'apply'):
        func = getattr(module, func_name, None)
        if not callable(func):
            problems.append(f'缺少可调用函数 {func_name}(ctx)')
            continue
        try:
            sig = inspect.signature(func)
            if len(sig.parameters) != 1:
                problems.append(f'{func_name} 签名应为 {func_name}(ctx)')
        except (TypeError, ValueError):
            problems.append(f'{func_name} 签名无法解析')

    if key is not None and not key.isidentifier():
        problems.append(f'CONTRACT_KEY 非法：{key}')
    return problems


def validate_industry_plugin(module):
    """产业类型插件接口校验（§8.2）。返回问题列表。"""
    problems = []
    key = _require(problems, module, 'INDUSTRY_KEY', str)
    display_name = _require(problems, module, 'INDUSTRY_NAME', str)
    fields = _require(problems, module, 'FIELDS', list)

    # 界面一律展示中文：产业名与每个字段名都必须有中文显示名
    if isinstance(display_name, str) and not display_name.strip():
        problems.append('INDUSTRY_NAME 不能为空（产业类型中文显示名）')

    if fields is not None:
        seen = set()
        for i, field in enumerate(fields):
            if not isinstance(field, dict):
                problems.append(f'FIELDS[{i}] 应为 dict')
                continue
            fkey = field.get('key')
            if not fkey:
                problems.append(f'FIELDS[{i}] 缺少 key')
                continue
            if fkey in seen:
                problems.append(f'字段键重复：{fkey}')
            seen.add(fkey)
            if not str(field.get('name') or '').strip():
                problems.append(f'字段 {fkey} 缺少 name（字段中文显示名）')
            if field.get('table') not in ('entity', 'finance', None):
                problems.append(f'字段 {fkey} 的 table 非法：{field.get("table")}')

    for func_name in ('initial_values', 'recompute'):
        func = getattr(module, func_name, None)
        if func is not None and not callable(func):
            problems.append(f'{func_name} 应为函数')

    if key is not None and not key.isidentifier():
        problems.append(f'INDUSTRY_KEY 非法：{key}')
    return problems
