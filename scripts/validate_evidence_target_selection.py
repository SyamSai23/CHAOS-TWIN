from __future__ import annotations

import json
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.domain.system_model.adapters import build_project_model_from_scan
from app.models.project import Project
from app.models.scan import Scan
from app.services.scanner_v3 import run_full_scan


def main() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="chaos-twin-evidence-target-validation-"))
    try:
        service_repo = create_service_heavy_repo(temp_root / "service-heavy")
        sparse_repo = create_sparse_repo(temp_root / "sparse-minimal")
        cases = [
            validate_backend_api_case(REPO_ROOT / "backend"),
            validate_frontend_case(REPO_ROOT / "frontend"),
            validate_service_heavy_case(service_repo),
            validate_sparse_case(sparse_repo),
        ]
        print(json.dumps({"cases": cases}, indent=2))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def validate_backend_api_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    component = result["components"][0]
    assert component["best_target"]["anchor_kind"] == "route_file"
    assert component["best_target"]["file_path"].endswith(".py")

    route = next(
        item for item in result["routes"]
        if item.get("handler_function") and item.get("best_target", {}).get("line_start") is not None
    )
    assert route["best_target"]["anchor_kind"] == "handler_definition"
    assert route["best_target"]["target_rank"] >= 96

    infra = {item["name"]: item for item in component.get("infrastructure", [])}
    postgres = infra["PostgreSQL"]
    assert postgres["best_target"]["file_path"]
    assert postgres["best_target"]["target_rank"] >= 48

    model = build_model(root, result)
    canonical_component = next(iter(model.components.values()))
    assert canonical_component.metadata.get("best_target", {}).get("file_path")
    canonical_route = next(iter(model.routes.values()))
    route_evidence = model.evidence[canonical_route.evidence_ids[0]]
    assert route_evidence.line_start is not None

    return {
        "name": "backend_api",
        "component_best_target": component["best_target"],
        "route_best_target": route["best_target"],
        "postgres_best_target": postgres["best_target"],
    }


def validate_frontend_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    component = result["components"][0]
    assert component["best_target"]["anchor_kind"] == "entry_file"
    assert component["best_target"]["file_path"] == "src/main.tsx"
    return {
        "name": "frontend_only",
        "component_best_target": component["best_target"],
    }


def validate_service_heavy_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    components = {component["name"]: component for component in result["components"]}
    gateway = components["gateway"]
    worker = components["worker"]
    assert gateway["best_target"]["file_path"] == "gateway/main.py"
    assert worker["best_target"]["file_path"] == "worker/app.py"

    gateway_infra = {item["name"]: item for item in gateway.get("infrastructure", [])}
    worker_infra = {item["name"]: item for item in worker.get("infrastructure", [])}
    assert gateway_infra["Redis"]["best_target"]["anchor_kind"] == "client_initialization"
    assert gateway_infra["Redis"]["best_target"]["file_path"] == "gateway/main.py"
    assert worker_infra["PostgreSQL"]["best_target"]["anchor_kind"] in {"client_initialization", "connection_string"}
    assert worker_infra["PostgreSQL"]["best_target"]["file_path"] == "worker/app.py"

    model = build_model(root, result)
    store_targets = {
        store.name: store.metadata.get("best_target")
        for store in model.data_stores.values()
        if store.metadata.get("best_target")
    }
    assert store_targets["Redis"]["file_path"] == "gateway/main.py"
    assert store_targets["PostgreSQL"]["file_path"] == "worker/app.py"

    return {
        "name": "service_heavy",
        "gateway_best_target": gateway["best_target"],
        "worker_best_target": worker["best_target"],
        "gateway_infra_best_targets": {
            name: item["best_target"]
            for name, item in gateway_infra.items()
        },
        "worker_infra_best_targets": {
            name: item["best_target"]
            for name, item in worker_infra.items()
        },
    }


def validate_sparse_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    assert result["components"] == [], f"expected sparse repo to have no components, got {result['components']}"
    return {"name": "sparse_minimal", "component_count": 0}


def build_model(root: Path, scan_result: dict) -> object:
    project = Project(id="project-validation", name=root.name, path=str(root))
    scan = Scan(
        id=f"scan-{root.name}",
        project_id=project.id,
        upload_id="upload-validation",
        status="completed",
        file_count=len(scan_result["files"]),
        files=scan_result["files"],
        languages=scan_result["languages"],
        frameworks=scan_result["frameworks"],
        key_files=scan_result["key_files"],
        top_level_dirs=scan_result["top_level_dirs"],
        extension_counts=scan_result["extension_counts"],
        project_type=scan_result["project_type"],
        entry_points=scan_result["entry_points"],
        components=scan_result["components"],
        confidence_scores=scan_result["confidence_scores"],
        dependencies=scan_result["dependencies"],
        service_graph=scan_result["service_graph"],
        routes=scan_result["routes"],
        import_graph=scan_result["import_graph"],
        execution_flow=scan_result["execution_flow"],
        env_variables=scan_result["env_variables"],
        docker_services=scan_result["docker_services"],
    )
    return build_project_model_from_scan(project, scan)


def create_service_heavy_repo(root: Path) -> Path:
    write_text(
        root / "docker-compose.yml",
        """
        version: '3.9'
        services:
          gateway:
            build: ./gateway
            depends_on:
              - postgres
              - redis
          worker:
            build: ./worker
            depends_on:
              - postgres
              - redis
          postgres:
            image: postgres:16
          redis:
            image: redis:7
        """,
    )
    write_text(root / "gateway" / "requirements.txt", "fastapi\nuvicorn\npsycopg\nredis\nstripe\n")
    write_text(
        root / "gateway" / "main.py",
        """
        from fastapi import FastAPI
        import redis
        import stripe

        app = FastAPI()
        cache = redis.Redis(host=\"redis\")


        @app.get(\"/health\")
        def health():
            cache.ping()
            return {\"status\": \"ok\", \"provider\": stripe.__name__}
        """,
    )
    write_text(root / "worker" / "requirements.txt", "fastapi\npsycopg\nredis\n")
    write_text(
        root / "worker" / "app.py",
        """
        import psycopg
        import redis


        def run_job():
            cache = redis.Redis(host=\"redis\")
            cache.ping()
            return psycopg.connect(\"postgresql://postgres:postgres@postgres/service\")
        """,
    )
    return root


def create_sparse_repo(root: Path) -> Path:
    write_text(root / "README.md", "# Sparse repo\n")
    write_text(root / "tool.py", "def main():\n    return 'ok'\n")
    return root


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()