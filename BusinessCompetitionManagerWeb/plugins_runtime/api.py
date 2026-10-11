"""插件可见的受控 API（§8：插件只拿 ctx，不暴露 Django ORM）。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Effect:
    """落账效果（§7.2）：company=参与方角色或公司标识，op ∈ ADD/SUB/SET。"""

    company: str
    field: str
    op: str
    value: Any

    def __post_init__(self):
        if self.op not in ('ADD', 'SUB', 'SET'):
            raise ValueError(f'非法效果操作：{self.op}')


class ContractContext:
    """合同插件执行上下文（M1 定义接口，M3 满实现数据读写）。"""

    def __init__(self, parties=None, inputs=None, fields=None, basedata=None):
        self._parties = parties or {}
        self._inputs = inputs or {}
        self._fields = fields or {}
        self._basedata = basedata or {}

    def party(self, role: str) -> str:
        return self._parties.get(role)

    def company_field(self, role: str, field: str, default=0):
        return self._fields.get((role, field), default)

    def input(self, key: str, default=None):
        return self._inputs.get(key, default)

    def basedata(self, table: str, code: str):
        return self._basedata.get((table, code))


class IndustryContext:
    """产业插件上下文（M1 定义接口）。"""

    def __init__(self, fields=None):
        self._fields = fields or {}

    def field(self, key: str, default=None):
        return self._fields.get(key, default)
