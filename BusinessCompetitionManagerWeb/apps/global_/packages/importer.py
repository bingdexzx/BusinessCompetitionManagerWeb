"""比赛包导入编排（§9.2、《比赛包格式规范》§8）。

流程：解压 → manifest/SHA-256 校验 → AST 扫描插件 → 建库即迁移 → 产业字段迁移
→ 基础数据（数据管理）导入 → 合同实例导入 → 导入报告。
**公司数据不从比赛包导入**；公司由组队/分配产生。
失败策略：任一阶段出错 → 全局库/比赛库整体回滚（新建的比赛库直接删除），并持久化 FAILED 报告。"""

import json
import re
import tempfile

from datetime import datetime, timezone
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import yaml

from django.apps import apps as django_apps
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction

from apps.common import context as ctx
from apps.competition import provisioning
from apps.competition.contracts import services as contract_services
from apps.competition.industries import services as industry_services
from apps.global_.packages import parsers
from apps.global_.packages.models import Package, PackagePlugin
from apps.global_.plugins.models import PluginRegistry
from plugins_runtime import loader

from django.conf import settings

MAX_PACKAGE_BYTES = settings.PACKAGE_MAX_BYTES


class ImportFailure(Exception):
    def __init__(self, report):
        self.report = report
        super().__init__('；'.join(report.get('errors') or ['导入失败']))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load_manifest(root: Path) -> dict:
    path = root / 'manifest.yaml'
    if not path.exists():
        raise ImportFailure({'errors': ['缺少 manifest.yaml']})
    try:
        manifest = yaml.safe_load(path.read_text(encoding='utf-8'))
    except yaml.YAMLError as exc:
        raise ImportFailure({'errors': [f'manifest.yaml 解析失败：{exc}']})
    if not isinstance(manifest, dict):
        raise ImportFailure({'errors': ['manifest.yaml 格式错误']})
    return manifest


def _validate_manifest(manifest: dict, root: Path, report: dict):
    errors, warnings = report['errors'], report['warnings']

    version = str(manifest.get('packageVersion') or '')
    if not version.startswith('1'):
        errors.append(f'不支持的 packageVersion：{version or "(空)"}')

    declared = set()
    for entry in manifest.get('plugins') or []:
        file_rel = entry.get('file')
        if not file_rel:
            errors.append('plugins 清单存在无 file 的条目')
            continue
        declared.add(file_rel)
        path = root / file_rel
        if not path.exists():
            errors.append(f'插件文件缺失：{file_rel}')
            continue
        sha = loader.sha256_file(path)
        if entry.get('sha256') and entry['sha256'] != sha:
            errors.append(f'插件哈希不一致：{file_rel}')
        kind, fname = entry.get('kind'), Path(file_rel).name
        if kind == 'CONTRACT' and not fname.startswith('contract_'):
            errors.append(f'kind=CONTRACT 但文件名不符合 contract_ 前缀：{file_rel}')
        if kind == 'INDUSTRY' and not fname.startswith('industry_'):
            errors.append(f'kind=INDUSTRY 但文件名不符合 industry_ 前缀：{file_rel}')

    for entry in manifest.get('sheets') or []:
        file_rel = entry.get('file')
        if not file_rel:
            continue
        declared.add(file_rel)
        path = root / file_rel
        if not path.exists():
            errors.append(f'表格文件缺失：{file_rel}')
            continue
        if entry.get('sha256'):
            sha = loader.sha256_file(path)
            if entry['sha256'] != sha:
                errors.append(f'表格哈希不一致：{file_rel}')

    # dashboard.json（或 manifest.dashboard 指定名）是合法声明文件，先入 declared 以免被误报
    declared.add(str(manifest.get('dashboard') or 'dashboard.json'))
    # 区域字段定义文件（manifest.regionFields 可改名，默认 region-fields.json）
    declared.add(str(manifest.get('regionFields') or 'region-fields.json'))

    for path in root.rglob('*'):
        if path.is_file():
            rel = str(path.relative_to(root)).replace('\\', '/')
            if rel != 'manifest.yaml' and rel not in declared:
                warnings.append(f'未在 manifest 声明的文件：{rel}')


MAX_PACKAGE_FILES = settings.PACKAGE_MAX_FILES
MAX_PACKAGE_UNCOMPRESSED_BYTES = settings.PACKAGE_MAX_UNCOMPRESSED_BYTES   # 解压后上限（防 zip bomb）


