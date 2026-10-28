"""Settings that belong to the business (thresholds, channel mappings, model routing) live in
config/*.yaml, not in code. This module reads them."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(os.environ.get("MSD_ROOT", Path(__file__).resolve().parents[2]))


def channel_label(key: str | None) -> str:
    """Google Ads, Meta, ... for display; the key itself if unknown."""
    if not key:
        return "every channel"
    return str(read("channels")["channels"].get(key, {}).get("label", key))


@lru_cache
def read(name: str) -> dict[str, Any]:
    with open(ROOT / "config" / f"{name}.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"config/{name}.yaml must be a mapping")
    return data
