"""角色权限矩阵（2026-11）：不新增角色，只配置「参赛代表 / 管理员」各自能看什么、能操作什么。

存储：``Competition.permissions``（全局库 JSON）形如 ``{"PLAYER": ["view.contracts", ...]}``；
缺省值 = 系统当前默认行为，未配置时不改变任何现有表现。系统超级管理员始终拥有全部能力。
"""

from apps.common.context import get_competition_id

# 能力目录（顺序即界面展示顺序）
CAPABILITIES = [
    {'key': 'view.companies', 'label': '查看公司信息（含字段表）', 'group': '查看'},
    {'key': 'view.contracts', 'label': '查看合同', 'group': '查看'},
    {'key': 'view.fieldlogs', 'label': '查看字段日志', 'group': '查看'},
    {'key': 'act.companies', 'label': '修改公司字段值', 'group': '操作'},
    {'key': 'act.contracts', 'label': '创建 / 提交 / 确认 / 终止合同', 'group': '操作'},
    {'key': 'act.contracts_modify', 'label': '申请修改合同 / 提交修改内容', 'group': '操作'},
]

CAPABILITY_KEYS = [item['key'] for item in CAPABILITIES]

ROLES = [
    {'key': 'PLAYER', 'label': '参赛代表'},
    {'key': 'ADMIN', 'label': '管理员（主席团）'},
]

# 默认 = 现有行为：两类角色都能看公司/合同，参赛代表能改本公司字段与做合同动作
DEFAULT_MATRIX = {
    'PLAYER': ['view.companies', 'view.contracts', 'act.companies',
               'act.contracts', 'act.contracts_modify'],
    'ADMIN': ['view.companies', 'view.contracts', 'act.companies',
              'act.contracts', 'act.contracts_modify'],
}


def _sanitize(matrix) -> dict:
    """清洗外部输入：只保留已知角色与已知能力。"""
    result = {}
    if not isinstance(matrix, dict):
        return result
    for role in DEFAULT_MATRIX:
        raw = matrix.get(role)
        if not isinstance(raw, list):
            continue
        result[role] = [key for key in CAPABILITY_KEYS if key in raw]
    return result


def get_matrix(competition) -> dict:
    """取比赛的有效权限矩阵（缺省用默认值补齐）。"""
    stored = _sanitize(getattr(competition, 'permissions', None) or {})
    matrix = {}
    for role, defaults in DEFAULT_MATRIX.items():
        matrix[role] = stored.get(role, list(defaults))
    return matrix


def role_of(user, competition_id=None):
    """用户在该比赛的身份键（PLAYER / ADMIN）；非成员返回 None。"""
    from apps.global_.memberships.models import CompetitionMembership

    competition_id = competition_id or get_competition_id()
    if not (user and user.is_authenticated and competition_id):
        return None
    membership = (
        CompetitionMembership.objects
        .filter(user=user, competition_id=competition_id, is_active=True)
        .first()
    )
    return membership.identity if membership is not None else None


def has_capability(user, capability: str, competition_id=None, matrix=None) -> bool:
    """判断用户在当前比赛是否具备某能力；系统超级管理员恒为 True。"""
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if capability not in CAPABILITY_KEYS:
        return False
    role = role_of(user, competition_id)
    if role is None:
        return False
    if matrix is None:
        from apps.global_.competitions.models import Competition

        competition_id = competition_id or get_competition_id()
        competition = Competition.objects.using('default').filter(pk=competition_id).first()
        if competition is None:
            return False
        matrix = get_matrix(competition)
    return capability in (matrix.get(role) or [])