def _extract_package(zip_path, dest: Path):
    try:
        with ZipFile(zip_path) as zf:
            members = zf.infolist()
            if len(members) > MAX_PACKAGE_FILES:
                raise ImportFailure(
                    {'errors': [f'压缩包文件过多（> {MAX_PACKAGE_FILES}）']})
            total = sum(max(0, member.file_size) for member in members)
            if total > MAX_PACKAGE_UNCOMPRESSED_BYTES:
                raise ImportFailure(
                    {'errors': [f'解压后体积过大（{total // 1024 // 1024}MB），上限 '
                                f'{MAX_PACKAGE_UNCOMPRESSED_BYTES // 1024 // 1024}MB']})
            root = dest.resolve()
            for member in members:
                target = (dest / member.filename).resolve()
                # 用 is_relative_to 而不是字符串前缀：避免 /a/b 与 /a/bc 的前缀绕过
                if not target.is_relative_to(root):
                    raise ImportFailure({'errors': [f'非法压缩包路径：{member.filename}']})
            zf.extractall(dest)
    except BadZipFile as exc:
        raise ImportFailure({'errors': [f'压缩包无法读取：{exc}']})


_DASHBOARD_TYPES = {'number', 'gauge', 'table', 'text'}
_DASHBOARD_AGGREGATES = {'sum', 'latest', 'average'}


def _validate_dashboard_component(where: str, comp, problems: list):
    if not isinstance(comp, dict):
        problems.append(f'{where} 必须是对象')
        return
    ctype = comp.get('type')
    if ctype not in _DASHBOARD_TYPES:
        problems.append(f'{where}.type 必须是 {"|".join(sorted(_DASHBOARD_TYPES))}')
    if not comp.get('title'):
        problems.append(f'{where}.title 不能为空')
    if ctype == 'text':
        return
    bind = comp.get('bind')
    if not isinstance(bind, dict):
        problems.append(f'{where}.bind 必须是对象（绑定产业字段）')
        return
    if bind.get('table') not in ('entity', 'finance'):
        problems.append(f'{where}.bind.table 必须是 entity|finance')
    if not bind.get('fieldKey'):
        problems.append(f'{where}.bind.fieldKey 不能为空')
    if bind.get('aggregate', 'latest') not in _DASHBOARD_AGGREGATES:
        problems.append(f'{where}.bind.aggregate 必须是 {"|".join(sorted(_DASHBOARD_AGGREGATES))}')


def _validate_dashboard_components(where: str, components, problems: list) -> list:
    if not isinstance(components, list):
        problems.append(f'{where} 必须是数组')
        return []
    for i, comp in enumerate(components):
        _validate_dashboard_component(f'{where}[{i}]', comp, problems)
    return components


def _load_dashboard(root: Path, manifest: dict, competition, report: dict):
    """仪表盘样式文件（可选，包根 `dashboard.json`，manifest 可用 `dashboard:` 指定文件名）。

    2026-10 决策：仪表盘**不再是自定义拖拽控件**，而是比赛包里的前端样式文件，组件直接绑定
    产业字段值。布局 v2 按产业分屏：``components`` 通用区（聚合全部可操作公司）、
    ``industries.<产业key>`` 产业专属页签（**只聚合该产业的公司**，``bind.fieldKey`` 即该产业
    插件 FIELDS 的字段键）。格式非法进 errors 阻断导入，缺失则 SKIPPED。"""
    rel = str(manifest.get('dashboard') or 'dashboard.json')
    path = root / rel
    report['dashboard'] = {'status': 'SKIPPED', 'file': rel, 'components': 0, 'industries': {}}
    if not path.exists():
        return
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:  # noqa: BLE001
        report['dashboard'].update(status='INVALID')
        report['errors'].append(f'{rel}：JSON 解析失败（{exc}），仪表盘未更新')
        return

    problems: list = []
    components = _validate_dashboard_components(
        f'{rel} components', doc.get('components') if isinstance(doc, dict) else None, problems)

    industries_doc = doc.get('industries') if isinstance(doc, dict) else None
    industries: dict = {}
    if industries_doc is not None and not isinstance(industries_doc, dict):
        problems.append(f'{rel} industries 必须是对象（产业key → 分区）')
        industries_doc = {}
    for key, section in (industries_doc or {}).items():
        where = f'{rel} industries.{key}'
        if not isinstance(section, dict):
            problems.append(f'{where} 必须是对象')
            continue
        ind_components = _validate_dashboard_components(
            f'{where}.components', section.get('components'), problems)
        industries[str(key)] = {
            'title': str(section.get('title') or ''),
            'components': ind_components,
        }

    if problems:
        report['dashboard'].update(status='INVALID')
        report['errors'] += [f'{p}' for p in problems]
        return

    competition.dashboard_layout = {
        'title': str(doc.get('title') or '仪表盘'),
        'components': components,
        'industries': industries,
    }
    competition.save(update_fields=['dashboard_layout', 'updated_at'])
    report['dashboard'].update(
        status='OK', components=len(components),
        industries={k: len(v['components']) for k, v in industries.items()})


