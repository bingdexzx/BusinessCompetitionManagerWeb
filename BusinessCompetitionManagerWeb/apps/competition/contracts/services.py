"""合同类型暴露与合同实例导入（§9.2）；重导入按「类型+名称+参与方+输入」指纹幂等去重。"""

import json

from apps.competition.companies.models import Company
from apps.competition.contracts.fingerprint import contract_fingerprint
from apps.competition.contracts.models import Contract
from apps.global_.packages.models import PackagePlugin
from plugins_runtime import loader

__all__ = ['contract_fingerprint', 'import_contract_instances']


def _plugin_abs_path(file_path: str) -> str:
    from django.core.files.storage import default_storage
    return default_storage.path(file_path)


def _contract_registry(competition, contract_type_key, plugin_version=None):
    qs = (
        PackagePlugin.objects
        .filter(package__competition=competition, kind='CONTRACT', key=contract_type_key)
        .select_related('plugin')
        .order_by('-id')
    )
    if plugin_version:
        qs = qs.filter(version=plugin_version)
    return qs.first()


def contract_module_for(contract_type_key: str, plugin_version: str = ''):
    """按 (类型, 版本) 加载合同插件模块（§5.4 合同实例锁定执行时的插件版本）。"""
    from apps.common.context import get_competition_id
    from apps.global_.competitions.models import Competition

    competition = Competition.objects.get(pk=get_competition_id())
    link = _contract_registry(competition, contract_type_key, plugin_version)
    if link is None:
        raise ValueError(f'未注册的合同类型：{contract_type_key} {plugin_version}')
    module, problems = loader.load_plugin(_plugin_abs_path(link.plugin.file_path))
    if problems:
        raise ValueError('插件加载失败：' + '；'.join(problems))
    return module


def contract_number_prefix(contract_type_key: str) -> str:
    """合同类别前缀（D13 / §18 跟进 #3：随比赛包合同类型插件清单定稿）。"""
    from apps.common.context import get_competition_id
    from apps.global_.competitions.models import Competition

    competition = Competition.objects.get(pk=get_competition_id())
    link = _contract_registry(competition, contract_type_key)
    if link is not None and link.plugin.number_prefix:
        return link.plugin.number_prefix
    return contract_type_key[:2].upper()


def contract_types_for_competition(competition) -> list:
    links = (
        PackagePlugin.objects
        .filter(package__competition=competition, kind='CONTRACT')
        .select_related('plugin')
        .order_by('key', '-id')
    )
    seen, out = set(), []
    for link in links:
        if link.key in seen:
            continue
        seen.add(link.key)
        module, problems = loader.load_plugin(_plugin_abs_path(link.plugin.file_path))
        if problems:
            out.append({'key': link.key, 'name': link.key, 'version': link.version,
                        'errors': problems})
            continue
        out.append({
            'key': module.CONTRACT_KEY,
            'name': module.CONTRACT_NAME,
            'version': link.version,
            'numberPrefix': getattr(module, 'NUMBER_PREFIX', module.CONTRACT_KEY[:2].upper()),
            'partyRoles': module.PARTY_ROLES,
            'inputSchema': module.INPUT_SCHEMA,
        })
    return out


def _resolve_company(name: str, created_by: int) -> Company:
    name = str(name).strip()
    company, created = Company.objects.get_or_create(name=name, defaults={'industry_key': ''})
    return company


def import_contract_instances(rows, contract_modules, *, user=None):
    """导入合同实例（草稿态）。rows 为 contracts.xlsx 解析行。

    幂等：按合同指纹（类型+名称+参与方+输入）跳过已存在的合同——同一份包内的重复行，
    以及此前导入过（哪怕已软删除）的同一条，避免重导入产生重复合同。
    """
    errors, created, skipped, skip_notes = [], 0, 0, []
    seen_in_run: set[str] = set()
    for i, row in enumerate(rows, start=2):
        type_key = str(row.get('contractTypeKey') or row.get('contracttypekey') or '').strip()
        entry = contract_modules.get(type_key)
        if entry is None:
            errors.append(f'第 {i} 行：未知合同类型 {type_key}')
            continue
        module = entry['module']

        parties_raw = row.get('partiesJSON') or row.get('partiesjson') or '[]'
        inputs_raw = row.get('inputsJSON') or row.get('inputsjson') or '{}'
        try:
            parties = json.loads(parties_raw) if isinstance(parties_raw, str) else parties_raw
            inputs = json.loads(inputs_raw) if isinstance(inputs_raw, str) else inputs_raw
        except (TypeError, ValueError) as exc:
            errors.append(f'第 {i} 行：JSON 解析失败（{exc}）')
            continue

        known_roles = {p['role'] for p in module.PARTY_ROLES}
        known_inputs = {s['key'] for s in module.INPUT_SCHEMA}
        row_errors = []
        party_entries = []
        for order, p in enumerate(parties or []):
            role = p.get('role')
            if role not in known_roles:
                row_errors.append(f'未知参与方角色 {role}')
                continue
            company_name = p.get('companyName') or p.get('company') or ''
            company = _resolve_company(company_name, getattr(user, 'id', None))
            party_entries.append({'role': role, 'companyId': company.id,
                                  'companyName': company.name, 'confirmOrder': order})
        bad_inputs = [k for k in (inputs or {}) if k not in known_inputs]
        if bad_inputs:
            row_errors.append(f'未知输入项：{", ".join(bad_inputs)}')

        if row_errors:
            errors.append(f'第 {i} 行：' + '；'.join(row_errors))
            continue

        name = str(row.get('name') or '')[:200]
        fingerprint = contract_fingerprint(type_key, name, party_entries, inputs or {})
        if fingerprint in seen_in_run or Contract.objects.filter(
                import_fingerprint=fingerprint).exists():
            skipped += 1
            skip_notes.append(
                f'contracts：第 {i} 行「{name or type_key}」已存在（重导入去重），已跳过')
            continue
        seen_in_run.add(fingerprint)

        fiscal_year_no = row.get('fiscalYear') or row.get('fiscalyear')
        fiscal_year = None
        if fiscal_year_no not in (None, ''):
            from apps.competition.fiscal.models import FiscalYear
            fiscal_year = FiscalYear.objects.filter(year=int(fiscal_year_no)).first()

        Contract.objects.create(
            contract_type_key=type_key,
            plugin_version=entry.get('version', ''),
            name=name,
            status=Contract.Status.DRAFT,
            parties=party_entries,
            inputs=inputs or {},
            fiscal_year=fiscal_year,
            is_backfill=False,
            import_fingerprint=fingerprint,
            created_by=getattr(user, 'id', 0) or 0,
        )
        created += 1
    return {'created': created, 'skipped': skipped, 'errors': errors,
            'skipNotes': skip_notes}
