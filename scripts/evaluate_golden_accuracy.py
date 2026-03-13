from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import textwrap
import uuid
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.route_analysis import RouteAnalysis  # noqa: E402
from app.services.identity import make_route_id  # noqa: E402
from app.services.route_analysis_utils import ensure_route_analysis_signature  # noqa: E402
from app.services.scanner_v3 import run_full_scan  # noqa: E402


CORPUS_PATH = REPO_ROOT / "scripts" / "golden_set" / "corpus.v1.json"
TARGET_ORDER = [
    "route_extraction",
    "component_boundaries",
    "infra_detection",
    "request_flow_quality",
    "sequence_quality",
    "best_target_quality",
]


@dataclass
class GeneratedCaseContext:
    root: Path
    created_projects: list[str]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CHAOS-TWIN golden-set accuracy evaluation.")
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    temp_root = Path(tempfile.mkdtemp(prefix="ct-golden-eval-"))
    client = TestClient(app)

    try:
        case_results = [evaluate_case(case, temp_root=temp_root, client=client) for case in corpus["cases"]]
        report = build_report(corpus_version=corpus["version"], case_results=case_results)

        if args.json_output:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")

        if args.markdown_output:
            args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_output.write_text(render_markdown_report(report), encoding="utf-8")

        print(json.dumps(report, indent=2))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def evaluate_case(case: dict[str, Any], temp_root: Path, client: TestClient) -> dict[str, Any]:
    case_root = materialize_case_source(case, temp_root)
    scan_result = run_full_scan(str(case_root))
    project_id: Optional[str] = None

    target_results: dict[str, dict[str, Any]] = {}
    for target_name in TARGET_ORDER:
        if target_name not in case.get("targets", {}):
            continue

        if target_name == "sequence_quality":
            if project_id is None:
                project_id = create_scanned_project(client, case["id"], case_root)
            target_results[target_name] = compare_sequence_quality(
                case=case,
                project_id=project_id,
                expectation=case["targets"][target_name],
                client=client,
            )
            continue

        if target_name == "route_extraction":
            target_results[target_name] = compare_route_extraction(case, scan_result, case["targets"][target_name])
        elif target_name == "component_boundaries":
            target_results[target_name] = compare_component_boundaries(case, scan_result, case["targets"][target_name])
        elif target_name == "infra_detection":
            target_results[target_name] = compare_infra_detection(case, scan_result, case["targets"][target_name])
        elif target_name == "request_flow_quality":
            target_results[target_name] = compare_request_flow_quality(case, scan_result, case["targets"][target_name])
        elif target_name == "best_target_quality":
            target_results[target_name] = compare_best_target_quality(case, scan_result, case["targets"][target_name])

    if project_id is not None:
        delete_project_quietly(client, project_id)

    case_score = average([result["score"] for result in target_results.values()])
    return {
        "case_id": case["id"],
        "repo_shape": case["repo_shape"],
        "source": case["source"],
        "score": round(case_score, 4),
        "target_results": target_results,
    }


def build_report(corpus_version: str, case_results: list[dict[str, Any]]) -> dict[str, Any]:
    by_target_scores: dict[str, list[float]] = defaultdict(list)
    failure_counter: Counter[str] = Counter()
    mismatch_counter: Counter[str] = Counter()
    issue_examples: dict[str, list[str]] = defaultdict(list)

    total_checks = 0
    passed_checks = 0

    for case in case_results:
        for target_name, result in case["target_results"].items():
            by_target_scores[target_name].append(result["score"])
            total_checks += result["summary"]["total_checks"]
            passed_checks += result["summary"]["passed_checks"]
            for mismatch in result["mismatches"]:
                failure_counter[mismatch["classification"]] += 1
                mismatch_counter[mismatch["code"]] += 1
                example = f"{case['case_id']}::{target_name}::{mismatch['message']}"
                if len(issue_examples[mismatch["code"]]) < 3:
                    issue_examples[mismatch["code"]].append(example)

    target_summary = {
        target_name: {
            "score": round(average(scores), 4),
            "case_count": len(scores),
        }
        for target_name, scores in by_target_scores.items()
    }

    sorted_targets = sorted(target_summary.items(), key=lambda item: item[1]["score"], reverse=True)
    strongest = [
        {
            "target": target,
            "score": summary["score"],
            "reason": strength_reason(target, summary["score"]),
        }
        for target, summary in sorted_targets[:3]
    ]
    weakest = [] if not mismatch_counter else [
        {
            "target": target,
            "score": summary["score"],
            "reason": weakness_reason(target, summary["score"], mismatch_counter),
        }
        for target, summary in sorted(sorted_targets, key=lambda item: item[1]["score"])[:3]
    ]

    recurring_patterns = [
        {
            "code": code,
            "count": count,
            "examples": issue_examples.get(code, []),
        }
        for code, count in mismatch_counter.most_common(6)
    ]

    report = {
        "corpus_version": corpus_version,
        "overall": {
            "score": round(passed_checks / total_checks, 4) if total_checks else 1.0,
            "total_checks": total_checks,
            "passed_checks": passed_checks,
            "failed_checks": total_checks - passed_checks,
            "failure_kinds": dict(failure_counter),
            "by_target": target_summary,
        },
        "cases": case_results,
        "strongest_areas": strongest,
        "weakest_areas": weakest,
        "recurring_error_patterns": recurring_patterns,
        "recommended_next_fixes": recommend_next_fixes(mismatch_counter),
    }
    return report