def import_package(*, competition, zip_path, file_name, user):
    """执行完整导入；成功返回 Package，失败抛 ImportFailure（report 含问题清单）。"""
    report = {
        'status': 'FAILED', 'startedAt': _now(), 'finishedAt': None,
        'files': [], 'plugins': [], 'createdDatabase': None,
        'fieldMigrations': [], 'basedataRows': {}, 'contractsCreated': 0,
        'contractsSkipped': 0,
        'errors': [], 'warnings': [],
    }
    db_created_this_run = False
    try:
        if Path(zip_path).stat().st_size > MAX_PACKAGE_BYTES:
            raise ImportFailure({'errors': [f'包超过大小上限 {MAX_PACKAGE_BYTES // 1024 // 1024}MB']})

        with tempfile.TemporaryDirectory(prefix='gipfel_pkg_') as tmp:
            root = Path(tmp)
            _extract_package(zip_path, root)
            manifest = _load_manifest(root)
            _validate_manifest(manifest, root, report)
            if report['errors']:
                raise ImportFailure(report)

            plugins = _load_plugins(root, manifest, report, user)
            db_created_this_run = _provision_database(competition, report)
            _import_data(competition, root, plugins, report, user, manifest)
            _load_dashboard(root, manifest, competition, report)

        if report['errors']:
            # 后续阶段（dashboard 校验 / industries 字段对账等）追加了错误：
            # 即使主体数据已导入，也必须按失败处理（回滚新建库 + 落 FAILED 报告）
            raise ImportFailure(report)

        report['status'] = 'SUCCESS'
        report['finishedAt'] = _now()
        package = _persist_package(competition, zip_path, file_name, user, report,
                                   plugins, status=Package.Status.SUCCESS)
        return package

    except ImportFailure as exc:
        report.update({k: v for k, v in exc.report.items() if k in ('errors', 'warnings')})
        report['status'] = 'FAILED'
        report['finishedAt'] = _now()
        if competition is not None:
            if db_created_this_run and competition.db_name:
                _drop_database(competition.db_name)
                report['createdDatabase'] = f'{competition.db_name}（已回滚删除）'
            _persist_package(competition, zip_path, file_name, user, report,
                             {}, status=Package.Status.FAILED)
        raise

    except Exception as exc:  # noqa: BLE001 —— 兜底：任何未预期异常也按失败持久化，不吞异常
        report['errors'].append(f'未预期异常：{exc}')
        report['status'] = 'FAILED'
        report['finishedAt'] = _now()
        if competition is not None:
            if db_created_this_run and competition.db_name:
                _drop_database(competition.db_name)
                report['createdDatabase'] = f'{competition.db_name}（已回滚删除）'
            _persist_package(competition, zip_path, file_name, user, report,
                             {}, status=Package.Status.FAILED)
        raise


