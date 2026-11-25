"""公式依赖图：找出循环依赖（导入时拒绝计算这些字段）。

为什么单独成模块：导入（industry 插件）、重算（services）和测试都要用同一份判定，
避免三处各写一套「依赖解析」。
"""

import ast


def formula_references(formula: str) -> set:
    """公式里引用的字段键（排除函数名，如 round/log/IF）。"""
    try:
        tree = ast.parse(formula or '0', mode='eval')
    except SyntaxError:
        return set()
    names, funcs = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            funcs.add(node.func.id)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names - funcs


def find_formula_cycles(formulas: dict) -> list:
    """在「字段键 → 公式」里找循环依赖，返回 [[a, b, ...], ...]（每个环内按字母序）。

    自引用（a = a + 1）也会被识别为一个环。无环返回空列表。
    """
    graph = {
        key: {ref for ref in formula_references(formula) if ref in formulas}
        for key, formula in (formulas or {}).items()
    }

    # Tarjan 强连通分量
    index = {}
    low = {}
    stack = []
    on_stack = set()
    counter = [0]
    components = []

    def strongconnect(node):
        index[node] = low[node] = counter[0]
        counter[0] += 1
        stack.append(node)
        on_stack.add(node)
        for child in graph.get(node, ()):
            if child not in index:
                strongconnect(child)
                low[node] = min(low[node], low[child])
            elif child in on_stack:
                low[node] = min(low[node], index[child])
        if low[node] == index[node]:
            component = []
            while True:
                item = stack.pop()
                on_stack.discard(item)
                component.append(item)
                if item == node:
                    break
            components.append(component)

    for node in graph:
        if node not in index:
            strongconnect(node)

    cycles = []
    for component in components:
        if len(component) > 1:
            cycles.append(sorted(component))
        elif component and component[0] in graph.get(component[0], set()):
            cycles.append([component[0]])   # 自引用
    return sorted(cycles)


def cycle_members(formulas: dict) -> set:
    """处于循环依赖里的字段键集合。"""
    return {key for cycle in find_formula_cycles(formulas) for key in cycle}
