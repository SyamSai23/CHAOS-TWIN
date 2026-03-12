from __future__ import annotations

import argparse
import io
import json
import shutil
import tempfile
import textwrap
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models.graph_edge import GraphEdge
from app.models.graph_node import GraphNode
from app.models.project import Project
from app.models.project_model_snapshot import ProjectModelSnapshot
from app.models.scan import Scan
from app.models.simulation_run import SimulationRun


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CaseConfig:
    name: str
    shape: str
    source_dir: Path
    stage: str
    stacks: list[str]
    notes: str = ""
    force_invalid_snapshot: bool = False
    expected_min_routes: int = 0
    expected_min_components: int = 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run backend multi-codebase evaluation matrix.")
    parser.add_argument("--stage", choices=["core", "broad", "all"], default="all")
    args = parser.parse_args()

    temp_root = Path(tempfile.mkdtemp(prefix="ct-backend-matrix-"))
    try:
        cases = build_cases(temp_root)
        client = TestClient(app)

        core_cases = [case for case in cases if case.stage == "core"]
        broad_cases = [case for case in cases if case.stage == "broad"]

        if args.stage == "core":
            broad_cases = []
        elif args.stage == "broad":
            core_cases = []

        core_results = [run_case(case, client) for case in core_cases]
        broad_results = [run_case(case, client) for case in broad_cases]
        all_results = core_results + broad_results

        output = build_report(core_results=core_results, broad_results=broad_results, all_results=all_results)
        print(json.dumps(output, indent=2, default=str))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def build_cases(temp_root: Path) -> list[CaseConfig]:
    express_api = create_express_api_repo(temp_root / "express-api")
    flask_api = create_flask_api_repo(temp_root / "flask-api")
    django_api = create_django_api_repo(temp_root / "django-api")
    react_only = create_react_only_repo(temp_root / "react-only")
    next_fullstack = create_next_fullstack_repo(temp_root / "next-fullstack")
    service_heavy = create_service_heavy_repo(temp_root / "service-heavy")
    integration_heavy = create_integration_heavy_repo(temp_root / "integration-heavy")
    monorepo_mixed = create_mixed_language_monorepo(temp_root / "mixed-language-monorepo")
    sparse_repo = create_sparse_repo(temp_root / "sparse-minimal")
    minimal_backend = create_minimal_fastapi_repo(temp_root / "minimal-fastapi")

    return [
        CaseConfig(
            name="backend_rest_api",
            shape="backend REST API",
            source_dir=REPO_ROOT / "backend",
            stage="core",
            stacks=["FastAPI", "Python"],
            expected_min_routes=10,
            expected_min_components=1,
        ),
        CaseConfig(
            name="frontend_only_workspace",
            shape="frontend-only app",
            source_dir=REPO_ROOT / "frontend",
            stage="core",
            stacks=["React", "TypeScript", "Vite"],
            expected_min_components=1,
        ),
        CaseConfig(
            name="full_stack_workspace",
            shape="full-stack workspace",
            source_dir=REPO_ROOT,
            stage="core",
            stacks=["FastAPI", "React", "TypeScript", "Python"],
            expected_min_routes=10,
            expected_min_components=2,
        ),
        CaseConfig(
            name="sparse_minimal_repo",
            shape="sparse/minimal repo",
            source_dir=sparse_repo,
            stage="core",
            stacks=["Python"],
        ),
        CaseConfig(
            name="forced_fallback_backend",
            shape="forced degraded fallback",
            source_dir=REPO_ROOT / "backend",
            stage="core",
            stacks=["FastAPI", "Python"],
            force_invalid_snapshot=True,
            expected_min_routes=10,
            expected_min_components=1,
        ),
        CaseConfig(
            name="express_api_repo",
            shape="backend REST API",
            source_dir=express_api,
            stage="broad",
            stacks=["Express", "JavaScript"],
            expected_min_routes=2,
            expected_min_components=1,
        ),
        CaseConfig(
            name="flask_api_repo",
            shape="backend REST API",
            source_dir=flask_api,
            stage="broad",
            stacks=["Flask", "Python"],
            expected_min_routes=2,
            expected_min_components=1,
        ),
        CaseConfig(
            name="django_api_repo",
            shape="backend REST API",
            source_dir=django_api,
            stage="broad",
            stacks=["Django", "Python"],
            expected_min_routes=2,
            expected_min_components=1,
        ),
        CaseConfig(
            name="react_only_repo",
            shape="frontend-only app",
            source_dir=react_only,
            stage="broad",
            stacks=["React", "TypeScript"],
            expected_min_components=1,
        ),
        CaseConfig(
            name="next_fullstack_repo",
            shape="full-stack app",
            source_dir=next_fullstack,
            stage="broad",
            stacks=["Next.js", "TypeScript"],
            expected_min_routes=1,
            expected_min_components=1,
        ),
        CaseConfig(
            name="service_heavy_repo",
            shape="service-heavy backend",
            source_dir=service_heavy,
            stage="broad",
            stacks=["Flask", "Python"],
            expected_min_routes=1,
            expected_min_components=1,
        ),
        CaseConfig(
            name="integration_heavy_repo",
            shape="integration-heavy repo",
            source_dir=integration_heavy,
            stage="broad",
            stacks=["FastAPI", "Python"],
            expected_min_routes=1,
            expected_min_components=1,
        ),
        CaseConfig(
            name="mixed_language_monorepo",
            shape="mixed-language monorepo",
            source_dir=monorepo_mixed,
            stage="broad",
            stacks=["Express", "Go", "React", "TypeScript", "JavaScript"],
            expected_min_routes=1,
            expected_min_components=2,
        ),
        CaseConfig(
            name="minimal_fastapi_repo",
            shape="minimal backend",
            source_dir=minimal_backend,
            stage="broad",
            stacks=["FastAPI", "Python"],
            expected_min_routes=1,
            expected_min_components=1,
        ),
    ]


