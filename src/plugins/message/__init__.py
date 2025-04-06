"""Maim Message - A message handling library"""

__version__ = "0.1.0"

from .api import BaseMessageAPI, global_api
from .message_base import (
    Seg,
    GroupInfo,
    UserInfo,
    FormatInfo,
    TemplateInfo,
    BaseMessageInfo,
    MessageBase,
)

__all__ = [
    "BaseMessageAPI",
    "Seg",
    "global_api",
    "GroupInfo",
    "UserInfo",
    "FormatInfo",
    "TemplateInfo",
    "BaseMessageInfo",
    "MessageBase",
]
