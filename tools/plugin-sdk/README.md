# bcm-plugin-sdk —— 比赛包插件开发工具包

给**合同插件 / 产业插件**用的类型提示与开发辅助：`ctx` 补全、参数说明、`INPUT_SCHEMA` /
`PARTY_ROLES` / `FIELDS` 构造函数、插件源码静态校验。

> 只影响编辑器和开发期校验；插件运行时仍由引擎注入 `ctx` / `Effect`。

## 安装

```powershell
# 与后端同一个 Python 环境（部署脚本也会自动装）
uv pip install --python .venv\Scripts\python.exe -e tools/plugin-sdk
```

仓库根目录已带 `.vscode/settings.json` / `pyrightconfig.json`（`extraPaths` 指向
`tools/plugin-sdk`），VS Code 重新加载窗口即可识别。

## 1. 用构造函数写常量（推荐）

```python
from __future__ import annotations
from typing import TYPE_CHECKING

from bcm_plugin_sdk import (
    InputSchema, PartyRoles, number_field, list_field, list_sub_field, party_role,
)

if TYPE_CHECKING:
    from bcm_plugin_sdk import ContractContext, Effect

CONTRACT_KEY = "purchase"
CONTRACT_NAME = "采购合同"
NUMBER_PREFIX = "PO"

PARTY_ROLES: PartyRoles = [
    party_role("buyer", "买方"),
    party_role("seller", "卖方"),
    party_role("bank", "银行", optional=True),
]

INPUT_SCHEMA: InputSchema = [
    number_field("quantity", "数量", min=1),
    number_field("unitPrice", "单价", min=0),
    list_field(
        "materials", "原料清单", table="materials", item_label="原料", optional=True,
        fields=[list_sub_field("quantity", "数量", min=1)],
    ),
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
```

### 构造函数一览

| 函数 | 用途 | 关键参数 |
| --- | --- | --- |
| `number_field(key, label, min=None, max=None, optional=False)` | 数值输入（NUMBER） | `min/max` |
| `text_field(key, label, optional=False)` | 文本输入（TEXT） | — |
| `bool_field(key, label, optional=False)` | 开关（BOOLEAN） | — |
| `ref_field(key, label, table, optional=False)` | 可搜索下拉（REF:\<表\>） | `table` 只能是合法表名 |
| `list_field(key, label, table, item_label, fields=None, optional=False)` | 清单（LIST:\<表\>） | `fields=[]` 表示只登记条目 |
| `list_sub_field(key, label, min=0, max=None)` | 清单行内数量 | — |
| `party_role(role, label, optional=False)` | 参与方角色 | `role` 是 `ctx.party()` / `Effect` 的键 |
| `industry_field(key, name, table='entity', default=None, formula='', group='', timer_enabled=False, timer_trigger='FY_START')` | 产业字段 | `formula` 非空即由引擎重算 |

### 区域字段定义（`region-fields.json`）

```python
from bcm_plugin_sdk import (
    region_field, region_condition, region_fields_document,
)

doc = region_fields_document([
    region_field("market_capacity", "市场容量", "NUMBER", default=100,
                 condition=region_condition("license", True)),
    region_field("level", "等级", "TEXT", default="二线"),
])
# json.dump(doc, open("region-fields.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
```

- `type` 只能是 `NUMBER | TEXT | BOOL | DATE`；
- `condition` 可选：`source` 默认 `COMPANY`（公司实体字段），`REGION` 表示引用同区域其他字段；
- `op` 支持 `eq/ne/gt/gte/lt/lte/in`；`value` 必填；
- 条件含义：合同修改该区域字段时，只有满足条件才允许通过。

`table` 的合法值（`TableName` 字面量，编辑器会提示/拦截）：

```
materials parts products map_nodes cities vehicles companies regions
fuels tech_nodes infrastructures warehouses production_lines
```

## 2. 静态校验插件源码

不用起 Django、不用导入插件：

```powershell
python -m bcm_plugin_sdk check plugins/contract_purchase.py
python -m bcm_plugin_sdk check --all plugins/
```

会检查：

- 语法、禁止的 import/调用（`os/sys/subprocess/django/apps`、`eval/exec/open/getattr/__dunder__` 等）；
- 合同插件必须有的常量/函数：`CONTRACT_KEY/NAME/PARTY_ROLES/INPUT_SCHEMA` + `check(ctx)/apply(ctx)`；
- 产业插件必须有的 `INDUSTRY_KEY/NAME/FIELDS`；
- 角色重复、输入项 key 重复、`type` 是否合法、清单表名/子字段是否合法；
- `check/apply` 必须只有一个 `ctx` 参数。

也可以在代码里调用：

```python
from bcm_plugin_sdk import validate_source, validate_file
problems = validate_file(Path("plugins/contract_x.py"))
```

## 3. 示例

| 文件 | 内容 |
| --- | --- |
| [examples/contract_purchase.py](examples/contract_purchase.py) | 清单 + 价格 + Effect 完整合同 |
| [examples/industry_manufacture.py](examples/industry_manufacture.py) | 产业字段、公式、财年定时器 |

## 4. 类型/补全能力

- `ContractContext` / `IndustryContext`：运行时 API 的全部方法与参数说明（内置运行时副本，保证与真实签名一致）；
- `Effect`：构造参数 + `add / sub / set` 简写；
- `TableName` / `FieldType`：表名、输入项类型字面量；
- `InputField` / `PartyRole` / `IndustryFieldSpec`：required 键必填、可选键 `NotRequired`，写错键会报。

## 5. 运行时说明

- 构造函数（`number_field` 等）只返回 dict/list，**可以在插件运行时 import**；部署脚本会把
  `tools/plugin-sdk` 装进服务器 venv，因此插件可以安全使用；
- `Effect` 仍由引擎注入，**不要**在运行时 import `Effect`（放在 `TYPE_CHECKING` 里即可）；
- `ctx` 参数注解写成 `ContractContext` / `IndustryContext` 才有补全。

## 6. 常见问题

| 现象 | 处理 |
| --- | --- |
| Pylance 报 `无法解析导入 "bcm_plugin_sdk"` | 重新加载窗口；确认解释器是 `.venv`；或 `uv pip install -e tools/plugin-sdk`；仓库已配 `extraPaths` |
| `ctx.` 没有补全 | 给 `check/apply` 的 `ctx` 加 `ContractContext` 注解；确认 `TYPE_CHECKING` 导入 |
| `python -m bcm_plugin_sdk check` 报找不到模块 | 用项目 `.venv` 的 python 执行，或先安装 SDK |
| 运行时 `ModuleNotFoundError: bcm_plugin_sdk` | 插件在运行时 import 了 SDK，但服务器没装；部署脚本会自动装，手动环境执行上面的安装命令 |
| 构造函数报参数错误 | 看编辑器提示；`table` 只能用合法表名，`min/max` 是数字 |

## 维护

运行时 `plugins_runtime/api.py` 变化后：

```powershell
python tools/plugin-sdk/sync_runtime.py
python tools/plugin-sdk/check_sync.py
```
