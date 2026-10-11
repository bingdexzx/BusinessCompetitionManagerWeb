"""M1 单测：AST 护栏、插件接口校验、表格解析（§5.4、§8、《比赛包格式规范》）。"""

from django.test import SimpleTestCase

from apps.global_.packages import parsers
from plugins_runtime import ast_guard, loader


class AstGuardTests(SimpleTestCase):
    def test_clean_plugin_passes(self):
        src = (
            'CONTRACT_KEY = "x"\n'
            'def check(ctx):\n'
            '    return [str(ctx.input("a"))]\n'
        )
        self.assertEqual(ast_guard.scan(src), [])

    def test_banned_module_import(self):
        problems = ast_guard.scan('import os\n')
        self.assertTrue(any('禁止导入模块' in p for p in problems))

    def test_banned_call(self):
        problems = ast_guard.scan('def f():\n    return eval("1")\n')
        self.assertTrue(any('eval' in p for p in problems))

    def test_banned_attr(self):
        problems = ast_guard.scan('import subprocess\nsubprocess.run([])\n')
        self.assertTrue(problems)


class PluginValidationTests(SimpleTestCase):
    def test_contract_plugin_missing_elements(self):
        class M:
            CONTRACT_KEY = 'x'
        problems = loader.validate_contract_plugin(M())
        self.assertTrue(any('CONTRACT_NAME' in p for p in problems))
        self.assertTrue(any('check' in p for p in problems))

    def test_industry_plugin_bad_table(self):
        class M:
            INDUSTRY_KEY = 'x'
            INDUSTRY_NAME = 'X'
            FIELDS = [{'key': 'a', 'table': 'wrong'}]
        problems = loader.validate_industry_plugin(M())
        self.assertTrue(any('table' in p for p in problems))


class ParserTests(SimpleTestCase):
    def test_missing_required_column(self):
        entries, errors, warnings = parsers.parse_basedata_sheet('fuels', ['name'], [{'name': '柴油'}])
        self.assertTrue(any('缺少标准列' in e for e in errors))

    def test_duplicate_code_rejected(self):
        rows = [{'code': 'F1', 'name': 'a'}, {'code': 'F1', 'name': 'b'}]
        entries, errors, _ = parsers.parse_basedata_sheet('fuels', ['code', 'name'], rows)
        self.assertTrue(any('重复' in e for e in errors))
        self.assertEqual(len(entries), 1)

    def test_extra_columns_to_meta(self):
        rows = [{'code': 'F1', 'name': 'a', 'custom': 'x'}]
        entries, errors, warnings = parsers.parse_basedata_sheet(
            'fuels', ['code', 'name', 'custom'], rows)
        self.assertEqual(errors, [])
        self.assertTrue(any('扩展列' in w for w in warnings))
        self.assertEqual(entries[0]['meta'], {'custom': 'x'})

    def test_ref_check(self):
        entries = [{'code': 'V1', 'name': 'x', 'fuel_code': 'F9'}]
        errors = parsers.check_refs('vehicles', entries, {'fuels': {'F1'}})
        self.assertTrue(errors)

    def test_bad_json_column(self):
        rows = [{'code': 'L1', 'name': 'a', 'inputs': '{bad'}]
        entries, errors, _ = parsers.parse_basedata_sheet(
            'production_lines', ['code', 'name', 'inputs'], rows)
        self.assertTrue(any('JSON' in e for e in errors))
