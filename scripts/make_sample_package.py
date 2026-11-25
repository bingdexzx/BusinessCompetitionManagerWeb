"""生成示例比赛包（《比赛包格式规范》配套交付物）。

输出：dist/sample_competition_package.zip（含 manifest.yaml、dashboard.json、3 个插件、2 张表）

运行：.venv\\Scripts\\python.exe scripts\\make_sample_package.py [--out <目录>]
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import yaml

# ---------------------------------------------------------------- 插件源码

CONTRACT_PURCHASE = '''\
"""采购合同：买方向卖方购买产品（示例插件）。"""

CONTRACT_KEY = "purchase"
CONTRACT_NAME = "采购合同"
NUMBER_PREFIX = "PO"

PARTY_ROLES = [
    {"role": "buyer", "label": "买方"},
    {"role": "seller", "label": "卖方"},
    {"role": "bank", "label": "银行", "optional": True},
]

INPUT_SCHEMA = [
    {"key": "product", "label": "产品", "type": "REF:products"},
    {"key": "quantity", "label": "数量", "type": "NUMBER", "min": 1},
    {"key": "unitPrice", "label": "单价", "type": "NUMBER"},
]


def check(ctx):
    """前置检查：返回问题列表（空 = 通过）。保证创建即能执行。"""
    problems = []
    total = ctx.input("quantity") * ctx.input("unitPrice")
    if ctx.company_field("buyer", "cash", 0) < total:
        problems.append("买方资金不足")
    return problems


def apply(ctx):
    """字段修改：返回效果列表，由落账引擎写入并记审计。"""
    total = ctx.input("quantity") * ctx.input("unitPrice")
    return [
        Effect(company="buyer", field="cash", op="SUB", value=total),
        Effect(company="seller", field="cash", op="ADD", value=total),
        Effect(company="buyer", field="stock", op="ADD", value=ctx.input("quantity")),
    ]
'''

CONTRACT_LOAN = '''\
"""贷款合同：贷款方借款给借款方（示例插件）。"""

CONTRACT_KEY = "loan"
CONTRACT_NAME = "贷款合同"
NUMBER_PREFIX = "LN"

PARTY_ROLES = [
    {"role": "lender", "label": "贷款方"},
    {"role": "borrower", "label": "借款方"},
]

INPUT_SCHEMA = [
    {"key": "principal", "label": "本金", "type": "NUMBER", "min": 1},
    {"key": "rate", "label": "利率", "type": "NUMBER", "min": 0},
]


def check(ctx):
    problems = []
    if ctx.company_field("lender", "cash", 0) < ctx.input("principal"):
        problems.append("贷款方资金不足")
    return problems


def apply(ctx):
    principal = ctx.input("principal")
    return [
        Effect(company="lender", field="cash", op="SUB", value=principal),
        Effect(company="borrower", field="cash", op="ADD", value=principal),
        Effect(company="borrower", field="loan", op="ADD", value=principal),
    ]
'''

INDUSTRY_MANUFACTURER = '''\
"""制造业产业类型（示例插件）：定义字段、公式、数据类型、初始值。"""

INDUSTRY_KEY = "manufacturer"
INDUSTRY_NAME = "制造业"

FIELDS = [
    {"key": "cash", "name": "现金", "type": "NUMBER", "default": 100000, "table": "finance"},
    {"key": "capacity", "name": "产能", "type": "NUMBER", "default": 10, "table": "entity"},
    {"key": "loan_limit", "name": "贷款额度", "type": "NUMBER",
     "formula": "cash * 0.5", "table": "finance"},
]


def initial_values():
    return {"cash": 100000, "capacity": 10}


def recompute(company_fields):
    out = dict(company_fields)
    out["loan_limit"] = company_fields.get("cash", 0) * 0.5
    return out
'''

# ---------------------------------------------------------------- 表格数据

BASEDATA_SHEETS = {
    'fuels': {
        'headers': ['code', 'name', 'unit', 'energyValue', 'price', 'notes'],
        'rows': [
            ['F1', '柴油', '吨', 42.6, 7800, ''],
            ['F2', '汽油', '吨', 44.0, 8200, ''],
            ['F3', '电力', 'kWh', 3.6, 1.2, ''],
        ],
    },
    'warehouses': {
        'headers': ['code', 'name', 'capacity', 'regionCode', 'notes'],
        'rows': [
            ['W1', '中心仓', 5000, 'R1', ''],
            ['W2', '港口仓', 3000, 'R2', ''],
        ],
    },
    'vehicles': {
        'headers': ['code', 'name', 'vehicleType', 'loadCapacity', 'speed', 'fuelCode', 'fuelConsumption'],
        'rows': [
            ['V1', '重型卡车', 'truck', 30, 60, 'F1', 28],
            ['V2', '小型货车', 'van', 10, 80, 'F2', 12],
        ],
    },
    'maps': {
        'headers': ['code', 'name', 'regionType', 'adjacentCodes', 'distance'],
        'rows': [
            ['R1', '华东', 'plain', 'R2,R3', 300],
            ['R2', '华南', 'port', 'R1', 300],
            ['R3', '华北', 'plain', 'R1', 500],
        ],
    },
    'materials': {
        'headers': ['code', 'name', 'unit', 'basePrice'],
        'rows': [
            ['M1', '钢铁', '吨', 4200],
            ['M2', '塑料', '吨', 9000],
        ],
    },
    'products': {
        'headers': ['code', 'name', 'unit', 'basePrice'],
        'rows': [
            ['P1', '机床', '台', 85000],
            ['P2', '家电', '件', 2400],
        ],
    },
    'parts': {
        'headers': ['code', 'name', 'unit', 'basePrice', 'compatibleTypes'],
        'rows': [
            ['PT1', '发动机', '台', 12000, 'truck,van'],
            ['PT2', '轮胎', '条', 600, 'truck,van'],
        ],
    },
    'infrastructures': {
        'headers': ['code', 'name', 'infraType', 'buildCost', 'maintenanceCost', 'effect'],
        'rows': [
            ['I1', '厂房', 'factory', 2000000, 50000, json.dumps({'capacity': 5}, ensure_ascii=False)],
            ['I2', '码头', 'dock', 3000000, 80000, json.dumps({'logistics': 1}, ensure_ascii=False)],
        ],
    },
    'tech_tree': {
        'headers': ['code', 'name', 'tier', 'prerequisiteCodes', 'researchCost', 'effect'],
        'rows': [
            ['T1', '基础制造', 1, '', 100000, json.dumps({'efficiency': 0.05}, ensure_ascii=False)],
            ['T2', '精益制造', 2, 'T1', 300000, json.dumps({'efficiency': 0.1}, ensure_ascii=False)],
        ],
    },
    'production_lines': {
        'headers': ['code', 'name', 'inputs', 'outputs', 'capacity', 'buildCost'],
        'rows': [
            ['L1', '机床产线', json.dumps({'M1': 2}), json.dumps({'P1': 1}), 20, 500000],
            ['L2', '家电产线', json.dumps({'M2': 1}), json.dumps({'P2': 10}), 100, 300000],
        ],
    },
}


DASHBOARD = {
    'title': '经营看板',
    'components': [
        {'id': 'cash', 'type': 'number', 'title': '现金合计',
         'bind': {'table': 'finance', 'fieldKey': 'cash', 'aggregate': 'sum'}, 'suffix': '元'},
        {'id': 'capacity', 'type': 'number', 'title': '产能合计',
         'bind': {'table': 'entity', 'fieldKey': 'capacity', 'aggregate': 'sum'}},
        {'id': 'loan', 'type': 'table', 'title': '各公司贷款额度',
         'bind': {'table': 'finance', 'fieldKey': 'loan_limit', 'aggregate': 'latest'}},
        {'id': 'note', 'type': 'text', 'title': '说明', 'text': '示例仪表盘，可自行修改 dashboard.json'},
    ],
    'industries': {
        'manufacturer': {
            'title': '制造业',
            'components': [
                {'id': 'm_cash', 'type': 'number', 'title': '制造业现金',
                 'bind': {'table': 'finance', 'fieldKey': 'cash', 'aggregate': 'sum'}},
                {'id': 'm_capacity', 'type': 'gauge', 'title': '制造业产能',
                 'bind': {'table': 'entity', 'fieldKey': 'capacity',
                          'aggregate': 'latest', 'max': 100}},
            ],
        },
    },
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_xlsx(path: Path, headers, rows, extra_sheets=None):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = path.stem
    ws.append(headers)
    for row in rows:
        ws.append(row)
    for name, (h, r) in (extra_sheets or {}).items():
        ws2 = wb.create_sheet(name)
        ws2.append(h)
        for row in r:
            ws2.append(row)
    wb.save(path)


def build(out_dir: Path) -> Path:
    root = out_dir / 'sample_package'
    (root / 'plugins').mkdir(parents=True, exist_ok=True)
    (root / 'sheets').mkdir(parents=True, exist_ok=True)

    # 插件
    (root / 'plugins' / 'contract_purchase.py').write_text(CONTRACT_PURCHASE, encoding='utf-8')
    (root / 'plugins' / 'contract_loan.py').write_text(CONTRACT_LOAN, encoding='utf-8')
    (root / 'plugins' / 'industry_manufacturer.py').write_text(INDUSTRY_MANUFACTURER, encoding='utf-8')

    # 基础数据不再随比赛包提供（导入方式变更：改由系统「数据管理」页维护），
    # 示例包只含 产业信息（industries.xlsx）与 合同信息（contracts.xlsx）；
    # BASEDATA_SHEETS 定义保留作数据字典参考。

    # industries.xlsx（双工作表：industries + fields 对账）
    write_xlsx(
        root / 'sheets' / 'industries.xlsx',
        ['industryKey', 'name', 'pluginFile', 'description'],
        [['manufacturer', '制造业', 'plugins/industry_manufacturer.py', '示例制造业产业']],
        extra_sheets={'fields': (
            ['industryKey', 'fieldKey', 'name', 'type', 'defaultValue', 'formula',
             'table', 'isCalculated', 'timerEnabled', 'timerTrigger'],
            [
                ['manufacturer', 'cash', '现金', 'NUMBER', 100000, '', 'finance', 'FALSE', 'FALSE', ''],
                ['manufacturer', 'capacity', '产能', 'NUMBER', 10, '', 'entity', 'FALSE', 'FALSE', ''],
                ['manufacturer', 'loan_limit', '贷款额度', 'NUMBER', '', 'cash * 0.5',
                 'finance', 'TRUE', 'FALSE', ''],
            ],
        )},
    )

    # contracts.xlsx（合同实例）
    write_xlsx(
        root / 'sheets' / 'contracts.xlsx',
        ['contractTypeKey', 'name', 'partiesJSON', 'inputsJSON', 'fiscalYear', 'notes'],
        [
            ['purchase', '首笔钢材采购',
             json.dumps([{'role': 'buyer', 'companyName': '阿尔法公司'},
                         {'role': 'seller', 'companyName': '贝塔公司'}], ensure_ascii=False),
             json.dumps({'product': 'P1', 'quantity': 10, 'unitPrice': 5000}, ensure_ascii=False),
             '', '示例采购合同'],
            ['loan', '启动贷款',
             json.dumps([{'role': 'lender', 'companyName': '贝塔公司'},
                         {'role': 'borrower', 'companyName': '阿尔法公司'}], ensure_ascii=False),
             json.dumps({'principal': 500000, 'rate': 0.05}, ensure_ascii=False),
             '', '示例贷款合同'],
        ],
    )

    # 仪表盘布局（可选，但示例包带上）
    (root / 'dashboard.json').write_text(
        json.dumps(DASHBOARD, ensure_ascii=False, indent=2), encoding='utf-8')

    # manifest.yaml
    plugins = [
        ('plugins/contract_purchase.py', 'CONTRACT', 'purchase', '采购合同', '1.0.0'),
        ('plugins/contract_loan.py', 'CONTRACT', 'loan', '贷款合同', '1.0.0'),
        ('plugins/industry_manufacturer.py', 'INDUSTRY', 'manufacturer', '制造业', '1.0.0'),
    ]
    manifest = {
        'packageVersion': '1.0',
        'dashboard': 'dashboard.json',
        'competition': {
            'name': '2025 商业对抗赛（示例）',
            'coverImage': '',
            'staffingInfo': '主席团 5 人',
        },
        'plugins': [
            {'file': f, 'kind': k, 'key': key, 'name': name, 'version': ver,
             'sha256': sha256_file(root / f)}
            for f, k, key, name, ver in plugins
        ],
        'sheets': [
            {'file': f'sheets/{p.name}', 'sha256': sha256_file(p)}
            for p in sorted((root / 'sheets').glob('*.xlsx'))
        ],
    }
    (root / 'manifest.yaml').write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding='utf-8')

    # 打包
    zip_path = out_dir / 'sample_competition_package.zip'
    with ZipFile(zip_path, 'w', ZIP_DEFLATED) as zf:
        for p in sorted(root.rglob('*')):
            if p.is_file():
                zf.write(p, p.relative_to(root))
    print('已生成示例比赛包:', zip_path)
    return zip_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=str(Path(__file__).resolve().parent.parent / 'dist'))
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    build(out_dir)


if __name__ == '__main__':
    sys.exit(main())
