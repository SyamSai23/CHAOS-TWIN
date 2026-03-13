from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.db.session import SessionLocal
from app.main import app
from app.models.graph_edge import GraphEdge
from app.models.graph_node import GraphNode
from app.models.project import Project
from app.models.project_model_snapshot import ProjectModelSnapshot
from app.models.scan import Scan
from app.models.simulation_run import SimulationRun


@dataclass
class CaseConfig:
    name: str
    codebase_type: str
    source_dir: Path
    force_invalid_snapshot: bool = False


def main() -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="ct-e2e-validation-"))
    try:
        cases = build_cases(temp_root)
        client = TestClient(app)
        results = [run_case(case, client) for case in cases]
        print(json.dumps({"cases": results, "comparison": build_comparison(results)}, indent=2, default=str))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def build_cases(temp_root: Path) -> list[CaseConfig]:
    service_repo = create_service_heavy_repo(temp_root / "service-heavy-backend")
    sparse_repo = create_sparse_repo(temp_root / "sparse-minimal-repo")

    return [
        CaseConfig(
            name="backend_rest_api",
            codebase_type="backend REST API project",
            source_dir=REPO_ROOT / "backend",
        ),
        CaseConfig(
            name="frontend_only",
            codebase_type="frontend-only app",
            source_dir=REPO_ROOT / "frontend",
        ),
        CaseConfig(
            name="full_stack_workspace",
            codebase_type="full-stack app",
            source_dir=REPO_ROOT,
        ),
        CaseConfig(
            name="service_heavy_backend",
            codebase_type="service-heavy or integration-heavy backend",
            source_dir=service_repo,
        ),
        CaseConfig(
            name="sparse_minimal_repo",
            codebase_type="sparse/minimal weakly structured repo",
            source_dir=sparse_repo,
        ),
        CaseConfig(
            name="forced_fallback_backend",
            codebase_type="forced degraded fallback case",
            source_dir=REPO_ROOT / "backend",
            force_invalid_snapshot=True,
        ),
    ]


def create_service_heavy_repo(root: Path) -> Path:
    (root / "gateway").mkdir(parents=True, exist_ok=True)
    (root / "worker").mkdir(parents=True, exist_ok=True)

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
    write_text(
        root / "gateway" / "requirements.txt",
        "fastapi\nuvicorn\npsycopg\nredis\nstripe\nboto3\n",
    )
    write_text(
        root / "gateway" / "main.py",
        """
        from fastapi import FastAPI
        import redis
        import stripe

        app = FastAPI()
        cache = redis.Redis(host="redis")


        @app.get("/health")
        def health():
            cache.ping()
            return {"status": "ok", "provider": stripe.__name__}


        @app.post("/orders")
        def create_order():
            return {"created": True}
        """,
    )
    write_text(
        root / "worker" / "requirements.txt",
        "fastapi\npsycopg\nredis\nrequests\n",
    )
    write_text(
        root / "worker" / "app.py",
        """
        import psycopg
        import redis


        def run_job():
            cache = redis.Redis(host="redis")
            cache.ping()
            return psycopg.connect("postgresql://postgres:postgres@postgres/service")
        """,
    )
    return root


