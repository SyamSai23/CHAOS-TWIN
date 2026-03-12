from __future__ import annotations

import json
import shutil
import sys
import tempfile
import textwrap
import uuid
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.main import app


def main() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="chaos-twin-route-api-"))
    try:
        service_repo = create_python_service_repo(temp_root / "python-service-flow")
        sparse_repo = create_sparse_repo(temp_root / "sparse-minimal")
        client = TestClient(app)
        results = [
            validate_case(client, "backend_api", REPO_ROOT / "backend"),
            validate_case(client, "python_service_flow", service_repo),
            validate_case(client, "sparse_minimal", sparse_repo),
        ]
        print(json.dumps({"cases": results}, indent=2))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def validate_case(client: TestClient, case_name: str, source_dir: Path) -> dict:
    project_id = create_scanned_project(client, case_name, source_dir)
    try:
        list_response = client.get(f"/projects/{project_id}/routes")
        ensure_status(list_response, 200, f"{case_name} routes list")
        routes_payload = list_response.json()

        if case_name == "sparse_minimal":
            assert routes_payload["total"] == 0
            return {
                "name": case_name,
                "route_total": 0,
                "degraded_cleanly": True,
            }

        first_route = first_route_item(routes_payload)
        assert first_route["id"]
        assert "request_flow_summary" in first_route
        detail_response = client.get(f"/projects/{project_id}/routes/{first_route['id']}")
        ensure_status(detail_response, 200, f"{case_name} route detail")
        detail_payload = detail_response.json()
        analyze_response = client.get(f"/projects/{project_id}/analyze/route/{first_route['id']}")
        ensure_status(analyze_response, 200, f"{case_name} analyze fallback")
        analyze_payload = analyze_response.json()

        assert detail_payload["id"] == first_route["id"]
        assert detail_payload["request_flow"]["stage_count"] >= 2
        assert detail_payload["request_flow"]["stages"][0]["stage_type"] == "dispatch"
        assert detail_payload["request_flow"]["stages"][-1]["stage_type"] == "response"
        assert detail_payload["route_analysis"]["analysis_signature"]
        assert analyze_payload["analysis_signature"] == detail_payload["route_analysis"]["analysis_signature"]

        sample = {
            "route_id": detail_payload["id"],
            "analysis_source": detail_payload["analysis_source"],
            "request_flow_summary": first_route["request_flow_summary"],
            "best_target": detail_payload.get("best_target"),
            "stage_types": [stage["stage_type"] for stage in detail_payload["request_flow"]["stages"]],
        }

        if case_name == "python_service_flow":
            assert "service" in sample["stage_types"]
            assert "repository" in sample["stage_types"] or "data_access" in sample["stage_types"]
            assert "external" in sample["stage_types"]
            assert detail_payload["analysis_source"] == "derived_from_request_flow"

        return {
            "name": case_name,
            "route_total": routes_payload["total"],
            "sample": sample,
        }
    finally:
        client.delete(f"/projects/{project_id}")


def create_scanned_project(client: TestClient, case_name: str, source_dir: Path) -> str:
    create_response = client.post(
        "/projects",
        json={"name": f"route-api-{case_name}-{uuid.uuid4().hex[:8]}", "path": str(source_dir)},
    )
    ensure_status(create_response, 201, f"{case_name} project creation")
    project_id = create_response.json()["id"]

    upload_response = client.post(
        f"/projects/{project_id}/upload",
        files={"file": (f"{case_name}.zip", build_zip_bytes(source_dir), "application/zip")},
    )
    ensure_status(upload_response, 201, f"{case_name} upload")

    scan_response = client.post(f"/projects/{project_id}/scan")
    ensure_status(scan_response, 201, f"{case_name} scan")
    return project_id


def build_zip_bytes(source_dir: Path) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            archive.write(path, path.relative_to(source_dir))
    return buffer.getvalue()


def ensure_status(response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise RuntimeError(f"{label} failed: {response.status_code} {response.text}")


def first_route_item(routes_payload: dict) -> dict:
    for component_group in routes_payload.get("by_component", []):
        routes = component_group.get("routes") or []
        if routes:
            return routes[0]
    raise AssertionError("expected at least one route item")


def create_python_service_repo(root: Path) -> Path:
    write_text(root / "requirements.txt", "flask\nrequests\n")
    write_text(
        root / "app.py",
        """
        from flask import Blueprint, Flask
        from app.services.user_service import create_user_account

        app = Flask(__name__)
        bp = Blueprint('users', __name__, url_prefix='/api')

        def require_auth(func):
            return func

        def validate_payload(func):
            return func

        @bp.route('/users', methods=['POST'])
        @require_auth
        @validate_payload
        def create_user():
            return create_user_account({'name': 'Ada'})

        app.register_blueprint(bp)
        """,
    )
    write_text(
        root / "app" / "services" / "user_service.py",
        """
        from app.integrations.billing_gateway import create_customer
        from app.repositories.user_repository import save_user

        def create_user_account(payload):
            customer = create_customer(payload)
            return save_user(payload, customer)
        """,
    )
    write_text(
        root / "app" / "repositories" / "user_repository.py",
        """
        class Session:
            def add(self, payload):
                return payload

            def commit(self):
                return True

        db = Session()

        def save_user(payload, customer):
            db.add({'payload': payload, 'customer': customer})
            db.commit()
            return {'ok': True}
        """,
    )
    write_text(
        root / "app" / "integrations" / "billing_gateway.py",
        """
        import requests

        def create_customer(payload):
            requests.post('https://billing.example.com/customers', json=payload)
            return {'id': 'cus_123'}
        """,
    )
    return root


def create_sparse_repo(root: Path) -> Path:
    write_text(root / "README.md", "# Sparse\n")
    write_text(
        root / "tool.py",
        """
        def main():
            return 'ok'
        """,
    )
    return root


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()