"""AST 静态扫描（§5.4 护栏 2：导入前 AST 扫描，禁危险调用，黑名单可配置）。"""

import ast

from django.conf import settings

DEFAULT_FORBIDDEN_MODULES = {
    'os', 'sys', 'subprocess', 'socket', 'ctypes', 'importlib', 'shutil',
    'pathlib', 'tempfile', 'signal', 'threading', 'multiprocessing',
    'webbrowser', 'requests', 'urllib', 'http', 'ftplib', 'telnetlib',
}

DEFAULT_FORBIDDEN_NAMES = {
    'eval', 'exec', 'compile', '__import__', 'open', 'input', 'globals',
    'locals', 'vars', 'getattr', 'setattr', 'delattr', 'breakpoint',
    'memoryview', 'exit', 'quit',
}

DEFAULT_FORBIDDEN_ATTRS = {
    'system', 'popen', 'spawn', 'fork', 'execv', 'execve',
    'urlopen', 'create_connection', 'check_output', 'check_call',
    'f_globals', 'f_locals', 'gi_frame', 'tb_frame', 'cr_frame',
    '__subclasses__', '__bases__', '__mro__', '__globals__',
}


def _config(name, default):
    return set(getattr(settings, name, default))


def scan(source: str, filename: str = '<plugin>') -> list:
    """扫描插件源码，返回问题列表（空 = 通过）。"""
    problems = []
    bad_modules = _config('PLUGINS_FORBIDDEN_MODULES', DEFAULT_FORBIDDEN_MODULES)
    bad_names = _config('PLUGINS_FORBIDDEN_NAMES', DEFAULT_FORBIDDEN_NAMES)
    bad_attrs = _config('PLUGINS_FORBIDDEN_ATTRS', DEFAULT_FORBIDDEN_ATTRS)

    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [f'语法错误：{exc}']

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split('.')[0]
                if root in bad_modules:
                    problems.append(f'第 {node.lineno} 行：禁止导入模块 {alias.name}')
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or '').split('.')[0]
            if root in bad_modules:
                problems.append(f'第 {node.lineno} 行：禁止导入模块 {node.module}')
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in bad_names:
                problems.append(f'第 {node.lineno} 行：禁止调用 {func.id}()')
            if isinstance(func, ast.Attribute) and func.attr in bad_attrs:
                problems.append(f'第 {node.lineno} 行：禁止调用属性 {func.attr}()')
        elif isinstance(node, ast.Attribute):
            if node.attr in bad_attrs:
                problems.append(f'第 {node.lineno} 行：禁止访问属性 {node.attr}')
        elif isinstance(node, ast.Name):
            if node.id in bad_names and isinstance(node.ctx, ast.Load):
                problems.append(f'第 {node.lineno} 行：禁止引用 {node.id}')
    return problems