def create_sparse_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    write_text(root / "README.md", "# Sparse repo\nA weakly structured sample repo.\n")
    write_text(
        root / "tool.py",
        """
        def main():
            return "hello"


        if __name__ == "__main__":
            print(main())
        """,
    )
    return root


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def run_case(case: CaseConfig, client: TestClient) -> dict:
    db = SessionLocal()
    project_id = None
    try:
        project_name = f"validation-{case.name}-{uuid.uuid4().hex[:8]}"
        create_response = client.post(
            "/projects",
            json={"name": project_name, "path": str(case.source_dir)},
        )
        ensure_status(create_response, 201, "project creation")
        project_id = create_response.json()["id"]

        upload_response = client.post(
            f"/projects/{project_id}/upload",
            files={
                "file": (
                    f"{case.name}.zip",
                    build_zip_bytes(case.source_dir),
                    "application/zip",
                )
            },
        )
        ensure_status(upload_response, 201, "upload")

        scan_response = client.post(f"/projects/{project_id}/scan")
        scan_ok = scan_response.status_code == 201
        scan_payload = scan_response.json()

        scan = db.query(Scan).filter(Scan.project_id == project_id).order_by(Scan.created_at.desc()).first()
        snapshot = (
            db.query(ProjectModelSnapshot)
            .filter(ProjectModelSnapshot.project_id == project_id)
            .order_by(ProjectModelSnapshot.created_at.desc())
            .first()
        )
        snapshot_status = snapshot.status if snapshot is not None else "missing"

        if case.force_invalid_snapshot and snapshot is not None:
            snapshot.status = "completed"
            snapshot.model_data = {"broken": True}
            snapshot.validation_errors = []
            snapshot.error_message = None
            db.commit()
            snapshot_status = "created_then_corrupted_for_fallback"

        graph_response = client.post(f"/projects/{project_id}/graph")
        graph_ok = graph_response.status_code == 201
        graph_payload = graph_response.json()

        graph_nodes = (
            db.query(GraphNode)
            .filter(GraphNode.project_id == project_id)
            .order_by(GraphNode.created_at.asc())
            .all()
        )
        graph_edges = (
            db.query(GraphEdge)
            .filter(GraphEdge.project_id == project_id)
            .order_by(GraphEdge.created_at.asc())
            .all()
        )
        graph_mode = detect_graph_mode(graph_nodes, graph_edges)
        provenance_check = verify_graph_provenance(graph_mode, graph_nodes, graph_edges)

        simulation_status = "not-run"
        simulation_mode = "not-run"
        simulation_detail = None
        simulation_bug = None
        simulation_response = None
        simulation_node_id = choose_simulation_node(graph_nodes, graph_edges)
        if simulation_node_id is not None:
            simulation_response = client.post(
                f"/projects/{project_id}/simulate",
                json={"node_id": simulation_node_id},
            )
            simulation_status = str(simulation_response.status_code)
            if simulation_response.status_code == 201:
                simulation_payload = simulation_response.json()
                simulation_mode = simulation_payload.get("result", {}).get("mode", "unknown")
                simulation_detail = {
                    "severity": simulation_payload.get("severity"),
                    "impacted_count": len(simulation_payload.get("impacted_nodes", [])),
                }
            else:
                simulation_bug = simulation_response.json()
        else:
            simulation_response = client.post(
                f"/projects/{project_id}/simulate",
                json={"node_id": "missing-node"},
            )
            simulation_status = str(simulation_response.status_code)
            simulation_mode = "unavailable"
            simulation_detail = simulation_response.json()

        summary_response = client.get(f"/projects/{project_id}/summary")
        summary_ok = summary_response.status_code == 200
        summary_payload = summary_response.json()

        insights_response = client.get(f"/projects/{project_id}/insights")
        insights_ok = insights_response.status_code == 200
        insights_payload = insights_response.json()

        code_peek_checks = run_code_peek_checks(
            client=client,
            project_id=project_id,
            snapshot=snapshot,
            graph_nodes=graph_nodes,
            graph_edges=graph_edges,
            insights_payload=insights_payload if insights_ok else {},
            scan=scan,
        )

        same_scan_consistency = verify_same_scan_consistency(
            scan=scan,
            snapshot=snapshot,
            graph_nodes=graph_nodes,
            graph_edges=graph_edges,
            summary_payload=summary_payload,
            insights_payload=insights_payload,
            code_peek_checks=code_peek_checks,
        )

        anomalies = collect_anomalies(
            case=case,
            scan_ok=scan_ok,
            scan_payload=scan_payload,
            snapshot=snapshot,
            graph_ok=graph_ok,
            graph_payload=graph_payload,
            graph_nodes=graph_nodes,
            graph_edges=graph_edges,
            graph_mode=graph_mode,
            provenance_check=provenance_check,
            simulation_response=simulation_response,
            summary_payload=summary_payload,
            summary_ok=summary_ok,
            insights_payload=insights_payload,
            insights_ok=insights_ok,
            code_peek_checks=code_peek_checks,
            same_scan_consistency=same_scan_consistency,
        )

        result = {
            "name": case.name,
            "codebase_type": case.codebase_type,
            "project_id": project_id,
            "scan_succeeded": scan_ok,
            "scan_status": scan_payload.get("status") if scan_ok else scan_payload,
            "canonical_snapshot": {
                "status": snapshot_status,
                "snapshot_id": snapshot.id if snapshot is not None else None,
                "validation_errors": list(snapshot.validation_errors)[:3] if snapshot is not None else [],
            },
            "graph": {
                "status_code": graph_response.status_code,
                "mode": graph_mode,
                "node_count": len(graph_nodes),
                "edge_count": len(graph_edges),
                "provenance_check": provenance_check,
            },
            "simulation": {
                "status": simulation_status,
                "mode": simulation_mode,
                "detail": simulation_detail,
            },
            "summary": {
                "status_code": summary_response.status_code,
                "confidence": summary_payload.get("confidence_summary", {}).get("overall_label") if summary_ok else None,
                "graph_provenance": summary_payload.get("graph_provenance") if summary_ok else None,
                "system_type_guess": summary_payload.get("system_type_guess") if summary_ok else None,
                "top_findings": len(summary_payload.get("top_findings", [])) if summary_ok else None,
                "top_risks": len(summary_payload.get("top_risks", [])) if summary_ok else None,
            },
            "insights": {
                "status_code": insights_response.status_code,
                "count": insights_payload.get("insight_count") if insights_ok else None,
                "counts_by_severity": insights_payload.get("counts_by_severity") if insights_ok else None,
                "counts_by_category": insights_payload.get("counts_by_category") if insights_ok else None,
            },
            "code_peek": code_peek_checks,
            "same_scan_consistency": same_scan_consistency,
            "major_findings_or_anomalies": anomalies,
            "bug_discovered": False,
        }

        delete_response = client.delete(f"/projects/{project_id}")
        result["cleanup_deleted"] = delete_response.status_code == 200
        result["cleanup_isolated"] = verify_project_deleted(db, project_id)
        return result
    finally:
        if project_id is not None:
            db.expire_all()
            if db.query(Project).filter(Project.id == project_id).first() is not None:
                client.delete(f"/projects/{project_id}")
        db.close()