def run_case(case: CaseConfig, client: TestClient) -> dict[str, Any]:
    db = SessionLocal()
    project_id: Optional[str] = None
    try:
        create_response = client.post(
            "/projects",
            json={
                "name": f"matrix-{case.name}-{uuid.uuid4().hex[:8]}",
                "path": str(case.source_dir),
            },
        )
        ensure_status(create_response, 201, f"{case.name} project creation")
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
        ensure_status(upload_response, 201, f"{case.name} upload")

        scan_response = client.post(f"/projects/{project_id}/scan")
        scan_ok = scan_response.status_code == 201
        scan_payload = scan_response.json()

        scan = (
            db.query(Scan)
            .filter(Scan.project_id == project_id)
            .order_by(Scan.created_at.desc())
            .first()
        )
        snapshot = latest_snapshot(db, project_id)
        snapshot_status = snapshot.status if snapshot is not None else "missing"

        if case.force_invalid_snapshot and snapshot is not None:
            snapshot.status = "completed"
            snapshot.model_data = {"broken": True}
            snapshot.validation_errors = []
            snapshot.error_message = None
            db.commit()
            snapshot_status = "created_then_corrupted_for_fallback"

        graph_response = client.post(f"/projects/{project_id}/graph")
        graph_payload = graph_response.json()
        graph_nodes = load_graph_nodes(db, project_id)
        graph_edges = load_graph_edges(db, project_id)
        graph_mode = detect_graph_mode(graph_nodes, graph_edges)
        provenance_check = verify_graph_provenance(graph_mode, graph_nodes, graph_edges)

        simulation = run_simulation(client, project_id, graph_nodes, graph_edges)

        summary_response = client.get(f"/projects/{project_id}/summary")
        summary_ok = summary_response.status_code == 200
        summary_payload = summary_response.json()

        insights_response = client.get(f"/projects/{project_id}/insights")
        insights_ok = insights_response.status_code == 200
        insights_payload = insights_response.json()

        code_peek = run_code_peek_checks(
            client=client,
            project_id=project_id,
            snapshot=snapshot,
            graph_nodes=graph_nodes,
            graph_edges=graph_edges,
            insights_payload=insights_payload if insights_ok else {},
            scan=scan,
        )

        route_metrics = run_route_flow_checks(client=client, project_id=project_id)

        same_scan_consistency = verify_same_scan_consistency(
            scan=scan,
            snapshot=snapshot,
            graph_nodes=graph_nodes,
            graph_edges=graph_edges,
            summary_payload=summary_payload,
            insights_payload=insights_payload,
            code_peek_checks=code_peek,
        )

        result: dict[str, Any] = {
            "repo_identifier": case.name,
            "repo_shape": case.shape,
            "stage": case.stage,
            "stacks": case.stacks,
            "scan_success": scan_ok,
            "scan_status": scan_payload.get("status") if scan_ok else scan_payload,
            "scan_id": scan.id if scan is not None else None,
            "route_count": int(len(scan.routes or [])) if scan is not None and isinstance(scan.routes, list) else 0,
            "component_count": int(len(scan.components or [])) if scan is not None and isinstance(scan.components, list) else 0,
            "canonical_snapshot_status": snapshot_status,
            "graph_mode": graph_mode,
            "graph_node_count": len(graph_nodes),
            "graph_edge_count": len(graph_edges),
            "graph_provenance": provenance_check,
            "simulation": simulation,
            "summary": {
                "status_code": summary_response.status_code,
                "confidence": summary_payload.get("confidence_summary", {}).get("overall_label") if summary_ok else None,
                "graph_provenance": summary_payload.get("graph_provenance") if summary_ok else None,
                "top_findings": len(summary_payload.get("top_findings", [])) if summary_ok else 0,
                "top_risks": len(summary_payload.get("top_risks", [])) if summary_ok else 0,
            },
            "insights": {
                "status_code": insights_response.status_code,
                "count": insights_payload.get("insight_count") if insights_ok else None,
                "counts_by_severity": insights_payload.get("counts_by_severity") if insights_ok else None,
            },
            "code_peek": code_peek,
            "request_flow": route_metrics,
            "same_scan_consistency": same_scan_consistency,
        }
        result["issues"] = collect_issues(
            case=case,
            scan=scan,
            snapshot=snapshot,
            graph_response=graph_response,
            graph_mode=graph_mode,
            provenance_check=provenance_check,
            simulation=simulation,
            summary_response=summary_response,
            summary_payload=summary_payload,
            insights_response=insights_response,
            insights_payload=insights_payload,
            code_peek=code_peek,
            route_metrics=route_metrics,
            same_scan_consistency=same_scan_consistency,
        )

        delete_response = client.delete(f"/projects/{project_id}")
        result["cleanup"] = {
            "deleted": delete_response.status_code == 200,
            "isolated": verify_project_deleted(db, project_id),
        }
        return result
    finally:
        if project_id is not None:
            db.expire_all()
            if db.query(Project).filter(Project.id == project_id).first() is not None:
                client.delete(f"/projects/{project_id}")
        db.close()