def _load_plugins(root: Path, manifest: dict, report: dict, user) -> dict:
    """AST 扫描 + 接口校验 + 注册不可变版本（全局库事务）。"""
    plugins = {}
    with transaction.atomic():
        for entry in manifest.get('plugins') or []:
            file_rel = entry.get('file')
            path = root / file_rel
            if not path.exists():
                continue  # manifest 校验已报错

            module, problems = loader.load_plugin(path)
            kind = entry.get('kind')
            if not problems:
                if kind == 'CONTRACT':
                    problems = loader.validate_contract_plugin(module)
                    key = getattr(module, 'CONTRACT_KEY', '')
                    prefix = getattr(module, 'NUMBER_PREFIX', key[:2].upper() if key else '')
                else:
                    problems = loader.validate_industry_plugin(module)
                    key = getattr(module, 'INDUSTRY_KEY', '')
                    prefix = ''
            if problems:
                report['errors'] += [f'{file_rel}：{p}' for p in problems]
                continue
            if key != entry.get('key'):
                report['errors'].append(
                    f'{file_rel}：manifest key({entry.get("key")}) 与插件 {key} 不一致')
                continue

            sha = loader.sha256_file(path)
            version = str(entry.get('version') or '1.0.0')
            # 中文显示名：manifest.name → 插件自带的 INDUSTRY_NAME/CONTRACT_NAME → key（兜底，界面上才会显示英文）
            module_name = getattr(
                module, 'INDUSTRY_NAME' if kind == 'INDUSTRY' else 'CONTRACT_NAME', '')
            display_name = (
                str(entry.get('name') or '').strip()
                or str(module_name or '').strip()
                or key
            )
            if not str(entry.get('name') or '').strip():
                report['warnings'].append(
                    f'{file_rel}：manifest 未声明插件中文名 name，已回退为「{display_name}」')
            stored = _store_plugin_file(path, key, version)
            registry, _ = PluginRegistry.objects.get_or_create(
                kind=kind, key=key, version=version, sha256=sha,
                defaults={
                    'name': display_name,
                    'file_name': Path(file_rel).name,
                    'file_path': stored,
                    'number_prefix': prefix,
                    'uploaded_by': getattr(user, 'id', None),
                    'uploaded_by_username': getattr(user, 'username', ''),
                    'audit_trail': [{'event': 'UPLOAD', 'actor': getattr(user, 'username', ''),
                                     'detail': {'file': file_rel, 'sha256': sha}}],
                },
            )
            plugins[key] = {'module': module, 'version': version, 'kind': kind,
                            'registry': registry, 'file': file_rel, 'name': display_name}
            report['plugins'].append({'file': file_rel, 'key': key, 'kind': kind,
                                      'name': display_name,
                                      'version': version, 'sha256': sha})
        if report['errors']:
            raise ImportFailure(report)
    return plugins


def _provision_database(competition, report: dict) -> bool:
    db_name = competition.db_name
    db_existed = provisioning.database_exists(db_name)
    provisioning.create_competition_database(db_name)
    report['createdDatabase'] = db_name if not db_existed else f'{db_name}（已存在，仅补迁移）'
    return not db_existed


def _drop_database(db_name: str):
    from django.db import connections

    import psycopg2

    connections.close_all()
    cfg = settings.DATABASES['default']
    conn = psycopg2.connect(dbname='postgres', user=cfg['USER'], password=cfg['PASSWORD'],
                            host=cfg['HOST'] or 'localhost', port=cfg['PORT'] or '5432')
    try:
        conn.autocommit = True
        conn.cursor().execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    finally:
        conn.close()


def _import_data(competition, root: Path, plugins: dict, report: dict, user, manifest: dict):
    alias = provisioning.ensure_competition_db(competition.db_name)
    ctx.set_competition_context(competition.id, alias)
    try:
        with transaction.atomic(using=alias):
            # 产业字段迁移（§8.2）
            industry_modules = {k: v for k, v in plugins.items() if v['kind'] == 'INDUSTRY'}
            for key, entry in industry_modules.items():
                stats = industry_services.apply_industry_fields(
                    entry['module'].FIELDS, plugin_key=key,
                    plugin_version=entry['version'], operator=user,
                )
                # 报告里带上中文产业名，前端不必再显示 manufacturer 这类 key
                stats['industryName'] = entry.get('name') or key
                report['fieldMigrations'].append(stats)
                for cycle in stats.get('formulaCycles') or []:
                    path_text = ' → '.join(list(cycle) + [cycle[0]])
                    report['warnings'].append(
                        f'{stats["industryName"]}：公式循环 {path_text}，已拒绝计算'
                        '（这些字段不会参与重算，请修正公式后重新导入）')

            # industries.xlsx 对账（规范 §6）
            _import_industries_sheet(root, industry_modules, report)

            # 区域字段定义（比赛包 region-fields.json）
            _import_region_fields(root, manifest, report)

            # 基础数据（数据管理）导入：fuels/warehouses/vehicles/materials/...
            _import_basedata(root, report)

            # 合同实例导入（规范 §7）
            contract_modules = {k: {'module': v['module'], 'version': v['version']}
                                for k, v in plugins.items() if v['kind'] == 'CONTRACT'}
            contracts_path = _find_sheet(root, 'contracts')
            if contracts_path and contract_modules:
                headers, rows = parsers.read_table(contracts_path)
                stats = contract_services.import_contract_instances(
                    rows, contract_modules, user=user)
                report['contractsCreated'] = stats['created']
                # 重导入去重：同一条合同已存在 → 跳过，不产生重复合同
                report['contractsSkipped'] = stats['skipped']
                report['errors'] += [f'contracts：{e}' for e in stats['errors']]
                report['warnings'] += stats['skipNotes']
                if stats['errors']:
                    raise ImportFailure(report)
    finally:
        ctx.clear_request_context()


