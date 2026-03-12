from __future__ import annotations

import json
import shutil
import tempfile
import textwrap
from pathlib import Path

from app.domain.system_model.adapters import build_project_model_from_scan
from app.models.project import Project
from app.models.scan import Scan
from app.services.scanner_v3 import run_full_scan


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="chaos-twin-infra-validation-"))
    try:
        service_repo = create_service_heavy_repo(temp_root / "service-heavy")
        integration_repo = create_integration_repo(temp_root / "integration-heavy")
        sparse_repo = create_sparse_repo(temp_root / "sparse-minimal")
        cases = [
            validate_backend_api_case(REPO_ROOT / "backend"),
            validate_service_heavy_case(service_repo),
            validate_integration_heavy_case(integration_repo),
            validate_sparse_case(sparse_repo),
        ]
        print(json.dumps({"cases": cases}, indent=2))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def validate_backend_api_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    component = result["components"][0]
    infra = {item["name"]: item for item in component.get("infrastructure", [])}
    assert "PostgreSQL" in infra, f"expected backend API infra to include PostgreSQL, got {infra}"
    postgres = infra["PostgreSQL"]
    assert postgres["confidence"] >= 0.7
    assert any(signal in postgres["signals"] for signal in ["declared_dependency", "connection_string", "client_initialization"])

    model = build_model(root, result)
    assert any(store.name == "PostgreSQL" for store in model.data_stores.values())
    return {
        "name": "backend_api",
        "component": component["name"],
        "infrastructure": summarize_items(component.get("infrastructure", [])),
        "canonical_data_stores": sorted(store.name for store in model.data_stores.values()),
        "canonical_externals": sorted(item.name for item in model.external_integrations.values()),
    }


def validate_service_heavy_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    components = {component["name"]: component for component in result["components"]}
    gateway_infra = {item["name"]: item for item in components["gateway"].get("infrastructure", [])}
    worker_infra = {item["name"]: item for item in components["worker"].get("infrastructure", [])}

    assert "PostgreSQL" in gateway_infra
    assert "Redis" in gateway_infra
    assert "Stripe" in gateway_infra
    assert "AWS / S3" not in gateway_infra, "declared boto3 dependency alone should not create an external integration"
    assert gateway_infra["Redis"]["confidence"] >= 0.8
    assert "client_initialization" in gateway_infra["Redis"]["signals"]

    assert "PostgreSQL" in worker_infra
    assert "Redis" in worker_infra
    assert worker_infra["PostgreSQL"]["confidence"] >= 0.75
    assert "client_initialization" in worker_infra["PostgreSQL"]["signals"] or "docker_dependency" in worker_infra["PostgreSQL"]["signals"]

    model = build_model(root, result)
    assert "PostgreSQL" in {store.name for store in model.data_stores.values()}
    assert "Redis" in {store.name for store in model.data_stores.values()}
    assert "Stripe" in {item.name for item in model.external_integrations.values()}
    assert "AWS / S3" not in {item.name for item in model.external_integrations.values()}
    return {
        "name": "service_heavy",
        "components": {
            "gateway": summarize_items(components["gateway"].get("infrastructure", [])),
            "worker": summarize_items(components["worker"].get("infrastructure", [])),
        },
        "canonical_data_stores": sorted(store.name for store in model.data_stores.values()),
        "canonical_externals": sorted(item.name for item in model.external_integrations.values()),
    }


def validate_integration_heavy_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    component = result["components"][0]
    infra = {item["name"]: item for item in component.get("infrastructure", [])}
    assert "AWS / S3" in infra
    assert "SendGrid" in infra
    assert infra["AWS / S3"]["confidence"] >= 0.65
    assert "client_initialization" in infra["AWS / S3"]["signals"]
    assert "client_initialization" in infra["SendGrid"]["signals"]

    model = build_model(root, result)
    assert "AWS / S3" in {item.name for item in model.external_integrations.values()}
    assert "SendGrid" in {item.name for item in model.external_integrations.values()}
    return {
        "name": "integration_heavy",
        "component": component["name"],
        "infrastructure": summarize_items(component.get("infrastructure", [])),
        "canonical_externals": sorted(item.name for item in model.external_integrations.values()),
    }


def validate_sparse_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    assert result["components"] == [], f"expected sparse repo to have no components, got {result['components']}"
    return {"name": "sparse_minimal", "component_count": 0}


def summarize_items(items: list[dict]) -> list[dict]:
    return [
        {
            "name": item["name"],
            "entity_type": item["entity_type"],
            "kind": item["kind"],
            "confidence": item["confidence"],
            "signals": item.get("signals", []),
        }
        for item in items
    ]


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
    write_text(root / "gateway" / "requirements.txt", "fastapi\nuvicorn\npsycopg\nredis\nstripe\nboto3\n")
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
    write_text(root / "worker" / "requirements.txt", "fastapi\npsycopg\nredis\nrequests\n")
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


def create_integration_repo(root: Path) -> Path:
    write_text(root / "requirements.txt", "fastapi\nboto3\nsendgrid\n")
    write_text(
        root / "app.py",
        """
        import boto3
        from sendgrid import SendGridAPIClient


        def bootstrap():
            client = boto3.client(\"s3\")
            mailer = SendGridAPIClient(\"token\")
            return client, mailer
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