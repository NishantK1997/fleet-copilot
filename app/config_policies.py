from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ReadToolPolicy(BaseModel):
    low_disk_percent: float = Field(default=10, gt=0, le=100)
    persistent_ratio: float = Field(default=0.5, ge=0, le=1)
    memory_used_percent: float = Field(default=85, gt=0, le=100)
    battery_cycle_count: int = Field(default=900, ge=0)
    battery_capacity_low: int = Field(default=5000, ge=0)


class InsightPolicy(ReadToolPolicy):
    compliance_drift_fail_ratio: float = Field(default=0.25, ge=0, le=1)


class Policies(BaseModel):
    read_tools: ReadToolPolicy = Field(default_factory=ReadToolPolicy)
    insights: InsightPolicy = Field(default_factory=InsightPolicy)


@lru_cache
def load_policies(path: str = "config/policies.yaml") -> Policies:
    policy_path = Path(path)
    if not policy_path.exists():
        return Policies()
    with policy_path.open("r", encoding="utf-8") as file:
        raw: dict[str, Any] = yaml.safe_load(file) or {}
    return Policies(**raw)


def clear_policy_cache() -> None:
    load_policies.cache_clear()