def build_report(core_results: list[dict[str, Any]], broad_results: list[dict[str, Any]], all_results: list[dict[str, Any]]) -> dict[str, Any]:
    issues = aggregate_issues(all_results)
    comparison = build_comparison_table(all_results)
    fixed_bugs: list[dict[str, Any]] = []
    return {
        "evaluation_coverage_summary": build_coverage_summary(core_results, broad_results, all_results),
        "comparison_table": comparison,
        "categorized_issue_log": issues,
        "bugs_fixed_during_evaluation": fixed_bugs,
        "remaining_weaknesses_and_patterns": summarize_patterns(issues),
        "recommendation": build_recommendation(all_results, issues),
        "raw_case_results": all_results,
    }


def build_coverage_summary(core_results: list[dict[str, Any]], broad_results: list[dict[str, Any]], all_results: list[dict[str, Any]]) -> dict[str, Any]:
    shapes = sorted({result["repo_shape"] for result in all_results})
    stacks = sorted({stack for result in all_results for stack in result.get("stacks", [])})
    successful_scans = sum(1 for result in all_results if result.get("scan_success"))
    successful_route_paths = sum(
        1 for result in all_results if result.get("request_flow", {}).get("detail_success_count", 0) > 0 or result.get("route_count", 0) == 0
    )
    return {
        "core_case_count": len(core_results),
        "broad_case_count": len(broad_results),
        "total_case_count": len(all_results),
        "repo_shapes": shapes,
        "stack_coverage": stacks,
        "scan_success_count": successful_scans,
        "request_flow_path_covered_count": successful_route_paths,
    }


