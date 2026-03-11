from __future__ import annotations

import hashlib


def make_route_id(method: str, path: str, file_path: str = "") -> str:
    raw = f"{method.upper()}:{path}:{file_path}"
    return hashlib.md5(raw.encode()).hexdigest()


def make_component_key(root_path: str) -> str:
    normalized = (root_path or ".").replace("\\", "/").strip()
    return hashlib.md5(normalized.encode()).hexdigest()