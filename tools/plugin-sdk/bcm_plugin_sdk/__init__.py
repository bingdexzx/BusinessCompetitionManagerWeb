"""bcm-plugin-sdk：编写比赛包插件时的类型提示包（运行时无依赖）。

作用（只影响编辑器/静态检查，不改变插件运行方式）：
- 给 ``ctx`` 参数补全：``ContractContext`` / ``IndustryContext`` 的全部方法与参数说明；
- ``Effect`` 的签名与 ``add/sub/set`` 简写；
- ``INPUT_SCHEMA`` / ``PARTY_ROLES`` 用 TypedDict，写字典时能补全键名；
- 附 JSON Schema，VS Code/Cursor 里编辑 ``manifest.yaml`` 可校验/补全。
"""

from ._runtime.api import ContractContext, Effect, IndustryContext
from .schema import (
    IndustryFieldSpec,
    InputField,
    InputSchema,
    ListSubField,
    PartyRole,
    PartyRoles,
)

__all__ = [
    'ContractContext',
    'Effect',
    'IndustryContext',
    'InputField',
    'InputSchema',
    'ListSubField',
    'PartyRole',
    'PartyRoles',
    'IndustryFieldSpec',
]

__version__ = '1.0.0'
