"""合同业务异常（独立模块，避免引擎/落账子模块相互导入）。"""


class ContractError(Exception):
    """业务错误（前置守卫不满足 / 检查不通过）。"""


class ContractPermissionError(ContractError):
    """权限不足（视图映射为 403）。"""


class CheckFailedError(ContractError):
    """检查不通过（用于区分其它业务错误，失败检查也要补记留痕）。"""
