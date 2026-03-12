from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from app.services.scanner_v3 import run_full_scan


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="chaos-twin-component-validation-"))
    try:
        sparse_repo = create_sparse_repo(temp_root / "sparse-minimal")
        cases = [
            validate_backend_api_case(REPO_ROOT / "backend"),
            validate_frontend_case(REPO_ROOT / "frontend"),
            validate_fullstack_case(REPO_ROOT),
            validate_sparse_case(sparse_repo),
        ]
        print(json.dumps({"cases": cases}, indent=2))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def validate_backend_api_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    components = result["components"]
    assert len(components) == 1, f"expected one backend component, got {components}"
    component = components[0]
    assert component["type"] == "backend"
    assert component["root_path"] in {".", "app"}
    assert component["name"] == "backend"
    assert component["entry_file"] == "app/main.py"
    assert component["ownership_summary"]["route_count"] >= 10
    assert "controller" in component["detected_roles"]
    assert "service" in component["detected_roles"]
    assert "model_schema" in component["detected_roles"]
    assert component["confidence"] >= 0.8
    return summarize_component("backend_api", component)


def validate_frontend_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    components = result["components"]
    assert len(components) == 1, f"expected one frontend component, got {components}"
    component = components[0]
    assert component["type"] == "frontend"
    assert component["root_path"] in {".", "src"}
    assert component["name"] == "frontend"
    assert component["entry_file"] == "src/main.tsx"
    assert "frontend_entry" in component["detected_roles"]
    assert "frontend_ui" in component["detected_roles"]
    assert component["confidence"] >= 0.75
    return summarize_component("frontend_only", component)


def validate_fullstack_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    components = result["components"]
    assert len(components) == 2, f"expected backend and frontend components, got {components}"
    index = {component["root_path"]: component for component in components}
    backend = index["backend"]
    frontend = index["frontend"]
    assert backend["type"] == "backend"
    assert frontend["type"] == "frontend"
    assert backend["ownership_summary"]["route_count"] >= 10
    assert "controller" in backend["detected_roles"]
    assert "frontend_entry" in frontend["detected_roles"]
    return {
        "name": "fullstack_workspace",
        "component_count": len(components),
        "components": [summarize_component("backend", backend), summarize_component("frontend", frontend)],
    }


def validate_sparse_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    assert result["components"] == [], f"expected no components, got {result['components']}"
    return {
        "name": "sparse_minimal",
        "component_count": 0,
    }


def summarize_component(name: str, component: dict) -> dict:
    return {
        "name": name,
        "component_name": component["name"],
        "type": component["type"],
        "root_path": component["root_path"],
        "entry_file": component.get("entry_file"),
        "detected_roles": component.get("detected_roles", []),
        "role_counts": component.get("role_counts", {}),
        "route_count": component.get("ownership_summary", {}).get("route_count", 0),
        "key_files": component.get("key_files", []),
        "confidence": component.get("confidence"),
        "boundary_evidence": component.get("boundary_evidence", []),
    }


def create_sparse_repo(root: Path) -> Path:
    write_text(root / "README.md", "# Sparse\n")
    write_text(root / "tool.py", "def main():\n    return 1\n")
    return root


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()