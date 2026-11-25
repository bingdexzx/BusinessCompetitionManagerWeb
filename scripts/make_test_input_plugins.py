"""生成「测试输入项」合同插件：每个插件只含一个输入项、apply 无效果。

用法：python scripts/make_test_input_plugins.py [--register <cid>]
不带 --register 只生成文件；带 cid 时同时登记 PluginRegistry + 比赛包关联。
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, 'BusinessCompetitionManagerWeb')
sys.path.insert(0, BACKEND)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')

# (slug, 中文名, 输入 type, itemLabel, 是否有数量字段)
LIST_ITEMS = [
    ('yuanliao', '原料清单', 'LIST:materials', '原料', True),
    ('lingjian', '零件清单', 'LIST:parts', '零件', True),
    ('chanpin', '产品清单', 'LIST:products', '产品', True),
    ('didian', '地点清单', 'LIST:map_nodes', '地点', False),
    ('chengshi', '城市清单', 'LIST:cities', '城市', False),
    ('zaiju', '载具清单', 'LIST:vehicles', '载具', True),
    ('gongsi', '公司清单', 'LIST:companies', '公司', False),
    ('quyu', '区域清单', 'LIST:regions', '区域', False),
    ('ranliao', '燃料清单', 'LIST:fuels', '燃料', True),
    ('kejishu', '科技树清单', 'LIST:tech_nodes', '科技树', False),
    ('jijian', '基建清单', 'LIST:infrastructures', '基建', True),
    ('cangku', '仓库清单', 'LIST:warehouses', '仓库', True),
    ('shengchanxian', '生产线清单', 'LIST:production_lines', '生产线', True),
]

REF_ITEMS = [
    ('ref_gongsi', '引用：公司', 'REF:companies'),
    ('ref_quyu', '引用：区域', 'REF:regions'),
    ('ref_chengshi', '引用：城市', 'REF:cities'),
    ('ref_didian', '引用：地点', 'REF:map_nodes'),
    ('ref_zaiju', '引用：载具', 'REF:vehicles'),
    ('ref_chanpin', '引用：产品', 'REF:products'),
    ('ref_lingjian', '引用：零件', 'REF:parts'),
    ('ref_yuanliao', '引用：原料', 'REF:materials'),
    ('ref_ranliao', '引用：燃料', 'REF:fuels'),
    ('ref_cangku', '引用：仓库', 'REF:warehouses'),
    ('ref_shengchanxian', '引用：生产线', 'REF:production_lines'),
    ('ref_jijian', '引用：基建', 'REF:infrastructures'),
    ('ref_kejishu', '引用：科技树', 'REF:tech_nodes'),
]

SCALAR_ITEMS = [
    ('shuzi', '数字输入', 'NUMBER'),
    ('wenben', '文本输入', 'TEXT'),
    ('buer', '开关输入', 'BOOLEAN'),
]


def schema_for(kind, label, item_label=None, with_quantity=False):
    if kind.startswith('LIST:'):
        entry = {
            'key': label,
            'label': label,
            'type': kind,
            'itemLabel': item_label or '条目',
            'optional': False,
        }
        entry['fields'] = (
            [{'key': 'quantity', 'label': '数量', 'type': 'NUMBER', 'min': 1}]
            if with_quantity else []
        )
        return [entry]
    if kind.startswith('REF:'):
        return [{'key': label, 'label': label, 'type': kind}]
    if kind == 'NUMBER':
        return [{'key': label, 'label': label, 'type': 'NUMBER', 'min': 0}]
    if kind == 'BOOLEAN':
        return [{'key': label, 'label': label, 'type': 'BOOLEAN'}]
    return [{'key': label, 'label': label, 'type': 'TEXT'}]


TEMPLATE = '''"""测试合同：仅一个输入项「{label}」（{kind}），用来验证输入项渲染与校验。

apply 返回空效果 —— 这张合同落账不修改任何字段，只用来试输入项。
"""

CONTRACT_KEY = '{key}'
CONTRACT_NAME = '测试输入项：{label}'

PARTY_ROLES = [{{'role': '买方', 'label': '买方'}}, {{'role': '卖方', 'label': '卖方'}}]

INPUT_SCHEMA = {schema}


def _rows(ctx):
    """读唯一输入项：清单返回行列表，其它原样返回（预览用，不落账）。"""
    key = INPUT_SCHEMA[0]['key']
    if str(INPUT_SCHEMA[0]['type']).startswith('LIST'):
        return ctx.input_list(key)
    return ctx.input(key)


def check(ctx):
    """只做基本非空校验（引擎已保证必填），不产生任何业务限制。"""
    return []


def apply(ctx):
    """无效果：只记录合同本身，不改库存、不改资金。"""
    return []
'''

FIELDS_SCHEMA_REPR = None


def render(slug, label, kind, item_label=None, with_quantity=False):
    key = f'testinput_{slug}'
    schema = schema_for(kind, label, item_label, with_quantity)
    import pprint

    schema_text = pprint.pformat(schema, width=100, sort_dicts=False)
    return key, TEMPLATE.format(key=key, label=label, kind=kind, schema=schema_text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--register', type=int, default=0, help='登记到哪个比赛（cid）')
    args = parser.parse_args()

    generated = []
    for slug, label, kind, item_label, with_quantity in LIST_ITEMS:
        key, source = render(slug, label, kind, item_label, with_quantity)
        generated.append((key, source, label))
    for slug, label, kind in REF_ITEMS:
        key, source = render(slug, label, kind)
        generated.append((key, source, label))
    for slug, label, kind in SCALAR_ITEMS:
        key, source = render(slug, label, kind)
        generated.append((key, source, label))

    import django

    django.setup()

    from django.core.files.storage import default_storage

    from apps.global_.packages.models import Package, PackagePlugin
    from apps.global_.plugins.models import PluginRegistry
    from plugins_runtime import loader

    registry_rows = []
    for key, source, display in generated:
        rel_dir = f'plugins/{key}/1.0.0'
        rel_path = f'{rel_dir}/contract_{key}.py'
        abs_dir = default_storage.path(rel_dir)
        os.makedirs(abs_dir, exist_ok=True)
        with open(default_storage.path(rel_path), 'w', encoding='utf-8') as fh:
            fh.write(source)

        module, problems = loader.load_plugin(default_storage.path(rel_path))
        assert not problems, (key, problems)
        assert not loader.validate_contract_plugin(module), (key, loader.validate_contract_plugin(module))
        assert module.apply(None) == []
        assert module.check(None) == []

        registry_rows.append(
            (key, display, rel_path, loader.sha256_file(default_storage.path(rel_path))))
    print(f'生成 {len(registry_rows)} 个测试插件')

    if not args.register:
        return

    package = (Package.objects.using('default')
               .filter(competition_id=args.register).order_by('-id').first())
    assert package is not None, f'比赛 {args.register} 没有比赛包，无法关联'
    for key, display, rel_path, sha in registry_rows:
        row, _ = PluginRegistry.objects.using('default').get_or_create(
            kind='CONTRACT', key=key, version='1.0.0', sha256=sha,
            defaults={
                'name': f'测试输入项：{display}',
                'file_name': f'contract_{key}.py',
                'file_path': rel_path,
                'audit_trail': [{'event': 'register', 'actor': 'agent',
                                 'detail': {'via': 'test-input-generator'}}],
            },
        )
        PackagePlugin.objects.using('default').get_or_create(
            package=package, plugin=row, kind='CONTRACT', key=key, version='1.0.0')
    print(f'已登记并关联到比赛 {args.register} 的比赛包 {package.pk}')


if __name__ == '__main__':
    main()