MAX_ROWS_PER_SHEET = 50_000


def _normalize_entry(model, entry: dict) -> dict:
    """空单元格 → 文本列 '' / JSON 列删除；其余字段保持 None。"""
    from django.db import models as dj_models

    for field in model._meta.fields:
        if field.name not in entry or entry[field.name] is not None:
            continue
        if isinstance(field, (dj_models.CharField, dj_models.TextField)):
            entry[field.name] = ''
        elif isinstance(field, dj_models.JSONField):
            del entry[field.name]
    return entry


def _import_basedata(root: Path, report: dict) -> None:
    """把包内基础数据表导入「数据管理」（按 code update_or_create）。"""
    all_entries: dict[str, list] = {}
    all_codes: dict[str, set] = {}
    for sheet_key in parsers.BASEDATA_SPECS:
        path = _find_sheet(root, sheet_key)
        if path is None:
            continue
        headers, rows = parsers.read_table(path)
        if len(rows) > MAX_ROWS_PER_SHEET:
            report['errors'].append(f'{sheet_key}：行数超过上限 {MAX_ROWS_PER_SHEET}')
            continue
        entries, errors, warnings = parsers.parse_basedata_sheet(sheet_key, headers, rows)
        report['errors'] += [f'{sheet_key}：{e}' for e in errors]
        report['warnings'] += [f'{sheet_key}：{w}' for w in warnings]
        all_entries[sheet_key] = entries
        all_codes[sheet_key] = {entry['code'] for entry in entries}

    for sheet_key, entries in all_entries.items():
        report['errors'] += [f'{sheet_key}：{e}' for e in
                             parsers.check_refs(sheet_key, entries, all_codes)]
    if report['errors']:
        raise ImportFailure(report)

    for sheet_key, entries in all_entries.items():
        app_label, model_name = parsers.BASEDATA_SPECS[sheet_key]['model']
        model = django_apps.get_model(app_label, model_name)
        for entry in entries:
            code = entry.pop('code')
            model.objects.update_or_create(
                code=code, defaults=_normalize_entry(model, entry))
        report['basedataRows'][sheet_key] = len(entries)
        report['files'].append({
            'file': f'sheets/{sheet_key}', 'stage': 'basedata',
            'rows': len(entries), 'errors': [], 'warnings': [],
        })


def _find_sheet(root: Path, sheet_key: str):
    for ext in ('.xlsx', '.csv'):
        for prefix in ('sheets/', ''):
            path = root / f'{prefix}{sheet_key}{ext}'
            if path.exists():
                return path
    return None


def _import_industries_sheet(root: Path, industry_modules: dict, report: dict):
    path = _find_sheet(root, 'industries')
    if path is None:
        return
    headers, rows = parsers.read_table(path)
    known = {str(r.get('industryKey') or r.get('industrykey') or '').strip() for r in rows}
    for key in known - set(industry_modules):
        if key:
            report['warnings'].append(f'industries：表格声明的产业 {key} 没有对应插件')

    # fields 工作表对账：插件 FIELDS 为准，不一致报错误（规范 §6 / 待确认 #1）
    if path.suffix.lower() != '.xlsx':
        return
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    if 'fields' not in wb.sheetnames:
        wb.close()
        return
    ws = wb['fields']
    raw = list(ws.iter_rows(values_only=True))
    wb.close()
    if not raw:
        return
    f_headers = [str(h).strip().lower() if h else '' for h in raw[0]]
    for line in raw[1:]:
        row = {f_headers[i]: line[i] for i in range(min(len(f_headers), len(line)))}
        key = str(row.get('industrykey') or '').strip()
        field_key = str(row.get('fieldkey') or '').strip()
        entry = industry_modules.get(key)
        if not entry or not field_key:
            continue
        spec = next((f for f in entry['module'].FIELDS if f.get('key') == field_key), None)
        if spec is None:
            report['errors'].append(f'industries!fields：{key}.{field_key} 在插件 FIELDS 中不存在')
        elif row.get('formula') and str(row['formula']) != str(spec.get('formula') or ''):
            report['errors'].append(f'industries!fields：{key}.{field_key} 公式与插件不一致')


