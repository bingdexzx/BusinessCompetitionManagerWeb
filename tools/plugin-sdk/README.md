# bcm-plugin-sdk —— 比赛包插件开发提示库

给编写**合同类型插件 / 产业类型插件**用的类型提示包：装进开发环境后，编辑器里写
`ctx.` 会有**方法补全、参数签名与中文说明**；写 `INPUT_SCHEMA` / `PARTY_ROLES` 会补全键名；
`manifest.yaml` 有 JSON Schema 校验。

> 只影响编辑器/类型检查，**不改变插件运行方式**。运行时引擎仍然注入 `ctx` / `Effect`，
> 插件不需要（也不应该）在运行时 import 本 SDK。

## 安装（开发机）

```powershell
# 在后端用的同一个 Python 环境里安装（二选一）
uv pip install -e tools/plugin-sdk
pip install -e tools/plugin-sdk
```

或者不安装，把 `tools/plugin-sdk` 加进编辑器分析路径：

```jsonc
// .vscode/settings.json
{
  "python.analysis.extraPaths": ["tools/plugin-sdk"]
}
```

## 在插件里怎么用

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:          # 只在编辑器里生效；运行时不会 import
    from bcm_plugin_sdk import ContractContext, Effect, InputSchema, PartyRoles

PARTY_ROLES: PartyRoles = [
    {'role': '买方', 'label': '买方'},
]

INPUT_SCHEMA: InputSchema = [
    {'key': '数量', 'label': '数量', 'type': 'NUMBER', 'min': 1},
]

def check(ctx: ContractContext) -> list[str]:
    return [] if ctx.input_number('数量') > 0 else ['数量必须大于 0']

def apply(ctx: ContractContext) -> list[Effect]:
    amount = ctx.input_number('数量') * 100
    return [
        Effect.sub('买方', 'yinhangzhanghu', amount),
        Effect.add('卖方', 'yinhangzhanghu', amount),
    ]
```

要点：

1. `from __future__ import annotations`（或给注解加引号），避免运行时解析注解；
2. SDK 的 import 必须放在 `if TYPE_CHECKING:` 里，运行时不会执行；
3. 函数体里用的 `Effect` 由引擎注入为全局名，和普通插件写法完全一致；
4. `ctx` 注解写 `ContractContext` / `IndustryContext` 后，输入 `ctx.` 即可看到全部方法。

## 能补全什么

| 对象 | 内容 |
| --- | --- |
| `ContractContext` | `input*` / `party` / `company_field` / `item(s)` / `item_names` / `price(s)` / `price_names` / `node_region(s)` / `node_city(ies)` 等 31 个方法（含已弃用别名），每个都有参数与返回说明 |
| `IndustryContext` | 上述只读查询 + `basedata` / `number` |
| `Effect` | `Effect(company, field, op, value)` 与 `add / sub / set` 简写、`region` 说明 |
| `InputSchema` / `InputField` | 写 `INPUT_SCHEMA` 时补全 `key/label/type/optional/itemLabel/fields/min/max` |
| `PartyRoles` / `PartyRole` | 参与方角色结构 |
| `IndustryFieldSpec` | 产业 `FIELDS` 的 `key/name/type/table/default/formula/timerEnabled/timerTrigger` |

字段语义、公式白名单、清单类型（`LIST:materials` 等 13 类）、REF 下拉规则见
[docs/比赛包格式规范.md](../../docs/比赛包格式规范.md)。

## manifest.yaml 的校验/补全

在 `manifest.yaml` 第一行加：

```yaml
# yaml-language-server: $schema=../tools/plugin-sdk/bcm_plugin_sdk/schemas/manifest.schema.json
```

VS Code 安装 YAML 插件后即可校验 `packageVersion` / `plugins[]` / `sheets[]` 的必填与格式。
示例见 [templates/manifest.example.yaml](templates/manifest.example.yaml)。

合同 `INPUT_SCHEMA` 的 JSON Schema 在
`bcm_plugin_sdk/schemas/input-schema.schema.json`（供工具校验，不强制使用）。

## 模板

| 文件 | 用途 |
| --- | --- |
| [templates/contract_template.py](templates/contract_template.py) | 合同类型插件骨架（参与方/输入项/check/apply） |
| [templates/industry_template.py](templates/industry_template.py) | 产业类型插件骨架（FIELDS/timer_check） |
| [templates/manifest.example.yaml](templates/manifest.example.yaml) | 带 schema 引用的 manifest 示例 |

## 保持与运行时同步

SDK 内置运行时的 `api.py` / `ops.py` 副本（`bcm_plugin_sdk/_runtime/`），这样不装 Django
也能获得与真实签名一致的提示。运行时 API 改动后：

```powershell
python tools/plugin-sdk/sync_runtime.py   # 重新同步
python tools/plugin-sdk/check_sync.py    # 校验是否一致（CI 用，退出码 1 = 有漂移）
```

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `ctx.` 没有补全 | 确认 `ctx` 参数有注解、SDK 装在**当前解释器**（或配了 `extraPaths`）、已 `TYPE_CHECKING` 导入 |
| 运行时 `ModuleNotFoundError: bcm_plugin_sdk` | 说明 import 不在 `TYPE_CHECKING` 里；插件运行时不需要这个包 |
| 类型检查报 `Effect` 未定义（函数体内） | 确认 `if TYPE_CHECKING:` 块里有 `Effect`；运行时由引擎注入 |
| 补全的方法与最新代码不一致 | 跑 `sync_runtime.py` 重新同步 |
