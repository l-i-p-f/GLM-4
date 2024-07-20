from dataclasses import dataclass
from typing import Any


@dataclass
class ToolObservation:
    content_type: str  # 内容类型, 如system_error, 工具名称
    text: str  # 文本内容, 如日志信息, 工具调用结果
    image_url: str | None = None
    role_metadata: str | None = None
    metadata: Any = None
