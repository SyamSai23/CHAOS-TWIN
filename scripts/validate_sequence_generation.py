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
    temp_root = Path(tempfile.mkdtemp(prefix="chaos-twin-sequence-validation-"))
    try:
        python_service = create_python_service_repo(temp_root / "python-service-flow")
        express_service = create_express_service_repo(temp_root / "express-service-flow")
        sparse_repo = create_sparse_repo(temp_root / "sparse-minimal")
        client = TestClient(app)
        results = [
            validate_backend_api_case(client, REPO_ROOT / "backend"),
            validate_full_stack_workspace_case(client, REPO_ROOT),
            validate_python_service_case(client, python_service),
            validate_express_service_case(client, express_service),
            validate_sparse_case(client, sparse_repo),
        ]
        print(json.dumps({"cases": results}, indent=2))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def validate_backend_api_case(client: TestClient, source_dir: Path) -> dict:
    project_id = create_scanned_project(client, "backend-api-seq", source_dir)
    try:
        route = find_route(client, project_id, "POST", "/projects")
        sequence = generate_sequence(client, project_id, route)

        assert sequence["metadata"]["sequence_source"] == "request_flow"
        assert sequence["metadata"]["request_flow_stage_count"] >= 3
        assert sequence["metadata"]["degraded"] is False
        assert any(message["source_stage_type"] == "data_access" for message in sequence["messages"])
        assert any(message["label"] == "persist changes" for message in sequence["messages"])
        assert all("source_stage_step" in message for message in sequence["messages"])

        return {
            "name": "backend_api",
            "participant_labels": [participant["label"] for participant in sequence["participants"]],
            "message_labels": [message["label"] for message in sequence["messages"]],
            "metadata": sequence["metadata"],
        }
    finally:
        client.delete(f"/projects/{project_id}")


def validate_full_stack_workspace_case(client: TestClient, source_dir: Path) -> dict:
    project_id = create_scanned_project(client, "full-stack-seq", source_dir)
    try:
        route = find_route(client, project_id, "POST", "/projects")
        sequence = generate_sequence(client, project_id, route)

        assert sequence["metadata"]["sequence_source"] == "request_flow"
        assert sequence["metadata"]["request_flow_stage_count"] >= 3
        assert sequence["metadata"]["warnings"] == []

        return {
            "name": "full_stack_workspace",
            "message_count": len(sequence["messages"]),
            "metadata": sequence["metadata"],
        }
    finally:
        client.delete(f"/projects/{project_id}")


def validate_python_service_case(client: TestClient, source_dir: Path) -> dict:
    project_id = create_scanned_project(client, "python-service-seq", source_dir)
    try:
        route = find_route(client, project_id, "POST", "/api/users")
        sequence = generate_sequence(client, project_id, route)
        labels = [message["label"] for message in sequence["messages"]]
        participants = [participant["label"] for participant in sequence["participants"]]

        assert sequence["metadata"]["sequence_source"] == "request_flow"
        assert any(label == "verify auth token" for label in labels)
        assert any(label == "validate request payload" for label in labels)
        assert any(label == "create user account" for label in labels)
        assert any(label == "save user" for label in labels)
        assert any(label == "call Billing Gateway" for label in labels)
        assert any(label == "return 201 response" for label in labels)
        assert any(participant == "User Service" for participant in participants)
        assert any(participant == "User Repository" for participant in participants)
        assert any(participant == "Billing Gateway" for participant in participants)
        assert any(message.get("code_anchor", {}).get("file_path") for message in sequence["messages"])

        return {
            "name": "python_service_flow",
            "participant_labels": participants,
            "message_labels": labels,
            "metadata": sequence["metadata"],
        }
    finally:
        client.delete(f"/projects/{project_id}")


def validate_express_service_case(client: TestClient, source_dir: Path) -> dict:
    project_id = create_scanned_project(client, "express-service-seq", source_dir)
    try:
        route = find_route(client, project_id, "POST", "/api/orders")
        sequence = generate_sequence(client, project_id, route)
        labels = [message["label"] for message in sequence["messages"]]

        assert sequence["metadata"]["sequence_source"] == "request_flow"
        assert any(label == "verify auth token" for label in labels)
        assert any(label == "validate request payload" for label in labels)
        assert any(label == "create" for label in labels)
        assert any(label == "call Billing Gateway" for label in labels)
        assert any(message["source_stage_type"] == "service" for message in sequence["messages"])
        assert any(message.get("class_name") == "OrderService" for message in sequence["messages"])

        return {
            "name": "express_service_flow",
            "message_labels": labels,
            "metadata": sequence["metadata"],
        }
    finally:
        client.delete(f"/projects/{project_id}")


