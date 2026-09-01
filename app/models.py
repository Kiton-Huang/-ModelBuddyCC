"""
数据模型定义
"""
from dataclasses import dataclass, asdict


@dataclass
class ModelProfile:
    name: str
    base_url: str
    api_key: str
    model: str
    notes: str = ""
    # ── 模型层级映射（可选，空 = 不设置） ──
    opus_model: str = ""        # ANTHROPIC_DEFAULT_OPUS_MODEL
    sonnet_model: str = ""      # ANTHROPIC_DEFAULT_SONNET_MODEL
    haiku_model: str = ""       # ANTHROPIC_DEFAULT_HAIKU_MODEL
    subagent_model: str = ""    # CLAUDE_CODE_SUBAGENT_MODEL
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelProfile":
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__})


@dataclass
class LaunchRecord:
    directory: str
    label: str = ""
    opened_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LaunchRecord":
        return cls(**{k: d.get(k, "") for k in cls.__dataclass_fields__})
