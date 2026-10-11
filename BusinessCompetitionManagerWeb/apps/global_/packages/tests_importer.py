"""导入报告契约测试：报告结构对齐《比赛包格式规范》§8。"""

from django.test import SimpleTestCase

from apps.global_.packages import importer


class ImporterContractTests(SimpleTestCase):
    def test_manifest_missing_file_reported(self):
        import tempfile
        from pathlib import Path
        from zipfile import ZIP_DEFLATED, ZipFile

        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / 'bad.zip'
            with ZipFile(zip_path, 'w', ZIP_DEFLATED) as zf:
                zf.writestr('manifest.yaml',
                            'packageVersion: "1.0"\nplugins:\n'
                            '  - file: plugins/contract_x.py\n    kind: CONTRACT\n    key: x\n')
            with self.assertRaises(importer.ImportFailure) as cm:
                importer.import_package(
                    competition=None, zip_path=zip_path, file_name='bad.zip', user=None)
            self.assertTrue(any('缺失' in e for e in cm.exception.report['errors']))

    def test_manifest_bad_version(self):
        import tempfile
        from pathlib import Path
        from zipfile import ZIP_DEFLATED, ZipFile

        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / 'bad.zip'
            with ZipFile(zip_path, 'w', ZIP_DEFLATED) as zf:
                zf.writestr('manifest.yaml', 'packageVersion: "2.0"\n')
            with self.assertRaises(importer.ImportFailure) as cm:
                importer.import_package(
                    competition=None, zip_path=zip_path, file_name='bad.zip', user=None)
            self.assertTrue(any('packageVersion' in e for e in cm.exception.report['errors']))
