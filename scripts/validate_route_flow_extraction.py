from __future__ import annotations

import json
import shutil
import sys
import tempfile
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.scanner_v3 import run_full_scan


def main() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="chaos-twin-route-flow-validation-"))
    try:
        service_repo = create_python_service_repo(temp_root / "python-service-flow")
        express_repo = create_express_service_repo(temp_root / "express-service-flow")
        sparse_repo = create_sparse_repo(temp_root / "sparse-minimal")

        cases = [
            validate_backend_case(REPO_ROOT / "backend"),
            validate_python_service_case(service_repo),
            validate_express_service_case(express_repo),
            validate_sparse_case(sparse_repo),
        ]
        print(json.dumps({"cases": cases}, indent=2))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def validate_backend_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    routes = result["routes"]
    route_index = {(route["method"], route["path"], route["file"]): route for route in routes}

    create_project = route_index[("POST", "/projects", "app/routers/projects.py")]
    delete_project = route_index[("DELETE", "/projects/{project_id}", "app/routers/projects.py")]

    create_flow = create_project["request_flow"]
    delete_flow = delete_project["request_flow"]

    assert create_flow["stages"][0]["stage_type"] == "dispatch"
    assert create_flow["stages"][-1]["stage_type"] == "response"
    assert any(stage["stage_type"] == "handler" for stage in create_flow["stages"])
    assert any(stage["stage_type"] == "data_access" for stage in delete_flow["stages"])

    return {
        "name": "backend_api",
        "route_count": len(routes),
        "create_project_stages": summarize_flow(create_flow),
        "delete_project_stages": summarize_flow(delete_flow),
    }


def validate_python_service_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    routes = result["routes"]
    route_index = {(route["method"], route["path"], route["file"]): route for route in routes}
    create_user = route_index[("POST", "/api/users", "app.py")]
    flow = create_user["request_flow"]
    stage_types = [stage["stage_type"] for stage in flow["stages"]]

    assert stage_types[:4] == ["dispatch", "auth", "validation", "handler"]
    assert "service" in stage_types
    assert "repository" in stage_types or "data_access" in stage_types
    assert "external" in stage_types
    assert flow["summary"]["has_service"] is True
    assert flow["summary"]["has_external"] is True

    return {
        "name": "python_service_flow",
        "route_count": len(routes),
        "create_user_stages": summarize_flow(flow),
    }


def validate_express_service_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    routes = result["routes"]
    route_index = {(route["method"], route["path"], route["file"]): route for route in routes}
    create_order = route_index[("POST", "/api/orders", "src/routes.js")]
    flow = create_order["request_flow"]
    stage_types = [stage["stage_type"] for stage in flow["stages"]]

    assert stage_types[0] == "dispatch"
    assert "auth" in stage_types
    assert "validation" in stage_types
    assert "handler" in stage_types
    assert "service" in stage_types
    assert flow["stages"][-1]["stage_type"] == "response"

    return {
        "name": "express_service_flow",
        "route_count": len(routes),
        "create_order_stages": summarize_flow(flow),
    }


def validate_sparse_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    assert result["routes"] == []
    return {"name": "sparse_minimal", "route_count": 0}


def summarize_flow(flow: dict) -> list[dict]:
    return [
        {
            "stage_type": stage.get("stage_type"),
            "file_path": stage.get("file_path"),
            "symbol_name": stage.get("symbol_name"),
            "class_name": stage.get("class_name"),
            "confidence": stage.get("confidence"),
        }
        for stage in flow.get("stages") or []
    ]


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