def ensure_status(response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise RuntimeError(f"{label} failed: {response.status_code} {response.text}")


ARCHIVE_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "uploads",
    "workspaces",
    "__pycache__",
}


def should_skip_archive_path(source_dir: Path, path: Path) -> bool:
    relative_parts = path.relative_to(source_dir).parts
    return any(part in ARCHIVE_EXCLUDED_PARTS for part in relative_parts)


def build_zip_bytes(source_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file() or should_skip_archive_path(source_dir, path):
                continue
            archive.write(path, path.relative_to(source_dir))
    return buffer.getvalue()


def detect_graph_mode(graph_nodes: list[GraphNode], graph_edges: list[GraphEdge]) -> str:
    sources = []
    for node in graph_nodes:
        sources.append((node.data or {}).get("graph_source", "unknown"))
    for edge in graph_edges:
        sources.append((edge.data or {}).get("graph_source", "unknown"))
    if not sources:
        return "empty"
    if all(source == "canonical_snapshot" for source in sources):
        return "canonical_snapshot"
    if all(source == "raw_scan_fallback" for source in sources):
        return "raw_scan_fallback"
    return "mixed"


def verify_graph_provenance(graph_mode: str, graph_nodes: list[GraphNode], graph_edges: list[GraphEdge]) -> dict:
    if graph_mode == "canonical_snapshot":
        nodes_ok = all(node.canonical_entity_id and node.confidence_label for node in graph_nodes) if graph_nodes else True
        edges_ok = all(edge.canonical_relation_id and edge.confidence_label and edge.inference_stage for edge in graph_edges) if graph_edges else True
        return {"ok": nodes_ok and edges_ok, "detail": "canonical provenance populated"}
    if graph_mode == "raw_scan_fallback":
        nodes_ok = all(node.canonical_entity_id is None and node.confidence_label is None for node in graph_nodes)
        edges_ok = all(edge.canonical_relation_id is None and edge.confidence_label is None and edge.inference_stage is None for edge in graph_edges)
        return {"ok": nodes_ok and edges_ok, "detail": "fallback provenance kept null"}
    if graph_mode == "empty":
        return {"ok": True, "detail": "no graph rows persisted"}
    return {"ok": False, "detail": "mixed graph provenance detected"}


def choose_simulation_node(graph_nodes: list[GraphNode], graph_edges: list[GraphEdge]) -> Optional[str]:
    if not graph_nodes:
        return None
    degree = {node.id: 0 for node in graph_nodes}
    for edge in graph_edges:
        degree[edge.source_node_id] = degree.get(edge.source_node_id, 0) + 1
        degree[edge.target_node_id] = degree.get(edge.target_node_id, 0) + 1
    ranked = sorted(
        graph_nodes,
        key=lambda node: (
            -degree.get(node.id, 0),
            0 if node.node_type in {"runtime", "database", "external", "component"} else 1,
            node.label,
        ),
    )
    return ranked[0].id if ranked else None


def verify_same_scan_consistency(
    scan: Optional[Scan],
    snapshot: Optional[ProjectModelSnapshot],
    graph_nodes: list[GraphNode],
    graph_edges: list[GraphEdge],
    summary_payload: dict,
    insights_payload: dict,
    code_peek_checks: dict,
) -> dict:
    scan_id = scan.id if scan is not None else None
    code_peek_matches_scan = all(
        payload.get("scan_id") == scan_id
        for payload in code_peek_checks.get("payloads", [])
        if isinstance(payload, dict)
    )
    return {
        "snapshot_matches_scan": snapshot is None or snapshot.scan_id == scan_id,
        "graph_nodes_match_scan": all(node.scan_id == scan_id for node in graph_nodes),
        "graph_edges_match_scan": all(edge.scan_id == scan_id for edge in graph_edges),
        "summary_matches_scan": summary_payload.get("scan_id") == scan_id if summary_payload else False,
        "insights_match_scan": insights_payload.get("scan_id") == scan_id if insights_payload else False,
        "code_peek_matches_scan": code_peek_matches_scan,
    }


def collect_anomalies(
    case: CaseConfig,
    scan_ok: bool,
    scan_payload: dict,
    snapshot: Optional[ProjectModelSnapshot],
    graph_ok: bool,
    graph_payload: dict,
    graph_nodes: list[GraphNode],
    graph_edges: list[GraphEdge],
    graph_mode: str,
    provenance_check: dict,
    simulation_response,
    summary_payload: dict,
    summary_ok: bool,
    insights_payload: dict,
    insights_ok: bool,
    code_peek_checks: dict,
    same_scan_consistency: dict,
) -> list[str]:
    anomalies: list[str] = []
    if not scan_ok:
        anomalies.append(f"scan failed: {scan_payload}")
    if snapshot is None:
        anomalies.append("no canonical snapshot row was created")
    elif snapshot.status in {"failed", "rejected_invalid"}:
        anomalies.append(f"canonical snapshot status={snapshot.status}")
    if graph_ok and graph_payload.get("node_count", 0) == 0:
        anomalies.append("graph endpoint returned an empty graph")
    if not provenance_check.get("ok"):
        anomalies.append(f"graph provenance check failed: {provenance_check.get('detail')}")
    if simulation_response is not None and simulation_response.status_code not in {201, 404}:
        anomalies.append(f"unexpected simulation response: {simulation_response.status_code}")
    if not insights_ok:
        anomalies.append("insights endpoint failed")
    if graph_mode == "canonical_snapshot" and summary_ok and summary_payload.get("confidence_summary", {}).get("overall_label") == "low":
        anomalies.append("summary confidence stayed low despite canonical-backed graph")
    if insights_ok and graph_mode == "empty" and insights_payload.get("insight_count", 0) > 3:
        anomalies.append("empty graph produced too many insights")
    if code_peek_checks.get("unexpected_failures"):
        anomalies.extend(code_peek_checks["unexpected_failures"])
    if case.force_invalid_snapshot and graph_mode != "raw_scan_fallback":
        anomalies.append("forced invalid snapshot did not drive raw fallback graph generation")
    if not all(same_scan_consistency.values()):
        anomalies.append(f"artifact scan consistency issue: {same_scan_consistency}")
    return anomalies


def verify_project_deleted(db, project_id: str) -> bool:
    return (
        db.query(Project).filter(Project.id == project_id).first() is None
        and db.query(Scan).filter(Scan.project_id == project_id).first() is None
        and db.query(ProjectModelSnapshot).filter(ProjectModelSnapshot.project_id == project_id).first() is None
        and db.query(GraphNode).filter(GraphNode.project_id == project_id).first() is None
        and db.query(GraphEdge).filter(GraphEdge.project_id == project_id).first() is None
        and db.query(SimulationRun).filter(SimulationRun.project_id == project_id).first() is None
    )


def build_comparison(results: list[dict]) -> list[dict]:
    comparison = []
    for result in results:
        comparison.append(
            {
                "case": result["name"],
                "codebase_type": result["codebase_type"],
                "scan_succeeded": result["scan_succeeded"],
                "snapshot_status": result["canonical_snapshot"]["status"],
                "graph_mode": result["graph"]["mode"],
                "simulation_mode": result["simulation"]["mode"],
                "summary_confidence": result["summary"]["confidence"],
                "insight_count": result["insights"]["count"],
                "code_peek_successes": result["code_peek"]["success_count"],
                "bug_discovered": result["bug_discovered"],
            }
        )
    return comparison


def run_code_peek_checks(
    client: TestClient,
    project_id: str,
    snapshot: Optional[ProjectModelSnapshot],
    graph_nodes: list[GraphNode],
    graph_edges: list[GraphEdge],
    insights_payload: dict,
    scan: Optional[Scan],
) -> dict:
    checks: list[tuple[str, dict, bool]] = []
    payloads: list[dict] = []
    unexpected_failures: list[str] = []

    if snapshot is not None and isinstance(snapshot.model_data, dict):
        evidence_ids = list((snapshot.model_data.get("evidence") or {}).keys())
        entity_ids = list((snapshot.model_data.get("components") or {}).keys())
        if evidence_ids:
            checks.append(("evidence", {"evidence_id": evidence_ids[0]}, True))
        if entity_ids:
            checks.append(("entity", {"entity_id": entity_ids[0]}, True))

    if insights_payload.get("insights"):
        checks.append(("insight", {"insight_id": insights_payload["insights"][0]["insight_id"]}, True))

    graph_node = next((node for node in graph_nodes if node.canonical_entity_id or (node.data or {}).get("entry_file")), None)
    if graph_node is not None:
        checks.append(("graph_node", {"graph_node_id": graph_node.id}, True))

    graph_edge = next((edge for edge in graph_edges if edge.canonical_relation_id), None)
    if graph_edge is not None:
        checks.append(("graph_edge", {"graph_edge_id": graph_edge.id}, True))

    if scan is not None:
        direct_file = None
        if scan.entry_points:
            direct_file = scan.entry_points[0]
        elif scan.key_files:
            direct_file = scan.key_files[0]
        elif scan.files:
            for item in scan.files:
                if isinstance(item, dict) and item.get("path"):
                    direct_file = item["path"]
                    break
        if direct_file:
            checks.append(("file", {"file_path": direct_file}, True))

    results: dict[str, dict] = {}
    success_count = 0
    for name, params, required in checks:
        response = client.get(f"/projects/{project_id}/code-peek", params=params)
        results[name] = {"status_code": response.status_code}
        if response.status_code == 200:
            payload = response.json()
            payloads.append(payload)
            results[name].update(
                {
                    "source_type": payload.get("source_type"),
                    "file_path": payload.get("file_path"),
                    "snippet_lines": [
                        payload.get("generated_from", {}).get("snippet_line_start"),
                        payload.get("generated_from", {}).get("snippet_line_end"),
                    ],
                    "snippet_non_empty": bool(payload.get("snippet_text")),
                }
            )
            success_count += 1
        else:
            results[name]["detail"] = response.json()
            if required:
                unexpected_failures.append(f"code peek {name} failed: {response.status_code}")

    return {
        "results": results,
        "success_count": success_count,
        "payloads": payloads,
        "unexpected_failures": unexpected_failures,
    }


if __name__ == "__main__":
    main()