def compare_route_extraction(case: dict[str, Any], scan_result: dict[str, Any], expectation: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    routes = list(scan_result.get("routes") or [])
    route_index = {(route.get("method"), route.get("path"), route.get("file")): route for route in routes}
    classification = expectation.get("classification", "accuracy")

    if "min_total" in expectation:
        checks.append(make_check(
            passed=len(routes) >= expectation["min_total"],
            code="route_total_below_min",
            message=f"route count {len(routes)} >= {expectation['min_total']}",
            classification=classification,
            actual=len(routes),
            expected=expectation["min_total"],
        ))
    if "exact_total" in expectation:
        checks.append(make_check(
            passed=len(routes) == expectation["exact_total"],
            code="route_total_mismatch",
            message=f"route count {len(routes)} == {expectation['exact_total']}",
            classification=classification,
            actual=len(routes),
            expected=expectation["exact_total"],
        ))

    for expected_route in expectation.get("expected_routes", []):
        actual = route_index.get(route_key(expected_route))
        if actual is None:
            checks.append(make_check(
                passed=False,
                code="route_missing",
                message=f"missing route {expected_route['method']} {expected_route['path']} ({expected_route['file']})",
                classification=classification,
                expected=expected_route,
            ))
            continue

        checks.extend(compare_route_fields(actual, expected_route, classification))

    for forbidden in expectation.get("forbidden_routes", []):
        actual = route_index.get(route_key(forbidden))
        checks.append(make_check(
            passed=actual is None,
            code="route_forbidden_present",
            message=f"forbidden route absent: {forbidden['method']} {forbidden['path']} ({forbidden['file']})",
            classification=classification,
            actual=summarize_route(actual) if actual else None,
            expected=forbidden,
        ))

    return finalize_target_result(checks)


def compare_component_boundaries(case: dict[str, Any], scan_result: dict[str, Any], expectation: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    components = list(scan_result.get("components") or [])
    classification = expectation.get("classification", "accuracy")

    if "exact_total" in expectation:
        checks.append(make_check(
            passed=len(components) == expectation["exact_total"],
            code="component_total_mismatch",
            message=f"component count {len(components)} == {expectation['exact_total']}",
            classification=classification,
            actual=len(components),
            expected=expectation["exact_total"],
        ))

    for expected_component in expectation.get("expected_components", []):
        actual = find_component(components, expected_component)
        if actual is None:
            checks.append(make_check(
                passed=False,
                code="component_missing",
                message=f"missing component matching {component_locator_label(expected_component)}",
                classification=classification,
                expected=expected_component,
            ))
            continue

        checks.extend(compare_component_fields(actual, expected_component, classification))

    return finalize_target_result(checks)


def compare_infra_detection(case: dict[str, Any], scan_result: dict[str, Any], expectation: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    components = list(scan_result.get("components") or [])
    classification = expectation.get("classification", "accuracy")

    for component_expectation in expectation.get("components", []):
        actual_component = locate_component(components, component_expectation)
        if actual_component is None:
            checks.append(make_check(
                passed=False,
                code="infra_component_missing",
                message=f"missing infra component {component_locator_label(component_expectation)}",
                classification=classification,
                expected=component_expectation,
            ))
            continue

        infra_items = {item.get("name"): item for item in actual_component.get("infrastructure", [])}
        if component_expectation.get("exact_empty"):
            checks.append(make_check(
                passed=len(infra_items) == 0,
                code="infra_not_empty",
                message=f"component {actual_component.get('name')} has no infrastructure items",
                classification=classification,
                actual=sorted(infra_items),
                expected=[],
            ))

        for entity_expectation in component_expectation.get("entities", []):
            entity_name = entity_expectation["name"]
            actual_entity = infra_items.get(entity_name)
            must_be_present = entity_expectation.get("must_be_present", True)
            checks.append(make_check(
                passed=(actual_entity is not None) if must_be_present else (actual_entity is None),
                code="infra_presence_mismatch" if must_be_present else "infra_unexpected_entity",
                message=(
                    f"infra entity present: {entity_name}" if must_be_present else f"infra entity absent: {entity_name}"
                ),
                classification=classification,
                actual=summarize_infra(actual_entity) if actual_entity else None,
                expected=entity_expectation,
            ))
            if actual_entity is None:
                continue

            if "kind" in entity_expectation:
                checks.append(make_check(
                    passed=actual_entity.get("kind") == entity_expectation["kind"],
                    code="infra_kind_mismatch",
                    message=f"infra kind for {entity_name} == {entity_expectation['kind']}",
                    classification=classification,
                    actual=actual_entity.get("kind"),
                    expected=entity_expectation["kind"],
                ))
            if "entity_type" in entity_expectation:
                checks.append(make_check(
                    passed=actual_entity.get("entity_type") == entity_expectation["entity_type"],
                    code="infra_entity_type_mismatch",
                    message=f"infra entity_type for {entity_name} == {entity_expectation['entity_type']}",
                    classification=classification,
                    actual=actual_entity.get("entity_type"),
                    expected=entity_expectation["entity_type"],
                ))

    return finalize_target_result(checks)


def compare_request_flow_quality(case: dict[str, Any], scan_result: dict[str, Any], expectation: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    route_index = {(route.get("method"), route.get("path"), route.get("file")): route for route in scan_result.get("routes") or []}
    classification = expectation.get("classification", "accuracy")

    for route_expectation in expectation.get("routes", []):
        actual_route = route_index.get(route_key(route_expectation["route"]))
        route_label = route_locator_label(route_expectation["route"])
        if actual_route is None:
            checks.append(make_check(
                passed=False,
                code="request_flow_route_missing",
                message=f"request_flow route present: {route_label}",
                classification=classification,
                expected=route_expectation,
            ))
            continue

        flow = actual_route.get("request_flow") or {}
        stages = list(flow.get("stages") or [])
        stage_types = [stage.get("stage_type") for stage in stages]
        inferred_steps = sum(1 for stage in stages if stage.get("is_inferred"))

        checks.append(make_check(
            passed=len(stages) > 0,
            code="request_flow_missing",
            message=f"request_flow exists for {route_label}",
            classification=classification,
            actual=stage_types,
            expected="non-empty request_flow",
        ))
        if not stages:
            continue

        if "first_stage_type" in route_expectation:
            checks.append(make_check(
                passed=stage_types[0] == route_expectation["first_stage_type"],
                code="request_flow_first_stage_mismatch",
                message=f"first request_flow stage for {route_label} == {route_expectation['first_stage_type']}",
                classification=classification,
                actual=stage_types[0],
                expected=route_expectation["first_stage_type"],
            ))
        if "last_stage_type" in route_expectation:
            checks.append(make_check(
                passed=stage_types[-1] == route_expectation["last_stage_type"],
                code="request_flow_last_stage_mismatch",
                message=f"last request_flow stage for {route_label} == {route_expectation['last_stage_type']}",
                classification=classification,
                actual=stage_types[-1],
                expected=route_expectation["last_stage_type"],
            ))
        for stage_type in route_expectation.get("required_stage_types", []):
            checks.append(make_check(
                passed=stage_type in stage_types,
                code="request_flow_missing_stage",
                message=f"request_flow contains stage {stage_type} for {route_label}",
                classification=classification,
                actual=stage_types,
                expected=stage_type,
            ))
        ordered = route_expectation.get("required_stage_types_in_order", [])
        if ordered:
            checks.append(make_check(
                passed=is_subsequence(ordered, stage_types),
                code="request_flow_order_mismatch",
                message=f"request_flow preserves expected stage order for {route_label}",
                classification=classification,
                actual=stage_types,
                expected=ordered,
            ))
        if "min_confidence" in route_expectation:
            checks.append(make_check(
                passed=(flow.get("confidence") or 0) >= route_expectation["min_confidence"],
                code="request_flow_confidence_too_low",
                message=f"request_flow confidence for {route_label} >= {route_expectation['min_confidence']}",
                classification=classification,
                actual=flow.get("confidence"),
                expected=route_expectation["min_confidence"],
            ))
        if "max_inferred_steps" in route_expectation:
            checks.append(make_check(
                passed=inferred_steps <= route_expectation["max_inferred_steps"],
                code="request_flow_too_many_inferred",
                message=f"request_flow inferred steps for {route_label} <= {route_expectation['max_inferred_steps']}",
                classification=classification,
                actual=inferred_steps,
                expected=route_expectation["max_inferred_steps"],
            ))

    return finalize_target_result(checks)


def compare_sequence_quality(case: dict[str, Any], project_id: str, expectation: dict[str, Any], client: TestClient) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    classification = expectation.get("classification", "accuracy")
    route_expectations = expectation.get("routes", [])
    route_index: dict[tuple[str | None, str | None, str | None], dict[str, Any]] = {}
    if any("route_body" not in item for item in route_expectations):
        routes_payload = fetch_routes(client, project_id)
        route_index = {
            (route.get("method"), route.get("path"), route.get("file")): route
            for group in routes_payload.get("by_component", [])
            for route in group.get("routes") or []
        }

    for route_expectation in route_expectations:
        route_locator = route_expectation.get("route") or route_expectation.get("route_body") or {}
        route_label = route_locator_label(route_locator)
        actual_route = dict(route_expectation.get("route_body") or {})

        if route_expectation.get("stored_route_analysis"):
            seed_route_analysis(
                project_id=project_id,
                route=actual_route or dict(route_locator),
                analysis_data=route_expectation["stored_route_analysis"],
            )

        if not actual_route:
            actual_route = route_index.get(route_key(route_locator)) or {}

        if not actual_route:
            checks.append(make_check(
                passed=False,
                code="sequence_route_missing",
                message=f"sequence route present: {route_label}",
                classification=classification,
                expected=route_locator,
            ))
            continue

        sequence = generate_sequence(client, project_id, actual_route)
        metadata = sequence.get("metadata") or {}
        messages = list(sequence.get("messages") or [])
        participants = [participant.get("label") for participant in sequence.get("participants") or []]
        message_labels = [message.get("label") for message in messages]
        anchored_messages = sum(1 for message in messages if (message.get("code_anchor") or {}).get("file_path"))
        warnings = list(metadata.get("warnings") or [])

        if "expected_sequence_source" in route_expectation:
            checks.append(make_check(
                passed=metadata.get("sequence_source") == route_expectation["expected_sequence_source"],
                code="sequence_source_mismatch",
                message=f"sequence source for {route_label} == {route_expectation['expected_sequence_source']}",
                classification=classification,
                actual=metadata.get("sequence_source"),
                expected=route_expectation["expected_sequence_source"],
            ))
        if "expected_degraded" in route_expectation:
            checks.append(make_check(
                passed=bool(metadata.get("degraded")) == route_expectation["expected_degraded"],
                code="sequence_degraded_flag_mismatch",
                message=f"sequence degraded flag for {route_label} == {route_expectation['expected_degraded']}",
                classification=classification,
                actual=bool(metadata.get("degraded")),
                expected=route_expectation["expected_degraded"],
            ))
        if "min_anchored_messages" in route_expectation:
            checks.append(make_check(
                passed=anchored_messages >= route_expectation["min_anchored_messages"],
                code="sequence_anchor_coverage_too_low",
                message=f"sequence anchored messages for {route_label} >= {route_expectation['min_anchored_messages']}",
                classification=classification,
                actual=anchored_messages,
                expected=route_expectation["min_anchored_messages"],
            ))
        for participant in route_expectation.get("required_participants", []):
            checks.append(make_check(
                passed=participant in participants,
                code="sequence_missing_participant",
                message=f"sequence contains participant {participant} for {route_label}",
                classification=classification,
                actual=participants,
                expected=participant,
            ))
        for label in route_expectation.get("required_message_labels", []):
            checks.append(make_check(
                passed=label in message_labels,
                code="sequence_missing_message",
                message=f"sequence contains message '{label}' for {route_label}",
                classification=classification,
                actual=message_labels,
                expected=label,
            ))
        for warning_substring in route_expectation.get("required_warning_substrings", []):
            checks.append(make_check(
                passed=any(warning_substring in warning for warning in warnings),
                code="sequence_warning_missing",
                message=f"sequence warnings contain '{warning_substring}' for {route_label}",
                classification=classification,
                actual=warnings,
                expected=warning_substring,
            ))

    return finalize_target_result(checks)


def compare_best_target_quality(case: dict[str, Any], scan_result: dict[str, Any], expectation: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    classification = expectation.get("classification", "accuracy")
    routes = list(scan_result.get("routes") or [])
    route_index = {(route.get("method"), route.get("path"), route.get("file")): route for route in routes}
    components = list(scan_result.get("components") or [])

    for target in expectation.get("component_targets", []):
        component = locate_component(components, target["component"])
        checks.extend(compare_best_target(
            actual=(component or {}).get("best_target") if component else None,
            expectation=target,
            label=f"component {component_locator_label(target['component'])}",
            classification=classification,
        ))

    for target in expectation.get("route_targets", []):
        route = route_index.get(route_key(target["route"]))
        checks.extend(compare_best_target(
            actual=(route or {}).get("best_target") if route else None,
            expectation=target,
            label=f"route {route_locator_label(target['route'])}",
            classification=classification,
        ))

    for target in expectation.get("infra_targets", []):
        component = locate_component(components, target["component"])
        entity = None
        if component:
            entity = next((item for item in component.get("infrastructure", []) if item.get("name") == target["entity_name"]), None)
        checks.extend(compare_best_target(
            actual=(entity or {}).get("best_target") if entity else None,
            expectation=target,
            label=f"infra {target['entity_name']} in {component_locator_label(target['component'])}",
            classification=classification,
        ))

    for target in expectation.get("request_flow_stage_targets", []):
        route = route_index.get(route_key(target["route"]))
        stage = find_request_flow_stage(route, target) if route else None
        checks.extend(compare_flow_stage_target(stage, target, classification))

    return finalize_target_result(checks)


def compare_route_fields(actual: dict[str, Any], expected: dict[str, Any], classification: str) -> list[dict[str, Any]]:
    checks = []
    for field in ["handler_function", "controller_name", "router_prefix"]:
        if field not in expected:
            continue
        checks.append(make_check(
            passed=actual.get(field) == expected[field],
            code="route_field_mismatch",
            message=f"route field {field} matches for {expected['method']} {expected['path']}",
            classification=classification,
            actual=actual.get(field),
            expected=expected[field],
        ))
    for field in ["auth_hints_all", "validation_hints_all"]:
        if field not in expected:
            continue
        actual_values = actual.get(field.replace("_all", ""), [])
        for item in expected[field]:
            checks.append(make_check(
                passed=item in actual_values,
                code="route_hint_missing",
                message=f"route includes {field} item {item} for {expected['method']} {expected['path']}",
                classification=classification,
                actual=actual_values,
                expected=item,
            ))
    return checks


def compare_component_fields(actual: dict[str, Any], expected: dict[str, Any], classification: str) -> list[dict[str, Any]]:
    checks = []
    for field in ["name", "type"]:
        if field not in expected:
            continue
        checks.append(make_check(
            passed=actual.get(field) == expected[field],
            code="component_field_mismatch",
            message=f"component field {field} matches for {component_locator_label(expected)}",
            classification=classification,
            actual=actual.get(field),
            expected=expected[field],
        ))
    if "root_path_any" in expected:
        checks.append(make_check(
            passed=actual.get("root_path") in expected["root_path_any"],
            code="component_root_path_mismatch",
            message=f"component root_path matches allowed set for {component_locator_label(expected)}",
            classification=classification,
            actual=actual.get("root_path"),
            expected=expected["root_path_any"],
        ))
    if "entry_file_any" in expected:
        checks.append(make_check(
            passed=actual.get("entry_file") in expected["entry_file_any"],
            code="component_entry_file_mismatch",
            message=f"component entry_file matches allowed set for {component_locator_label(expected)}",
            classification=classification,
            actual=actual.get("entry_file"),
            expected=expected["entry_file_any"],
        ))
    for role in expected.get("roles_all", []):
        checks.append(make_check(
            passed=role in actual.get("detected_roles", []),
            code="component_role_missing",
            message=f"component contains role {role} for {component_locator_label(expected)}",
            classification=classification,
            actual=actual.get("detected_roles", []),
            expected=role,
        ))
    return checks


def compare_best_target(actual: Optional[dict[str, Any]], expectation: dict[str, Any], label: str, classification: str) -> list[dict[str, Any]]:
    checks = [make_check(
        passed=actual is not None,
        code="best_target_missing",
        message=f"best target exists for {label}",
        classification=classification,
        actual=actual,
        expected=expectation,
    )]
    if actual is None:
        return checks

    if "expected_file" in expectation:
        checks.append(make_check(
            passed=actual.get("file_path") == expectation["expected_file"],
            code="best_target_file_mismatch",
            message=f"best target file matches for {label}",
            classification=classification,
            actual=actual.get("file_path"),
            expected=expectation["expected_file"],
        ))
    if "expected_anchor_kind" in expectation:
        checks.append(make_check(
            passed=actual.get("anchor_kind") == expectation["expected_anchor_kind"],
            code="best_target_anchor_kind_mismatch",
            message=f"best target anchor kind matches for {label}",
            classification=classification,
            actual=actual.get("anchor_kind"),
            expected=expectation["expected_anchor_kind"],
        ))
    if "expected_symbol" in expectation:
        checks.append(make_check(
            passed=actual.get("symbol_name") == expectation["expected_symbol"],
            code="best_target_symbol_mismatch",
            message=f"best target symbol matches for {label}",
            classification=classification,
            actual=actual.get("symbol_name"),
            expected=expectation["expected_symbol"],
        ))
    if "target_rank_at_least" in expectation:
        checks.append(make_check(
            passed=(actual.get("target_rank") or 0) >= expectation["target_rank_at_least"],
            code="best_target_rank_too_low",
            message=f"best target rank for {label} >= {expectation['target_rank_at_least']}",
            classification=classification,
            actual=actual.get("target_rank"),
            expected=expectation["target_rank_at_least"],
        ))
    return checks


def compare_flow_stage_target(actual_stage: Optional[dict[str, Any]], expectation: dict[str, Any], classification: str) -> list[dict[str, Any]]:
    route_label = route_locator_label(expectation["route"])
    label = f"request_flow stage {expectation['stage_type']} for {route_label}"
    checks = [make_check(
        passed=actual_stage is not None,
        code="request_flow_stage_missing",
        message=f"{label} exists",
        classification=classification,
        actual=actual_stage,
        expected=expectation,
    )]
    if actual_stage is None:
        return checks

    checks.append(make_check(
        passed=actual_stage.get("file_path") == expectation.get("expected_file"),
        code="request_flow_stage_file_mismatch",
        message=f"{label} file matches",
        classification=classification,
        actual=actual_stage.get("file_path"),
        expected=expectation.get("expected_file"),
    ))
    if "expected_symbol" in expectation:
        checks.append(make_check(
            passed=actual_stage.get("symbol_name") == expectation["expected_symbol"],
            code="request_flow_stage_symbol_mismatch",
            message=f"{label} symbol matches",
            classification=classification,
            actual=actual_stage.get("symbol_name"),
            expected=expectation["expected_symbol"],
        ))
    if "expected_anchor_kind" in expectation:
        checks.append(make_check(
            passed=actual_stage.get("anchor_kind") == expectation["expected_anchor_kind"],
            code="request_flow_stage_anchor_kind_mismatch",
            message=f"{label} anchor kind matches",
            classification=classification,
            actual=actual_stage.get("anchor_kind"),
            expected=expectation["expected_anchor_kind"],
        ))
    return checks


def finalize_target_result(checks: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(checks)
    passed = sum(1 for check in checks if check["passed"])
    mismatches = [
        {
            "code": check["code"],
            "message": check["message"],
            "classification": check["classification"],
            "actual": check.get("actual"),
            "expected": check.get("expected"),
        }
        for check in checks
        if not check["passed"]
    ]
    return {
        "score": round(passed / total, 4) if total else 1.0,
        "summary": {
            "total_checks": total,
            "passed_checks": passed,
            "failed_checks": total - passed,
        },
        "checks": checks,
        "mismatches": mismatches,
    }


def make_check(*, passed: bool, code: str, message: str, classification: str, actual: Any = None, expected: Any = None) -> dict[str, Any]:
    return {
        "passed": passed,
        "code": code,
        "message": message,
        "classification": classification,
        "actual": actual,
        "expected": expected,
    }


def materialize_case_source(case: dict[str, Any], temp_root: Path) -> Path:
    source = case["source"]
    if source["kind"] == "workspace":
        return REPO_ROOT / source["path"]

    if source["kind"] == "generated":
        builder = FIXTURE_BUILDERS[source["fixture"]]
        target_dir = temp_root / case["id"]
        return builder(target_dir)

    raise ValueError(f"Unsupported source kind: {source['kind']}")


def create_scanned_project(client: TestClient, case_id: str, source_dir: Path) -> str:
    create_response = client.post(
        "/projects",
        json={"name": f"golden-{case_id}-{uuid.uuid4().hex[:8]}", "path": str(source_dir)},
    )
    ensure_status(create_response, 201, f"{case_id} project creation")
    project_id = create_response.json()["id"]

    upload_response = client.post(
        f"/projects/{project_id}/upload",
        files={"file": (f"{case_id}.zip", build_zip_bytes(source_dir), "application/zip")},
    )
    ensure_status(upload_response, 201, f"{case_id} upload")

    scan_response = client.post(f"/projects/{project_id}/scan")
    ensure_status(scan_response, 201, f"{case_id} scan")

    graph_response = client.post(f"/projects/{project_id}/graph")
    ensure_status(graph_response, 201, f"{case_id} graph")
    return project_id


def fetch_routes(client: TestClient, project_id: str) -> dict[str, Any]:
    response = client.get(f"/projects/{project_id}/routes")
    ensure_status(response, 200, f"{project_id} routes")
    return response.json()


def generate_sequence(client: TestClient, project_id: str, route: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        f"/projects/{project_id}/sequence/route",
        json={
            "method": route["method"],
            "path": route["path"],
            "file": route["file"],
            "component": route["component"],
        },
    )
    ensure_status(response, 201, f"{project_id} sequence generation")
    return response.json()


def delete_project_quietly(client: TestClient, project_id: str) -> None:
    try:
        client.delete(f"/projects/{project_id}")
    except Exception:
        return


def seed_route_analysis(project_id: str, route: dict[str, Any], analysis_data: dict[str, Any]) -> None:
    method = str(route.get("method") or "GET").upper()
    path = str(route.get("path") or "/")
    file_path = str(route.get("file") or "")
    component = str(route.get("component") or "unknown")
    route_id = make_route_id(method, path, file_path)
    normalized_analysis = ensure_route_analysis_signature({
        **analysis_data,
        "route_id": route_id,
        "method": method,
        "path": path,
        "file": file_path,
        "component": component,
    })

    session = SessionLocal()
    try:
        session.query(RouteAnalysis).filter(
            RouteAnalysis.project_id == project_id,
            RouteAnalysis.route_id == route_id,
        ).delete()
        session.add(RouteAnalysis(
            project_id=project_id,
            scan_id=None,
            route_id=route_id,
            method=method,
            path=path,
            file=file_path,
            component=component,
            analysis_data=normalized_analysis,
        ))
        session.commit()
    finally:
        session.close()


def ensure_status(response: Any, expected: int, label: str) -> None:
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
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file() or should_skip_archive_path(source_dir, path):
                continue
            archive.write(path, path.relative_to(source_dir))
    return buffer.getvalue()


def route_key(route: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    return route.get("method"), route.get("path"), route.get("file")


def route_locator_label(route: dict[str, Any]) -> str:
    return f"{route.get('method')} {route.get('path')} ({route.get('file')})"


def component_locator_label(locator: dict[str, Any]) -> str:
    if "name" in locator:
        return locator["name"]
    if "index" in locator:
        return f"component[{locator['index']}]"
    return json.dumps(locator, sort_keys=True)


def find_component(components: list[dict[str, Any]], locator: dict[str, Any]) -> Optional[dict[str, Any]]:
    if "name" in locator:
        return next((component for component in components if component.get("name") == locator["name"]), None)
    return locate_component(components, locator)


def locate_component(components: list[dict[str, Any]], locator: dict[str, Any]) -> Optional[dict[str, Any]]:
    if "name" in locator:
        return next((component for component in components if component.get("name") == locator["name"]), None)
    if "index" in locator:
        index = locator["index"]
        if 0 <= index < len(components):
            return components[index]
        return None
    return next(iter(components), None)


def find_request_flow_stage(route: Optional[dict[str, Any]], expectation: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not route:
        return None

    stages = [
        stage for stage in (route.get("request_flow") or {}).get("stages", [])
        if stage.get("stage_type") == expectation["stage_type"]
    ]
    if not stages:
        return None

    def score(stage: dict[str, Any]) -> int:
        value = 0
        if expectation.get("expected_file") and stage.get("file_path") == expectation["expected_file"]:
            value += 3
        if expectation.get("expected_symbol") and stage.get("symbol_name") == expectation["expected_symbol"]:
            value += 3
        if expectation.get("expected_anchor_kind") and stage.get("anchor_kind") == expectation["expected_anchor_kind"]:
            value += 1
        return value

    return max(stages, key=score)


def is_subsequence(expected: list[str], actual: list[str]) -> bool:
    actual_iter = iter(actual)
    return all(item in actual_iter for item in expected)


def summarize_route(route: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if route is None:
        return None
    return {
        "method": route.get("method"),
        "path": route.get("path"),
        "file": route.get("file"),
        "handler_function": route.get("handler_function"),
        "controller_name": route.get("controller_name"),
    }


def summarize_infra(item: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if item is None:
        return None
    return {
        "name": item.get("name"),
        "kind": item.get("kind"),
        "entity_type": item.get("entity_type"),
        "confidence": item.get("confidence"),
    }


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 1.0


def strength_reason(target: str, score: float) -> str:
    if target == "component_boundaries":
        return "Top-level boundaries are staying stable across representative repo shapes."
    if target == "infra_detection":
        return "Datastore and external detection is matching curated expectations consistently."
    if target == "request_flow_quality":
        return "Stage reconstruction is preserving the important handler-to-service-to-data semantics."
    if target == "sequence_quality":
        return "Sequence generation is carrying grounded route-flow semantics into useful diagrams."
    if target == "best_target_quality":
        return "Anchor selection is landing on the right files and symbols for judged cases."
    return "This target family is producing a high proportion of correct checks."


def weakness_reason(target: str, score: float, mismatches: Counter[str]) -> str:
    if target == "route_extraction":
        return "Route discovery still appears to be the main noise entrypoint when false positives slip through."
    if target == "best_target_quality":
        return "Anchor ranking still needs attention where file or symbol selection drifts."
    if target == "request_flow_quality":
        return "Request-flow semantics still weaken fastest when stage ordering or stage presence drifts."
    if target == "sequence_quality":
        return "Sequence usefulness drops when message labeling or participant derivation misses key semantics."
    if target == "component_boundaries":
        return "Boundary grouping remains sensitive to root-path and entry-file heuristics."
    return "This target family currently has the lowest check score in the golden set."


def recommend_next_fixes(mismatches: Counter[str]) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    if mismatches["route_forbidden_present"] or mismatches["route_total_mismatch"] or mismatches["route_missing"]:
        recommendations.append({
            "area": "route_extraction",
            "why": "Route extraction mismatches are still the clearest remaining accuracy weakness.",
            "next_fix": "Tighten false-positive suppression around AST/service files and preserve handler ownership precision before AI refinement.",
        })
    if mismatches["request_flow_order_mismatch"] or mismatches["request_flow_missing_stage"] or mismatches["request_flow_too_many_inferred"]:
        recommendations.append({
            "area": "request_flow_quality",
            "why": "Request-flow errors directly degrade both API Explorer trust and downstream sequence quality.",
            "next_fix": "Improve stage reconstruction around service, external, and repository ordering, especially when indirect calls are involved.",
        })
    if mismatches["sequence_missing_message"] or mismatches["sequence_missing_participant"]:
        recommendations.append({
            "area": "sequence_quality",
            "why": "Sequence usefulness depends on retaining the key semantic moments and actors from request_flow.",
            "next_fix": "Tighten message labeling and participant derivation so important route semantics survive diagram generation.",
        })
    if mismatches["best_target_file_mismatch"] or mismatches["request_flow_stage_file_mismatch"] or mismatches["best_target_anchor_kind_mismatch"]:
        recommendations.append({
            "area": "best_target_quality",
            "why": "Weak anchors undermine Code Peek trust even when higher-level semantics are otherwise correct.",
            "next_fix": "Refine evidence ranking and anchor-kind tie-breaking for route, infra, and request-flow stage targets.",
        })
    if mismatches["component_missing"] or mismatches["component_total_mismatch"]:
        recommendations.append({
            "area": "component_boundaries",
            "why": "Boundary drift distorts multiple downstream surfaces and should be fixed at the scan/model layer.",
            "next_fix": "Tighten root-path splitting and entry-file detection for mixed frontend/backend workspaces.",
        })

    if not recommendations:
        recommendations.append({
            "area": "coverage_growth",
            "why": "The current golden set is stable and mostly accurate.",
            "next_fix": "Expand the corpus with one or two additional manually judged edge cases before AI refinement to keep accuracy pressure high.",
        })
    return recommendations[:4]


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Golden Accuracy Evaluation v1",
        "",
        f"Overall score: **{report['overall']['score']:.2%}**",
        "",
        "## Overall",
        "",
        f"- Total checks: {report['overall']['total_checks']}",
        f"- Passed checks: {report['overall']['passed_checks']}",
        f"- Failed checks: {report['overall']['failed_checks']}",
        f"- Failure kinds: {json.dumps(report['overall']['failure_kinds'], sort_keys=True)}",
        "",
        "## By Target",
        "",
    ]
    for target, summary in sorted(report["overall"]["by_target"].items()):
        lines.append(f"- {target}: {summary['score']:.2%} across {summary['case_count']} case(s)")

    lines.extend(["", "## Strongest Areas", ""])
    for item in report["strongest_areas"]:
        lines.append(f"- {item['target']}: {item['score']:.2%} — {item['reason']}")

    lines.extend(["", "## Weakest Areas", ""])
    if not report["weakest_areas"]:
        lines.append("- No measured target family failed in v1. The current limitation is corpus breadth, not an observed accuracy miss in this baseline.")
    else:
        for item in report["weakest_areas"]:
            lines.append(f"- {item['target']}: {item['score']:.2%} — {item['reason']}")

    lines.extend(["", "## Recurring Error Patterns", ""])
    if not report["recurring_error_patterns"]:
        lines.append("- No recurring mismatches were observed in the v1 golden set.")
    else:
        for pattern in report["recurring_error_patterns"]:
            lines.append(f"- {pattern['code']}: {pattern['count']} occurrence(s)")
            for example in pattern["examples"]:
                lines.append(f"  - {example}")

    lines.extend(["", "## Recommended Next Fixes", ""])
    for item in report["recommended_next_fixes"]:
        lines.append(f"- {item['area']}: {item['why']} Next fix: {item['next_fix']}")

    lines.extend(["", "## Case Scores", ""])
    for case in report["cases"]:
        lines.append(f"- {case['case_id']}: {case['score']:.2%}")
        for target_name, result in case["target_results"].items():
            lines.append(f"  - {target_name}: {result['score']:.2%} ({result['summary']['passed_checks']}/{result['summary']['total_checks']})")

    return "\n".join(lines) + "\n"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def create_python_service_flow_repo(root: Path) -> Path:
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


def create_integration_heavy_backend(root: Path) -> Path:
    write_text(root / "requirements.txt", "fastapi\nboto3\nsendgrid\n")
    write_text(
        root / "app.py",
        """
        import boto3
        from sendgrid import SendGridAPIClient

        def bootstrap():
            client = boto3.client('s3')
            mailer = SendGridAPIClient('token')
            return client, mailer
        """,
    )
    return root


def create_mixed_language_monorepo(root: Path) -> Path:
    write_text(root / "services" / "api" / "requirements.txt", "fastapi\n")
    write_text(
        root / "services" / "api" / "app" / "main.py",
        """
        from fastapi import FastAPI

        app = FastAPI()

        @app.get('/api/health')
        def health_check():
            return {'status': 'ok'}
        """,
    )
    write_text(
        root / "services" / "web" / "package.json",
        """
        {
          "name": "web",
          "private": true,
          "version": "1.0.0"
        }
        """,
    )
    write_text(
        root / "services" / "web" / "src" / "main.tsx",
        """
        import React from 'react'
        import ReactDOM from 'react-dom/client'
        import { App } from './App'

        ReactDOM.createRoot(document.getElementById('root')!).render(<App />)
        """,
    )
    write_text(
        root / "services" / "web" / "src" / "App.tsx",
        """
        export function App() {
          return <main>dashboard</main>
        }
        """,
    )
    write_text(root / "packages" / "shared" / "index.ts", "export const version = '1.0.0'\n")
    return root


def create_route_false_positive_repo(root: Path) -> Path:
    write_text(root / "requirements.txt", "fastapi\n")
    write_text(
        root / "app.py",
        """
        from fastapi import FastAPI

        app = FastAPI()

        @app.get('/healthz')
        def healthz():
            return {'ok': True}
        """,
    )
    write_text(
        root / "app" / "services" / "path_service.py",
        """
        ROUTE_TEMPLATE = 'GET /path'

        def get_path_segments(raw_path: str) -> list[str]:
            return [segment for segment in raw_path.split('/') if segment]

        def post_path_event(path: str) -> dict:
            return {'method': 'POST', 'path': path}

        class PathFormatter:
            def get_path(self, slug: str) -> str:
                return f'/shadow/{slug}'
        """,
    )
    return root


def create_degraded_fallback_backend(root: Path) -> Path:
    write_text(root / "requirements.txt", "requests\n")
    write_text(
        root / "app.py",
        """
        from legacy_handlers import sync_invoice_report

        def bootstrap():
            return sync_invoice_report
        """,
    )
    write_text(
        root / "legacy_handlers.py",
        """
        import requests

        class Session:
            def execute(self, statement):
                return statement

            def commit(self):
                return True

        db = Session()

        def sync_invoice_report(report_id: str):
            payload = {'report_id': report_id}
            requests.post('https://reports.example.com/run', json=payload)
            db.execute({'report_id': report_id, 'status': 'generated'})
            db.commit()
            return {'ok': True}
        """,
    )
    return root


def create_ambiguous_anchor_backend(root: Path) -> Path:
    write_text(root / "requirements.txt", "fastapi\n")
    write_text(
        root / "app.py",
        """
        from fastapi import FastAPI
        from app.services.invoice_service import create_invoice_record
        from app.services.invoice_shadow import create_invoice_record as create_invoice_record_shadow

        app = FastAPI()

        @app.post('/api/invoices')
        def create_invoice():
            payload = {'amount': 42}
            create_invoice_record_shadow({'amount': 0})
            return create_invoice_record(payload)
        """,
    )
    write_text(
        root / "app" / "services" / "invoice_service.py",
        """
        from app.repositories.invoice_repo import persist_invoice

        def create_invoice_record(payload):
            return persist_invoice(payload)
        """,
    )
    write_text(
        root / "app" / "services" / "invoice_shadow.py",
        """
        def create_invoice_record(payload):
            return {'shadow': payload}
        """,
    )
    write_text(
        root / "app" / "repositories" / "invoice_repo.py",
        """
        def persist_invoice(payload):
            return {'invoice_id': 'inv_123', 'payload': payload}
        """,
    )
    return root


def create_sparse_minimal_repo(root: Path) -> Path:
    write_text(root / "README.md", "# Sparse repo\n")
    write_text(root / "tool.py", "def main():\n    return 'ok'\n")
    return root


FIXTURE_BUILDERS: dict[str, Callable[[Path], Path]] = {
    "mixed_language_monorepo": create_mixed_language_monorepo,
    "route_false_positive": create_route_false_positive_repo,
    "degraded_fallback_backend": create_degraded_fallback_backend,
    "ambiguous_anchor_backend": create_ambiguous_anchor_backend,
    "python_service_flow": create_python_service_flow_repo,
    "integration_heavy_backend": create_integration_heavy_backend,
    "sparse_minimal": create_sparse_minimal_repo,
}


if __name__ == "__main__":
    main()