REGION_FIELD_KEY_RE = re.compile(r'^[A-Za-z0-9_]{1,64}$')
REGION_FIELD_TYPES = {'NUMBER', 'TEXT', 'BOOL', 'DATE'}


def _import_region_fields(root: Path, manifest: dict, report: dict):
    """比赛包区域字段定义（默认 region-fields.json，manifest.regionFields 可改名）。

    结构：``{"fields": [{"key","name","type","default","condition"}]}``；
    定义是比赛级（所有区域共用），值按区域存。重导入时以包为准：更新/新增，包中移除的定义删除。
    """
    rel = str(manifest.get('regionFields') or 'region-fields.json')
    report['regionFields'] = {'status': 'SKIPPED', 'file': rel, 'count': 0}
    path = root / rel
    if not path.exists():
        return
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:  # noqa: BLE001
        report['regionFields'].update(status='INVALID')
        report['errors'].append(f'{rel}：JSON 解析失败（{exc}）')
        return

    specs = doc.get('fields') if isinstance(doc, dict) else doc
    if not isinstance(specs, list):
        report['errors'].append(f'{rel}：fields 必须是数组')
        report['regionFields'].update(status='INVALID')
        return

    from apps.competition.regions.models import RegionField, RegionFieldValue
    from apps.competition.regions.services import validate_condition

    cleaned, seen, problems = [], set(), []
    for index, spec in enumerate(specs):
        where = f'{rel} fields[{index}]'
        if not isinstance(spec, dict):
            problems.append(f'{where} 必须是对象')
            continue
        key = str(spec.get('key') or '').strip()
        if not REGION_FIELD_KEY_RE.match(key):
            problems.append(f'{where}.key 只能包含字母/数字/下划线（1-64）')
            continue
        if key in seen:
            problems.append(f'{where}.key 重复：{key}')
            continue
        seen.add(key)
        name = str(spec.get('name') or '').strip()
        if not name:
            problems.append(f'{where}.name 不能为空')
            continue
        field_type = str(spec.get('type') or spec.get('fieldType') or 'NUMBER').upper()
        if field_type not in REGION_FIELD_TYPES:
            problems.append(f'{where}.type 必须是 {"|".join(sorted(REGION_FIELD_TYPES))}')
            continue
        condition, error = validate_condition(spec.get('condition'))
        if error:
            problems.append(f'{where}：{error}')
            continue
        cleaned.append({
            'key': key,
            'name': name,
            'field_type': field_type,
            'default_value': spec.get('default', spec.get('defaultValue')),
            'condition': condition,
        })

    if problems:
        report['errors'] += problems
        report['regionFields'].update(status='INVALID')
        return

    keys = {spec['key'] for spec in cleaned}
    for spec in cleaned:
        RegionField.objects.update_or_create(
            field_key=spec['key'],
            defaults={k: v for k, v in spec.items() if k != 'key'},
        )
    stale = RegionField.objects.exclude(field_key__in=keys)
    if stale.exists():
        stale_keys = list(stale.values_list('field_key', flat=True))
        stale.delete()
        RegionFieldValue.objects.filter(field_key__in=stale_keys).delete()
    report['regionFields'].update(status='OK', count=len(cleaned))


def _store_plugin_file(path: Path, key: str, version: str) -> str:
    rel = f'plugins/{key}/{version}/{path.name}'
    return default_storage.save(rel, ContentFile(path.read_bytes()))


def _persist_package(competition, zip_path, file_name, user, report, plugins, status):
    sha = loader.sha256_file(zip_path)
    stored = default_storage.save(
        f'packages/{competition.id}/{file_name}', ContentFile(Path(zip_path).read_bytes()))
    package = Package.objects.create(
        competition=competition, file_name=file_name, file_path=stored, sha256=sha,
        status=status, import_report=report,
        created_by=getattr(user, 'id', None),
        created_by_username=getattr(user, 'username', ''),
    )
    for key, entry in plugins.items():
        PackagePlugin.objects.create(
            package=package, plugin=entry['registry'], kind=entry['kind'],
            key=key, version=entry['version'],
        )
    if status == Package.Status.SUCCESS and competition.status == competition.Status.CREATED:
        competition.transition_to(competition.Status.PACKAGE_IMPORTED)
    return package