def build_comparison_table(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for result in results:
        request_flow = result.get("request_flow", {})
        code_peek = result.get("code_peek", {})
        table.append(
            {
                "repo_identifier": result["repo_identifier"],
                "repo_shape": result["repo_shape"],
                "stage": result["stage"],
                "scan_success": result["scan_success"],
                "route_count": result["route_count"],
                "component_count": result["component_count"],
                "canonical_snapshot_status": result["canonical_snapshot_status"],
                "graph_mode": result["graph_mode"],
                "graph_node_count": result["graph_node_count"],
                "graph_edge_count": result["graph_edge_count"],
                "simulation_mode": result.get("simulation", {}).get("mode"),
                "summary_confidence": result.get("summary", {}).get("confidence"),
                "insight_count": result.get("insights", {}).get("count"),
                "code_peek_success_rate": code_peek.get("success_rate"),
                "request_flow_availability": request_flow.get("availability_ratio"),
                "request_flow_quality": request_flow.get("quality_label"),
                "issue_count": len(result.get("issues", [])),
            }
        )
    return table


def aggregate_issues(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "route extraction issues": [],
        "component boundary issues": [],
        "infra/datastore/external detection issues": [],
        "graph/provenance issues": [],
        "simulation issues": [],
        "summary/insight issues": [],
        "code-peek issues": [],
        "degraded/fallback behavior issues": [],
        "cleanup/lifecycle issues": [],
    }
    for result in results:
        for issue in result.get("issues", []):
            grouped.setdefault(issue["category"], []).append(issue)
    return {key: value for key, value in grouped.items() if value}


def summarize_patterns(grouped_issues: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    for category, issues in grouped_issues.items():
        affected = sorted({repo for issue in issues for repo in issue.get("affected_repos", [])})
        severities = sorted({issue.get("severity", "unknown") for issue in issues})
        patterns.append(
            {
                "category": category,
                "issue_count": len(issues),
                "affected_repo_count": len(affected),
                "severities": severities,
                "recurring_pattern": issues[0]["description"],
            }
        )
    return patterns


def build_recommendation(results: list[dict[str, Any]], grouped_issues: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    severe = [issue for issues in grouped_issues.values() for issue in issues if issue.get("severity") in {"high", "critical"}]
    medium = [issue for issues in grouped_issues.values() for issue in issues if issue.get("severity") == "medium"]
    route_path_failures = [
        result for result in results
        if result.get("route_count", 0) > 0 and result.get("request_flow", {}).get("detail_success_count", 0) == 0
    ]
    proceed = not severe and len(route_path_failures) <= 1
    rationale = "Backend is strong enough for the next frontend route-flow rendering step." if proceed else "Backend still has blocking evaluation findings that should be addressed before richer frontend route rendering."
    return {
        "proceed_to_frontend_route_flow_rendering": proceed,
        "high_or_critical_issue_count": len(severe),
        "medium_issue_count": len(medium),
        "route_path_failure_case_count": len(route_path_failures),
        "rationale": rationale,
    }


def collect_issues(
    case: CaseConfig,
    scan: Optional[Scan],
    snapshot: Optional[ProjectModelSnapshot],
    graph_response,
    graph_mode: str,
    provenance_check: dict[str, Any],
    simulation: dict[str, Any],
    summary_response,
    summary_payload: dict[str, Any],
    insights_response,
    insights_payload: dict[str, Any],
    code_peek: dict[str, Any],
    route_metrics: dict[str, Any],
    same_scan_consistency: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    def add_issue(
        category: str,
        description: str,
        severity: str,
        likely_root_cause: str,
        issue_type: str,
        fixed_or_deferred: str = "deferred",
    ) -> None:
        issues.append(
            {
                "category": category,
                "affected_repos": [case.name],
                "description": description,
                "severity": severity,
                "likely_root_cause": likely_root_cause,
                "issue_type": issue_type,
                "fixed_or_deferred": fixed_or_deferred,
            }
        )

    route_count = int(len(scan.routes or [])) if scan is not None and isinstance(scan.routes, list) else 0
    component_count = int(len(scan.components or [])) if scan is not None and isinstance(scan.components, list) else 0
    infra_count = sum(len(component.get("infrastructure") or []) for component in (scan.components or [])) if scan is not None else 0

    if not case.force_invalid_snapshot and snapshot is None:
        add_issue(
            "graph/provenance issues",
            "Canonical snapshot row was not created after scan.",
            "high",
            "Snapshot creation path may have failed silently during scan finalization.",
            "true bug",
        )
    if graph_response.status_code != 201:
        add_issue(
            "graph/provenance issues",
            f"Graph generation returned unexpected status {graph_response.status_code}.",
            "high",
            "Graph generation endpoint failed for this repo shape.",
            "true bug",
        )
    if not provenance_check.get("ok"):
        add_issue(
            "graph/provenance issues",
            f"Graph provenance validation failed: {provenance_check.get('detail')}.",
            "high",
            "Graph persistence emitted mixed or incomplete provenance fields.",
            "true bug",
        )
    if graph_mode == "empty" and route_count > 0:
        add_issue(
            "degraded/fallback behavior issues",
            "Non-empty repo produced an empty graph.",
            "medium",
            "Canonical and fallback graph generation both failed to retain entities.",
            "product semantics issue",
        )
    if component_count < case.expected_min_components:
        add_issue(
            "component boundary issues",
            f"Repo produced {component_count} detected components, below the expected minimum of {case.expected_min_components}.",
            "medium",
            "Component boundary heuristics missed the dominant roots for this repo layout.",
            "product semantics issue",
        )
    if route_count < case.expected_min_routes:
        add_issue(
            "route extraction issues",
            f"Repo produced {route_count} detected routes, below the expected minimum of {case.expected_min_routes}.",
            "medium",
            "Route extraction heuristics missed the framework-specific route declarations.",
            "product semantics issue",
        )
    if infra_count == 0 and case.shape in {"service-heavy backend", "integration-heavy repo"}:
        add_issue(
            "infra/datastore/external detection issues",
            "Infra-heavy repo produced no infrastructure detections.",
            "medium",
            "Infrastructure heuristics did not connect dependencies, code signals, or docker metadata.",
            "product semantics issue",
        )
    if simulation.get("status_code") not in {201, 404}:
        add_issue(
            "simulation issues",
            f"Simulation returned unexpected status {simulation.get('status_code')}.",
            "high",
            "Simulation endpoint did not degrade cleanly for this graph state.",
            "true bug",
        )
    if summary_response.status_code != 200:
        add_issue(
            "summary/insight issues",
            f"Summary endpoint returned unexpected status {summary_response.status_code}.",
            "high",
            "Summary generation failed for this repo shape.",
            "true bug",
        )
    if insights_response.status_code != 200:
        add_issue(
            "summary/insight issues",
            f"Insights endpoint returned unexpected status {insights_response.status_code}.",
            "high",
            "Insight generation failed for this repo shape.",
            "true bug",
        )
    if graph_mode == "canonical_snapshot" and summary_payload.get("confidence_summary", {}).get("overall_label") == "low":
        add_issue(
            "summary/insight issues",
            "Summary confidence remained low even with canonical-backed graph generation.",
            "medium",
            "Summary confidence calibration may be too pessimistic for supported graphs.",
            "product semantics issue",
        )
    if code_peek.get("success_rate") is not None and code_peek.get("success_rate", 0.0) < 0.6:
        add_issue(
            "code-peek issues",
            f"Code Peek success rate was only {code_peek.get('success_rate'):.2f}.",
            "medium",
            "Retriever fallbacks did not cover enough artifact types for this repo shape.",
            "product semantics issue",
        )
    if code_peek.get("unexpected_failures"):
        add_issue(
            "code-peek issues",
            "; ".join(code_peek["unexpected_failures"]),
            "high",
            "Code Peek endpoint failed on required retrieval paths.",
            "true bug",
        )
    if route_count > 0 and route_metrics.get("detail_success_count", 0) == 0:
        add_issue(
            "route extraction issues",
            "Route list succeeded but route detail/request_flow checks had zero successful samples.",
            "high",
            "Route-detail surface is not aligned with detected route identifiers or request_flow population.",
            "true bug",
        )
    elif route_count > 0 and route_metrics.get("availability_ratio", 0.0) < 0.5:
        add_issue(
            "route extraction issues",
            f"Request flow availability ratio was only {route_metrics.get('availability_ratio'):.2f}.",
            "medium",
            "Request-flow extraction remains sparse across sampled routes for this repo shape.",
            "product semantics issue",
        )
    if case.force_invalid_snapshot and graph_mode != "raw_scan_fallback":
        add_issue(
            "degraded/fallback behavior issues",
            "Forced invalid snapshot did not drive raw-scan fallback graph generation.",
            "high",
            "Fallback graph path is not activating when canonical snapshot hydration fails.",
            "true bug",
        )
    if case.shape == "sparse/minimal repo" and graph_mode == "empty":
        add_issue(
            "degraded/fallback behavior issues",
            "Sparse repo degrades to an empty graph and simulation remains unavailable.",
            "low",
            "This is current product behavior when canonical and fallback graph builders retain no entities.",
            "product semantics issue",
        )
    if case.force_invalid_snapshot and simulation.get("mode") == "basic":
        add_issue(
            "degraded/fallback behavior issues",
            "Forced fallback case dropped from semantic to basic simulation and lower-confidence summary.",
            "low",
            "This is expected degradation when canonical snapshot hydration fails and raw fallback data is used.",
            "product semantics issue",
        )
    if not all(same_scan_consistency.values()):
        add_issue(
            "cleanup/lifecycle issues",
            f"Artifact scan consistency mismatch detected: {same_scan_consistency}.",
            "high",
            "One or more downstream artifacts were generated against a stale scan id.",
            "true bug",
        )
    return issues


def run_simulation(client: TestClient, project_id: str, graph_nodes: list[GraphNode], graph_edges: list[GraphEdge]) -> dict[str, Any]:
    simulation_node_id = choose_simulation_node(graph_nodes, graph_edges)
    if simulation_node_id is None:
        response = client.post(f"/projects/{project_id}/simulate", json={"node_id": "missing-node"})
        return {
            "status_code": response.status_code,
            "mode": "unavailable",
            "detail": response.json(),
        }
    response = client.post(f"/projects/{project_id}/simulate", json={"node_id": simulation_node_id})
    payload = response.json()
    if response.status_code == 201:
        result = payload.get("result", {})
        return {
            "status_code": response.status_code,
            "mode": result.get("mode"),
            "severity": payload.get("severity"),
            "impacted_count": len(payload.get("impacted_nodes", [])),
        }
    return {
        "status_code": response.status_code,
        "mode": "unavailable",
        "detail": payload,
    }


def run_route_flow_checks(client: TestClient, project_id: str) -> dict[str, Any]:
    list_response = client.get(f"/projects/{project_id}/routes")
    if list_response.status_code != 200:
        return {
            "list_status_code": list_response.status_code,
            "route_total": 0,
            "detail_success_count": 0,
            "availability_ratio": 0.0,
            "quality_label": "unavailable",
            "warnings": [f"routes list failed with {list_response.status_code}"],
        }

    payload = list_response.json()
    route_items = flatten_route_items(payload)
    sampled_routes = route_items[: min(3, len(route_items))]
    detail_success_count = 0
    sampled_stage_counts: list[int] = []
    sampled_confidences: list[float] = []
    warnings: list[str] = []

    summary_available = sum(
        1 for route in route_items
        if isinstance(route.get("request_flow_summary"), dict) and route["request_flow_summary"].get("has_request_flow")
    )

    for route in sampled_routes:
        detail_response = client.get(f"/projects/{project_id}/routes/{route['id']}")
        if detail_response.status_code != 200:
            warnings.append(f"route detail failed for {route['id']}: {detail_response.status_code}")
            continue
        detail_payload = detail_response.json()
        request_flow = detail_payload.get("request_flow") or {}
        stages = request_flow.get("stages") or []
        if stages:
            detail_success_count += 1
            sampled_stage_counts.append(len(stages))
            confidence = request_flow.get("confidence")
            if confidence is not None:
                sampled_confidences.append(float(confidence))
        else:
            warnings.append(f"route detail returned no request_flow stages for {route['id']}")

    route_total = len(route_items)
    availability_ratio = round(summary_available / route_total, 2) if route_total else 1.0
    average_stage_count = round(sum(sampled_stage_counts) / len(sampled_stage_counts), 2) if sampled_stage_counts else 0.0
    average_confidence = round(sum(sampled_confidences) / len(sampled_confidences), 2) if sampled_confidences else None

    quality_label = "strong"
    if route_total == 0:
        quality_label = "not_applicable"
    elif detail_success_count == 0:
        quality_label = "failed"
    elif availability_ratio < 0.5 or average_stage_count < 3:
        quality_label = "weak"
    elif availability_ratio < 0.8:
        quality_label = "mixed"

    return {
        "list_status_code": list_response.status_code,
        "route_total": route_total,
        "summary_available_count": summary_available,
        "detail_success_count": detail_success_count,
        "availability_ratio": availability_ratio,
        "average_stage_count": average_stage_count,
        "average_confidence": average_confidence,
        "quality_label": quality_label,
        "warnings": warnings,
    }


def flatten_route_items(routes_payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for group in routes_payload.get("by_component", []):
        for route in group.get("routes") or []:
            if isinstance(route, dict):
                items.append(route)
    return items


def latest_snapshot(db, project_id: str) -> Optional[ProjectModelSnapshot]:
    return (
        db.query(ProjectModelSnapshot)
        .filter(ProjectModelSnapshot.project_id == project_id)
        .order_by(ProjectModelSnapshot.created_at.desc())
        .first()
    )


def load_graph_nodes(db, project_id: str) -> list[GraphNode]:
    return (
        db.query(GraphNode)
        .filter(GraphNode.project_id == project_id)
        .order_by(GraphNode.created_at.asc())
        .all()
    )


def load_graph_edges(db, project_id: str) -> list[GraphEdge]:
    return (
        db.query(GraphEdge)
        .filter(GraphEdge.project_id == project_id)
        .order_by(GraphEdge.created_at.asc())
        .all()
    )


def ensure_status(response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise RuntimeError(f"{label} failed: {response.status_code} {response.text}")


def build_zip_bytes(source_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            archive.write(path, path.relative_to(source_dir))
    return buffer.getvalue()


def detect_graph_mode(graph_nodes: list[GraphNode], graph_edges: list[GraphEdge]) -> str:
    sources: list[str] = []
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


def verify_graph_provenance(graph_mode: str, graph_nodes: list[GraphNode], graph_edges: list[GraphEdge]) -> dict[str, Any]:
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
    summary_payload: dict[str, Any],
    insights_payload: dict[str, Any],
    code_peek_checks: dict[str, Any],
) -> dict[str, bool]:
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


def verify_project_deleted(db, project_id: str) -> bool:
    return (
        db.query(Project).filter(Project.id == project_id).first() is None
        and db.query(Scan).filter(Scan.project_id == project_id).first() is None
        and db.query(ProjectModelSnapshot).filter(ProjectModelSnapshot.project_id == project_id).first() is None
        and db.query(GraphNode).filter(GraphNode.project_id == project_id).first() is None
        and db.query(GraphEdge).filter(GraphEdge.project_id == project_id).first() is None
        and db.query(SimulationRun).filter(SimulationRun.project_id == project_id).first() is None
    )


def run_code_peek_checks(
    client: TestClient,
    project_id: str,
    snapshot: Optional[ProjectModelSnapshot],
    graph_nodes: list[GraphNode],
    graph_edges: list[GraphEdge],
    insights_payload: dict[str, Any],
    scan: Optional[Scan],
) -> dict[str, Any]:
    checks: list[tuple[str, dict[str, Any], bool]] = []
    payloads: list[dict[str, Any]] = []
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

    results: dict[str, dict[str, Any]] = {}
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
                    "snippet_non_empty": bool(payload.get("snippet_text")),
                }
            )
            success_count += 1
        else:
            results[name]["detail"] = response.json()
            if required:
                unexpected_failures.append(f"code peek {name} failed: {response.status_code}")

    total = len(checks)
    return {
        "results": results,
        "success_count": success_count,
        "total_checks": total,
        "success_rate": round(success_count / total, 2) if total else None,
        "payloads": payloads,
        "unexpected_failures": unexpected_failures,
    }


def create_express_api_repo(root: Path) -> Path:
    write_text(
        root / "package.json",
        '{"name": "express-api", "version": "1.0.0", "dependencies": {"express": "^4.19.2"}}',
    )
    write_text(
        root / "src" / "server.js",
        """
        const express = require('express');
        const routes = require('./routes');

        const app = express();
        app.use('/api/v1', routes);
        app.listen(3000);
        """,
    )
    write_text(
        root / "src" / "routes.js",
        """
        const express = require('express');
        const ensureAuth = require('./middleware/ensureAuth');
        const validateSpot = require('./middleware/validateSpot');
        const SessionController = require('./controllers/SessionController');
        const SpotController = require('./controllers/SpotController');

        const router = express.Router();
        router.post('/sessions', SessionController.store);
        router.post('/spots', ensureAuth, validateSpot, SpotController.store);

        module.exports = router;
        """,
    )
    write_text(root / "src" / "controllers" / "SessionController.js", "exports.store = (req, res) => res.json({ ok: true });")
    write_text(root / "src" / "controllers" / "SpotController.js", "exports.store = (req, res) => res.status(201).json({ created: true });")
    write_text(root / "src" / "middleware" / "ensureAuth.js", "module.exports = function ensureAuth(req, res, next) { return next(); };")
    write_text(root / "src" / "middleware" / "validateSpot.js", "module.exports = function validateSpot(req, res, next) { return next(); };")
    return root


def create_flask_api_repo(root: Path) -> Path:
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


def create_django_api_repo(root: Path) -> Path:
    write_text(root / "requirements.txt", "django\n")
    write_text(root / "manage.py", "print('manage')")
    write_text(
        root / "app" / "urls.py",
        """
        from django.urls import path
        from .views import list_posts, create_post

        urlpatterns = [
            path('posts/', list_posts),
            path('posts/create/', create_post),
        ]
        """,
    )
    write_text(
        root / "app" / "views.py",
        """
        def list_posts(request):
            return {'posts': []}

        def create_post(request):
            return {'created': True}
        """,
    )
    return root


def create_react_only_repo(root: Path) -> Path:
    write_text(root / "package.json", '{"name": "react-only", "version": "1.0.0"}')
    write_text(root / "vite.config.ts", "export default {};\n")
    write_text(root / "src" / "main.tsx", "import { App } from './App'; console.log(App);\n")
    write_text(root / "src" / "App.tsx", "export function App() { return <div>Hello</div>; }\n")
    return root


def create_next_fullstack_repo(root: Path) -> Path:
    write_text(root / "package.json", '{"name": "next-fullstack", "dependencies": {"next": "14.0.0", "react": "18.0.0"}}')
    write_text(root / "pages" / "index.tsx", "export default function Home() { return <div>Home</div>; }\n")
    write_text(
        root / "pages" / "api" / "health.ts",
        """
        export default function health(req, res) {
          return res.status(200).json({ ok: true });
        }
        """,
    )
    return root


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
          postgres:
            image: postgres:16
          redis:
            image: redis:7
        """,
    )
    write_text(root / "gateway" / "requirements.txt", "flask\nrequests\nredis\npsycopg\n")
    write_text(
        root / "gateway" / "app.py",
        """
        from flask import Blueprint, Flask
        from gateway.services.user_service import create_user_account

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
        root / "gateway" / "services" / "user_service.py",
        """
        from gateway.integrations.billing_gateway import create_customer
        from gateway.repositories.user_repository import save_user

        def create_user_account(payload):
            customer = create_customer(payload)
            return save_user(payload, customer)
        """,
    )
    write_text(
        root / "gateway" / "repositories" / "user_repository.py",
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
        root / "gateway" / "integrations" / "billing_gateway.py",
        """
        import requests

        def create_customer(payload):
            requests.post('https://billing.example.com/customers', json=payload)
            return {'id': 'cus_123'}
        """,
    )
    return root


def create_integration_heavy_repo(root: Path) -> Path:
    write_text(root / "requirements.txt", "fastapi\nboto3\nsendgrid\nstripe\n")
    write_text(
        root / "app.py",
        """
        from fastapi import FastAPI
        import boto3
        import stripe
        from sendgrid import SendGridAPIClient

        app = FastAPI()

        @app.post('/notify')
        def notify():
            boto3.client('s3')
            SendGridAPIClient('token')
            stripe.api_key = 'secret'
            return {'ok': True}
        """,
    )
    return root


def create_mixed_language_monorepo(root: Path) -> Path:
    write_text(root / "web" / "package.json", '{"name": "web", "version": "1.0.0"}')
    write_text(root / "web" / "src" / "main.tsx", "console.log('web');\n")
    write_text(root / "api" / "package.json", '{"name": "api", "dependencies": {"express": "^4.19.2"}}')
    write_text(root / "api" / "src" / "server.js", "const express = require('express'); const app = express(); app.get('/health', (req,res)=>res.json({ok:true})); app.listen(3000);\n")
    write_text(root / "worker" / "go.mod", "module worker\n\ngo 1.22\n")
    write_text(root / "worker" / "main.go", "package main\nfunc main() {}\n")
    return root


def create_minimal_fastapi_repo(root: Path) -> Path:
    write_text(root / "requirements.txt", "fastapi\nuvicorn\n")
    write_text(
        root / "main.py",
        """
        from fastapi import FastAPI

        app = FastAPI()

        @app.get('/health')
        def health():
            return {'ok': True}
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