from __future__ import annotations

import json
import shutil
import tempfile
import textwrap
from pathlib import Path

from app.services.scanner_v3 import run_full_scan


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="chaos-twin-route-validation-"))
    try:
        express_repo = create_express_fullstack_repo(temp_root / "express-fullstack")
        flask_repo = create_flask_repo(temp_root / "flask-api")
        sparse_repo = create_sparse_repo(temp_root / "sparse-minimal")

        cases = [
            validate_backend_api_case(REPO_ROOT / "backend"),
            validate_express_case(express_repo),
            validate_flask_case(flask_repo),
            validate_sparse_case(sparse_repo),
        ]

        print(json.dumps({"cases": cases}, indent=2))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def validate_backend_api_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    routes = result["routes"]
    route_index = {(route["method"], route["path"], route["file"]): route for route in routes}
    assert len(routes) >= 10, f"expected backend repo to expose many routes, got {len(routes)}"
    assert len(route_index) == len(routes), "backend routes contain duplicate (method,path,file) entries"

    create_project = route_index[("POST", "/projects", "app/routers/projects.py")]
    delete_project = route_index[("DELETE", "/projects/{project_id}", "app/routers/projects.py")]
    health = route_index[("GET", "/health", "app/main.py")]

    assert create_project["handler_function"] == "create_project"
    assert create_project["router_prefix"] == "/projects"
    assert create_project["evidence"]["line_start"] is not None
    assert create_project["confidence"] >= 0.9
    assert delete_project["handler_function"] == "delete_project"
    assert health["handler_function"] == "health"

    evidence_covered = sum(1 for route in routes if route.get("evidence", {}).get("line_start"))
    return {
        "name": "backend_api",
        "route_count": len(routes),
        "evidence_covered": evidence_covered,
        "sample_routes": {
            "create_project": summarize_route(create_project),
            "delete_project": summarize_route(delete_project),
            "health": summarize_route(health),
        },
    }


def validate_express_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    routes = result["routes"]
    route_index = {(route["method"], route["path"], route["file"]): route for route in routes}
    assert len(route_index) == len(routes), "express case contains duplicate routes"

    session_route = route_index[("POST", "/api/v1/sessions", "backend/src/routes.js")]
    spot_route = route_index[("POST", "/api/v1/spots", "backend/src/routes.js")]
    booking_route = route_index[("POST", "/api/v1/spots/:spot_id/bookings", "backend/src/routes.js")]

    assert session_route["controller_name"] == "SessionController"
    assert session_route["handler_function"] == "store"
    assert spot_route["router_prefix"] == "/api/v1"
    assert "upload.single" in spot_route["middleware"]
    assert "ensureAuth" in spot_route["auth_hints"]
    assert "validateSpot" in spot_route["validation_hints"]
    assert booking_route["controller_name"] == "BookingController"

    return {
        "name": "express_fullstack",
        "route_count": len(routes),
        "sample_routes": {
            "session": summarize_route(session_route),
            "spot": summarize_route(spot_route),
            "booking": summarize_route(booking_route),
        },
    }


def validate_flask_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    routes = result["routes"]
    route_index = {(route["method"], route["path"], route["file"]): route for route in routes}
    assert len(route_index) == len(routes), "flask case contains duplicate routes"

    list_items = route_index[("GET", "/api/items", "app.py")]
    create_item = route_index[("POST", "/api/items", "app.py")]

    assert list_items["handler_function"] == "list_items"
    assert create_item["handler_function"] == "create_item"
    assert create_item["router_prefix"] == "/api"
    assert "require_auth" in create_item["auth_hints"]
    assert "validate_payload" in create_item["validation_hints"]
    assert create_item["evidence"]["line_start"] is not None

    return {
        "name": "flask_api",
        "route_count": len(routes),
        "sample_routes": {
            "list_items": summarize_route(list_items),
            "create_item": summarize_route(create_item),
        },
    }


def validate_sparse_case(root: Path) -> dict:
    result = run_full_scan(str(root))
    routes = result["routes"]
    assert routes == [], f"expected sparse repo to have no routes, got {routes}"
    return {
        "name": "sparse_minimal",
        "route_count": 0,
    }


def summarize_route(route: dict) -> dict:
    return {
        "method": route["method"],
        "path": route["path"],
        "file": route["file"],
        "handler_function": route.get("handler_function"),
        "controller_name": route.get("controller_name"),
        "router_prefix": route.get("router_prefix"),
        "middleware": route.get("middleware", []),
        "auth_hints": route.get("auth_hints", []),
        "validation_hints": route.get("validation_hints", []),
        "confidence": route.get("confidence"),
        "line_start": route.get("line_start"),
        "line_end": route.get("line_end"),
    }


def create_express_fullstack_repo(root: Path) -> Path:
    write_text(
        root / "frontend" / "package.json",
        '{"name": "frontend", "version": "1.0.0"}',
    )
    write_text(
        root / "backend" / "package.json",
        '{"name": "backend", "version": "1.0.0", "dependencies": {"express": "^4.0.0"}}',
    )
    write_text(
        root / "backend" / "src" / "server.js",
        """
        const express = require('express');
        const routes = require('./routes');

        const app = express();

        app.use('/api/v1', routes);
        app.listen(3333);
        """,
    )
    write_text(
        root / "backend" / "src" / "routes.js",
        """
        const express = require('express');
        const upload = require('./upload');
        const ensureAuth = require('./middleware/ensureAuth');
        const validateSpot = require('./middleware/validateSpot');
        const SessionController = require('./controllers/SessionController');
        const SpotController = require('./controllers/SpotController');
        const BookingController = require('./controllers/BookingController');

        const routes = express.Router();

        routes.post('/sessions', SessionController.store);
        routes.post('/spots', ensureAuth, validateSpot, upload.single('thumbnail'), SpotController.store);
        routes.post('/spots/:spot_id/bookings', ensureAuth, BookingController.store);

        module.exports = routes;
        """,
    )
    return root


def create_flask_repo(root: Path) -> Path:
    write_text(root / "requirements.txt", "flask\n")
    write_text(
        root / "app.py",
        """
        from flask import Blueprint, Flask

        app = Flask(__name__)
        bp = Blueprint('items', __name__, url_prefix='/api')

        def require_auth(func):
            return func

        def validate_payload(func):
            return func

        @bp.route('/items', methods=['GET'])
        def list_items():
            return {'items': []}

        @bp.route('/items', methods=['POST'])
        @require_auth
        @validate_payload
        def create_item():
            return {'created': True}

        app.register_blueprint(bp)
        """,
    )
    return root


def create_sparse_repo(root: Path) -> Path:
    write_text(root / "README.md", "# Sparse\n")
    write_text(
        root / "tool.py",
        """
        def main():
            return 'hello'
        """,
    )
    return root


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