def validate_sparse_case(client: TestClient, source_dir: Path) -> dict:
    project_id = create_scanned_project(client, "sparse-seq", source_dir)
    try:
        routes_payload = fetch_routes(client, project_id)
        assert routes_payload["total"] == 0
        return {
            "name": "sparse_minimal",
            "route_total": 0,
            "degraded_cleanly": True,
        }
    finally:
        client.delete(f"/projects/{project_id}")


def create_scanned_project(client: TestClient, case_name: str, source_dir: Path) -> str:
    create_response = client.post(
        "/projects",
        json={"name": f"{case_name}-{uuid.uuid4().hex[:8]}", "path": str(source_dir)},
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

    graph_response = client.post(f"/projects/{project_id}/graph")
    ensure_status(graph_response, 201, f"{case_name} graph")
    return project_id


def fetch_routes(client: TestClient, project_id: str) -> dict:
    response = client.get(f"/projects/{project_id}/routes")
    ensure_status(response, 200, f"{project_id} route list")
    return response.json()


def find_route(client: TestClient, project_id: str, method: str, path: str) -> dict:
    payload = fetch_routes(client, project_id)
    for group in payload.get("by_component", []):
        for route in group.get("routes") or []:
            if route.get("method") == method and route.get("path") == path:
                return route
    raise AssertionError(f"expected route {method} {path}")


def generate_sequence(client: TestClient, project_id: str, route: dict) -> dict:
    response = client.post(
        f"/projects/{project_id}/sequence/route",
        json={
            "method": route["method"],
            "path": route["path"],
            "file": route["file"],
            "component": route["component"],
        },
    )
    ensure_status(response, 201, f"{project_id} route sequence generation")
    payload = response.json()
    assert payload["metadata"]["analysis_signature"]
    return payload


def ensure_status(response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise RuntimeError(f"{label} failed: {response.status_code} {response.text}")


def build_zip_bytes(source_dir: Path) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            archive.write(path, path.relative_to(source_dir))
    return buffer.getvalue()


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


def create_express_service_repo(root: Path) -> Path:
    write_text(
        root / "package.json",
        '{"name": "express-flow", "version": "1.0.0", "dependencies": {"express": "^4.0.0"}}',
    )
    write_text(
        root / "src" / "routes.js",
        """
        const express = require('express');
        const ensureAuth = require('./middleware/ensureAuth');
        const validateOrder = require('./middleware/validateOrder');
        const OrderController = require('./controllers/OrderController');

        const router = express.Router();

        router.post('/api/orders', ensureAuth, validateOrder, OrderController.store);

        module.exports = router;
        """,
    )
    write_text(
        root / "src" / "controllers" / "OrderController.js",
        """
        const OrderService = require('../services/OrderService');

        class OrderController {
          static async store(req, res) {
            const result = await OrderService.create(req.body);
            return res.status(201).json(result);
          }
        }

        module.exports = OrderController;
        """,
    )
    write_text(
        root / "src" / "services" / "OrderService.js",
        """
        const BillingGateway = require('../integrations/BillingGateway');

        class OrderService {
          static async create(payload) {
            await BillingGateway.charge(payload);
            return { ok: true };
          }
        }

        module.exports = OrderService;
        """,
    )
    write_text(
        root / "src" / "integrations" / "BillingGateway.js",
        """
        const axios = require('axios');

        class BillingGateway {
          static async charge(payload) {
            return axios.post('https://billing.example.com/orders', payload);
          }
        }

        module.exports = BillingGateway;
        """,
    )
    write_text(
        root / "src" / "middleware" / "ensureAuth.js",
        """
        module.exports = function ensureAuth(req, res, next) {
          return next();
        };
        """,
    )
    write_text(
        root / "src" / "middleware" / "validateOrder.js",
        """
        module.exports = function validateOrder(req, res, next) {
          return next();
        };
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