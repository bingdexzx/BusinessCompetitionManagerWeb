# 比赛包工程工具

用于**创建、校验、打包**比赛包工程。不需要启动 Django，装好 `pyyaml` / `openpyxl` 即可
（项目 `.venv` 里已有）。

```bash
# 1) 创建工程脚手架（manifest + 示例合同/产业插件 + 两张 xlsx）
python tools/package-tools/package_tools.py init my_package

cd my_package
# 2) 校验（目录；直接传路径等价于 check）
python ../package-tools/package_tools.py check .
python ../package-tools/package_tools.py .

# 3) 重算 sha256 并打包 zip
python ../package-tools/package_tools.py build . --out ../my_package.zip

# 4) 校验最终 zip（含 zip-slip 检查）
python ../package-tools/package_tools.py check ../my_package.zip
```

## init 生成的结构

```
my_package/
├── manifest.yaml
├── plugins/
│   ├── contract_example.py     # 合同插件模板（可复制多份改 key）
│   └── industry_example.py     # 产业插件模板
├── dashboard.json              # 仪表盘布局（可选，init 会生成示例）
├── sheets/
│   ├── industries.xlsx         # industries + fields 两个工作表
│   └── contracts.xlsx
└── README.md
```

插件模板带 `TYPE_CHECKING` 的 `bcm_plugin_sdk` 类型注解，配合
[tools/plugin-sdk](../plugin-sdk/README.md) 可获得 `ctx.` 补全与参数说明。

## check 校验什么

**manifest**

- `packageVersion` 存在；
- `plugins` 每项含 `file/kind/key/sha256`，`kind ∈ CONTRACT/INDUSTRY`，`key` 不重复；
- `sheets` 每项文件存在、sha256 一致；
- 未列入 manifest 的 `plugins/*.py` 给出警告（导入不会生效）。

**插件源码**

- AST 扫描：禁止 import `os/sys/subprocess/shutil/pathlib/django/apps/plugins_runtime…`；
  禁止调用 `eval/exec/open/getattr/__import__…`；禁止 `__dunder__` 属性访问；
- 合同插件必须有 `CONTRACT_KEY / CONTRACT_NAME / PARTY_ROLES / INPUT_SCHEMA /
  check(ctx) / apply(ctx)`；
- 产业插件必须有 `INDUSTRY_KEY / INDUSTRY_NAME / FIELDS`；
- 常量里的 key 必须与 manifest 一致；
- 参与方角色不重复；输入项 key 不重复、`type` 合法（`NUMBER/TEXT/BOOLEAN/REF:* /LIST:*`）、
  清单表名合法、子字段合法。

**xlsx**

- `industries.xlsx`：必须有 `industries` 表及 `industryKey/name/pluginFile` 列，
  行里的 `industryKey` 必须对应 INDUSTRY 插件、`pluginFile` 必须存在；
- `contracts.xlsx`：必须有 `contractTypeKey/name/partiesJSON/inputsJSON` 列，
  `contractTypeKey` 必须对应 CONTRACT 插件；
- 可选 `dashboard.json` / `region-fields.json` 必须是合法 JSON。

**dashboard.json（可选）**

- `components[]`：`type ∈ number/gauge/table/text`，`title` 非空；
- 非 text 组件必须有 `bind.table(entity|finance)`、`bind.fieldKey`、`bind.aggregate(sum|latest|average)`；
- `industries.<产业key>.components` 的 key 必须对应 INDUSTRY 插件。

**zip**

- 解压前检查路径穿越（`../`、绝对路径）后再校验。

退出码：`0` 通过；`1` 有错误；`2` 缺少依赖。

## build

1. 按当前文件重算 `manifest.yaml` 里的 `sha256`；
2. 跑一遍 `check`；
3. 通过后打包为 zip（含 manifest 与全部文件）。

> 导入系统会校验 sha256，所以**改完插件/表格后必须重新 build**，否则导入会失败。

## 与插件 SDK 的关系

- 本工具负责**结构与格式**校验（不启动 Django）；
- [plugin-sdk](../plugin-sdk/README.md) 负责**编辑器类型提示**（`ctx` 方法、`Effect`、`INPUT_SCHEMA` 键补全）；
- 两者配合：写插件有补全，提交前用 `check` 卡住结构错误。
