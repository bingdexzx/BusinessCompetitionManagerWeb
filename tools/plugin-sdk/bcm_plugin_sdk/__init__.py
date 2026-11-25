"""bcm-plugin-sdk：编写比赛包插件时的类型提示与开发辅助（运行时不依赖）。

提供：
- ``ContractContext`` / ``IndustryContext`` / ``Effect``：ctx 方法、参数说明与补全；
- ``INPUT_SCHEMA`` / ``PARTY_ROLES`` / ``FIELDS`` 的类型与**构造函数**（自动补全、少写错）；
- ``validate_source`` / ``validate_file``：静态校验插件源码，终端可直接跑；
- ``TableName`` / ``FieldType``：表名、输入类型的字面量约束。

插件里推荐写法：

    from __future__ import annotations
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from bcm_plugin_sdk import ContractContext, Effect, InputSchema, PartyRoles
        from bcm_plugin_sdk import number_field, list_field, party_role

或者直接用构造函数的运行时导入（它们只返回 dict/list，不依赖 Django）：

    from bcm_plugin_sdk import InputSchema, number_field

校验：

    python -m bcm_plugin_sdk check plugins/contract_x.py
"""

from ._runtime.api import ContractContext, Effect, IndustryContext
from .regions import (
    ConditionOp,
    ConditionSource,
    RegionCondition,
    RegionFieldSpec,
    RegionFieldType,
    RegionFieldsDocument,
    region_condition,
    region_field,
    region_fields_document,
)
from .schema import (
    FieldType,
    IndustryFieldSpec,
    InputField,
    InputSchema,
    ListSubField,
    PartyRole,
    PartyRoles,
    TableName,
    bool_field,
    industry_bool_field,
    industry_field,
    industry_number_field,
    industry_text_field,
    list_field,
    list_sub_field,
    number_field,
    party_role,
    ref_field,
    text_field,
)
from .validate import validate_file, validate_source

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
    'TableName',
    'FieldType',
    'number_field',
    'text_field',
    'bool_field',
    'ref_field',
    'list_field',
    'list_sub_field',
    'party_role',
    'industry_field',
    'industry_number_field',
    'industry_text_field',
    'industry_bool_field',
    'RegionFieldType',
    'RegionFieldSpec',
    'RegionCondition',
    'RegionFieldsDocument',
    'ConditionOp',
    'ConditionSource',
    'region_field',
    'region_condition',
    'region_fields_document',
    'validate_source',
    'validate_file',
]

__version__ = '1.1.0'
