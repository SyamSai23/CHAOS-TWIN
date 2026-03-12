from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional


SOURCE_EXTENSIONS: set[str] = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rb", ".php", ".ini", ".cfg", ".toml",
}

_MAX_CODE_BYTES = 512 * 1024
_SKIP_SCAN_PATH_SUFFIXES = {"app/services/infrastructure_detection.py"}

_DEPENDENCY_RULES: dict[str, dict[str, str]] = {
    "psycopg": {"entity_type": "data_store", "name": "PostgreSQL", "kind": "sql"},
    "psycopg2": {"entity_type": "data_store", "name": "PostgreSQL", "kind": "sql"},
    "psycopg2-binary": {"entity_type": "data_store", "name": "PostgreSQL", "kind": "sql"},
    "asyncpg": {"entity_type": "data_store", "name": "PostgreSQL", "kind": "sql"},
    "pymysql": {"entity_type": "data_store", "name": "MySQL", "kind": "sql"},
    "mysql-connector": {"entity_type": "data_store", "name": "MySQL", "kind": "sql"},
    "mysql-connector-python": {"entity_type": "data_store", "name": "MySQL", "kind": "sql"},
    "pymongo": {"entity_type": "data_store", "name": "MongoDB", "kind": "document"},
    "motor": {"entity_type": "data_store", "name": "MongoDB", "kind": "document"},
    "mongoose": {"entity_type": "data_store", "name": "MongoDB", "kind": "document"},
    "redis": {"entity_type": "data_store", "name": "Redis", "kind": "cache"},
    "ioredis": {"entity_type": "data_store", "name": "Redis", "kind": "cache"},
    "sqlite3": {"entity_type": "data_store", "name": "SQLite", "kind": "sql"},
    "better-sqlite3": {"entity_type": "data_store", "name": "SQLite", "kind": "sql"},
    "pika": {"entity_type": "data_store", "name": "RabbitMQ", "kind": "queue"},
    "aio-pika": {"entity_type": "data_store", "name": "RabbitMQ", "kind": "queue"},
    "kafka-python": {"entity_type": "data_store", "name": "Kafka", "kind": "queue"},
    "confluent-kafka": {"entity_type": "data_store", "name": "Kafka", "kind": "queue"},
    "kafkajs": {"entity_type": "data_store", "name": "Kafka", "kind": "queue"},
    "celery": {"entity_type": "data_store", "name": "Celery", "kind": "queue"},
    "elasticsearch": {"entity_type": "data_store", "name": "Elasticsearch", "kind": "search"},
    "opensearch": {"entity_type": "data_store", "name": "OpenSearch", "kind": "search"},
    "minio": {"entity_type": "data_store", "name": "MinIO", "kind": "object_store"},
    "boto3": {"entity_type": "external_integration", "name": "AWS / S3", "kind": "object_storage", "provider": "AWS"},
    "aws-sdk": {"entity_type": "external_integration", "name": "AWS / S3", "kind": "object_storage", "provider": "AWS"},
    "stripe": {"entity_type": "external_integration", "name": "Stripe", "kind": "payment", "provider": "Stripe"},
    "stripe-python": {"entity_type": "external_integration", "name": "Stripe", "kind": "payment", "provider": "Stripe"},
    "sendgrid": {"entity_type": "external_integration", "name": "SendGrid", "kind": "email", "provider": "SendGrid"},
    "twilio": {"entity_type": "external_integration", "name": "Twilio", "kind": "messaging", "provider": "Twilio"},
    "slack-sdk": {"entity_type": "external_integration", "name": "Slack", "kind": "messaging", "provider": "Slack"},
    "slack_sdk": {"entity_type": "external_integration", "name": "Slack", "kind": "messaging", "provider": "Slack"},
    "firebase": {"entity_type": "external_integration", "name": "Firebase", "kind": "backend_service", "provider": "Firebase"},
    "firebase-admin": {"entity_type": "external_integration", "name": "Firebase", "kind": "backend_service", "provider": "Firebase"},
    "supabase": {"entity_type": "external_integration", "name": "Supabase", "kind": "backend_service", "provider": "Supabase"},
    "openai": {"entity_type": "external_integration", "name": "OpenAI", "kind": "ai", "provider": "OpenAI"},
    "anthropic": {"entity_type": "external_integration", "name": "Anthropic", "kind": "ai", "provider": "Anthropic"},
}

_DOCKER_KEYWORDS: dict[str, dict[str, str]] = {
    "postgres": {"entity_type": "data_store", "name": "PostgreSQL", "kind": "sql"},
    "postgresql": {"entity_type": "data_store", "name": "PostgreSQL", "kind": "sql"},
    "mysql": {"entity_type": "data_store", "name": "MySQL", "kind": "sql"},
    "mariadb": {"entity_type": "data_store", "name": "MariaDB", "kind": "sql"},
    "mongo": {"entity_type": "data_store", "name": "MongoDB", "kind": "document"},
    "mongodb": {"entity_type": "data_store", "name": "MongoDB", "kind": "document"},
    "redis": {"entity_type": "data_store", "name": "Redis", "kind": "cache"},
    "sqlite": {"entity_type": "data_store", "name": "SQLite", "kind": "sql"},
    "dynamodb": {"entity_type": "data_store", "name": "DynamoDB", "kind": "nosql"},
    "rabbitmq": {"entity_type": "data_store", "name": "RabbitMQ", "kind": "queue"},
    "kafka": {"entity_type": "data_store", "name": "Kafka", "kind": "queue"},
    "celery": {"entity_type": "data_store", "name": "Celery", "kind": "queue"},
    "elasticsearch": {"entity_type": "data_store", "name": "Elasticsearch", "kind": "search"},
    "opensearch": {"entity_type": "data_store", "name": "OpenSearch", "kind": "search"},
    "minio": {"entity_type": "data_store", "name": "MinIO", "kind": "object_store"},
    "localstack": {"entity_type": "data_store", "name": "LocalStack", "kind": "emulator"},
}

_URI_PATTERNS: list[tuple[re.Pattern[str], dict[str, str]]] = [
    (re.compile(r"postgres(?:ql)?(?:\+[a-z0-9_]+)?://[^\s'\"\)]+", re.I), {"entity_type": "data_store", "name": "PostgreSQL", "kind": "sql"}),
    (re.compile(r"mysql(?:\+[a-z0-9_]+)?://[^\s'\"\)]+", re.I), {"entity_type": "data_store", "name": "MySQL", "kind": "sql"}),
    (re.compile(r"mariadb(?:\+[a-z0-9_]+)?://[^\s'\"\)]+", re.I), {"entity_type": "data_store", "name": "MariaDB", "kind": "sql"}),
    (re.compile(r"mongodb(?:\+srv)?://[^\s'\"\)]+", re.I), {"entity_type": "data_store", "name": "MongoDB", "kind": "document"}),
    (re.compile(r"redis://[^\s'\"\)]+", re.I), {"entity_type": "data_store", "name": "Redis", "kind": "cache"}),
    (re.compile(r"amqp://[^\s'\"\)]+", re.I), {"entity_type": "data_store", "name": "RabbitMQ", "kind": "queue"}),
    (re.compile(r"kafka://[^\s'\"\)]+", re.I), {"entity_type": "data_store", "name": "Kafka", "kind": "queue"}),
    (re.compile(r"sqlite:///[^\s'\"\)]+", re.I), {"entity_type": "data_store", "name": "SQLite", "kind": "sql"}),
]

_ENV_TOKEN_RULES: list[tuple[re.Pattern[str], dict[str, str]]] = [
    (re.compile(r"\bDATABASE_URL\b"), {"entity_type": "data_store", "name": "PostgreSQL", "kind": "sql"}),
    (re.compile(r"\bREDIS_URL\b"), {"entity_type": "data_store", "name": "Redis", "kind": "cache"}),
    (re.compile(r"\b(?:RABBITMQ_URL|AMQP_URL)\b"), {"entity_type": "data_store", "name": "RabbitMQ", "kind": "queue"}),
    (re.compile(r"\bKAFKA_BOOTSTRAP_SERVERS\b"), {"entity_type": "data_store", "name": "Kafka", "kind": "queue"}),
    (re.compile(r"\b(?:STRIPE_API_KEY|STRIPE_SECRET_KEY)\b"), {"entity_type": "external_integration", "name": "Stripe", "kind": "payment", "provider": "Stripe"}),
    (re.compile(r"\b(?:AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|S3_BUCKET)\b"), {"entity_type": "external_integration", "name": "AWS / S3", "kind": "object_storage", "provider": "AWS"}),
    (re.compile(r"\bSENDGRID_API_KEY\b"), {"entity_type": "external_integration", "name": "SendGrid", "kind": "email", "provider": "SendGrid"}),
    (re.compile(r"\bTWILIO_(?:ACCOUNT_SID|AUTH_TOKEN)\b"), {"entity_type": "external_integration", "name": "Twilio", "kind": "messaging", "provider": "Twilio"}),
]

_URL_RULES: list[tuple[re.Pattern[str], dict[str, str]]] = [
    (re.compile(r"https?://[^\s'\"]*api\.stripe\.com[^\s'\"]*", re.I), {"entity_type": "external_integration", "name": "Stripe", "kind": "payment", "provider": "Stripe"}),
    (re.compile(r"https?://[^\s'\"]*api\.sendgrid\.com[^\s'\"]*", re.I), {"entity_type": "external_integration", "name": "SendGrid", "kind": "email", "provider": "SendGrid"}),
    (re.compile(r"https?://[^\s'\"]*api\.twilio\.com[^\s'\"]*", re.I), {"entity_type": "external_integration", "name": "Twilio", "kind": "messaging", "provider": "Twilio"}),
    (re.compile(r"https?://[^\s'\"]*slack\.com/api[^\s'\"]*", re.I), {"entity_type": "external_integration", "name": "Slack", "kind": "messaging", "provider": "Slack"}),
    (re.compile(r"https?://[^\s'\"]*amazonaws\.com[^\s'\"]*", re.I), {"entity_type": "external_integration", "name": "AWS / S3", "kind": "object_storage", "provider": "AWS"}),
]

_CODE_SIGNAL_RULES: list[tuple[re.Pattern[str], dict[str, str], str]] = [
    (re.compile(r"\bpsycopg(?:2)?\.connect\s*\(", re.I), {"entity_type": "data_store", "name": "PostgreSQL", "kind": "sql"}, "client_initialization"),
    (re.compile(r"\basyncpg\.connect\s*\(", re.I), {"entity_type": "data_store", "name": "PostgreSQL", "kind": "sql"}, "client_initialization"),
    (re.compile(r"\bredis\.Redis\s*\(", re.I), {"entity_type": "data_store", "name": "Redis", "kind": "cache"}, "client_initialization"),
    (re.compile(r"\bnew\s+Redis\s*\(", re.I), {"entity_type": "data_store", "name": "Redis", "kind": "cache"}, "client_initialization"),
    (re.compile(r"\bMongoClient\s*\(", re.I), {"entity_type": "data_store", "name": "MongoDB", "kind": "document"}, "client_initialization"),
    (re.compile(r"\bmongoose\.connect\s*\(", re.I), {"entity_type": "data_store", "name": "MongoDB", "kind": "document"}, "client_initialization"),
    (re.compile(r"\bcreate_engine\s*\(", re.I), {"entity_type": "data_store", "name": "Database", "kind": "sql"}, "client_initialization"),
    (re.compile(r"\bPrismaClient\s*\(", re.I), {"entity_type": "data_store", "name": "Database", "kind": "sql"}, "client_initialization"),
    (re.compile(r"\b(?:KafkaProducer|KafkaConsumer)\s*\(", re.I), {"entity_type": "data_store", "name": "Kafka", "kind": "queue"}, "client_initialization"),
    (re.compile(r"\bCelery\s*\(", re.I), {"entity_type": "data_store", "name": "Celery", "kind": "queue"}, "client_initialization"),
    (re.compile(r"\bboto3\.(?:client|resource)\s*\(\s*['\"](s3|sns|sqs|dynamodb)['\"]", re.I), {"entity_type": "external_integration", "name": "AWS / S3", "kind": "object_storage", "provider": "AWS"}, "client_initialization"),
    (re.compile(r"\bS3Client\s*\(", re.I), {"entity_type": "external_integration", "name": "AWS / S3", "kind": "object_storage", "provider": "AWS"}, "client_initialization"),
    (re.compile(r"\bstripe\.[A-Za-z_]", re.I), {"entity_type": "external_integration", "name": "Stripe", "kind": "payment", "provider": "Stripe"}, "active_usage"),
    (re.compile(r"\bnew\s+Stripe\s*\(", re.I), {"entity_type": "external_integration", "name": "Stripe", "kind": "payment", "provider": "Stripe"}, "client_initialization"),
    (re.compile(r"\bSendGridAPIClient\s*\(", re.I), {"entity_type": "external_integration", "name": "SendGrid", "kind": "email", "provider": "SendGrid"}, "client_initialization"),
    (re.compile(r"\btwilio\s*\(", re.I), {"entity_type": "external_integration", "name": "Twilio", "kind": "messaging", "provider": "Twilio"}, "client_initialization"),
    (re.compile(r"\bWebClient\s*\(", re.I), {"entity_type": "external_integration", "name": "Slack", "kind": "messaging", "provider": "Slack"}, "client_initialization"),
    (re.compile(r"\bOpenAI\s*\(", re.I), {"entity_type": "external_integration", "name": "OpenAI", "kind": "ai", "provider": "OpenAI"}, "client_initialization"),
    (re.compile(r"\bAnthropic\s*\(", re.I), {"entity_type": "external_integration", "name": "Anthropic", "kind": "ai", "provider": "Anthropic"}, "client_initialization"),
]

_SIGNAL_WEIGHTS: dict[str, float] = {
    "declared_dependency": 0.22,
    "docker_service": 0.55,
    "docker_dependency": 0.16,
    "connection_string": 0.24,
    "client_initialization": 0.28,
    "active_usage": 0.16,
    "env_reference": 0.1,
}

_EVIDENCE_TYPE_PRIORITY: dict[str, int] = {
    "client_initialization": 100,
    "connection_string": 92,
    "active_usage": 82,
    "docker_dependency": 68,
    "docker_service": 58,
    "env_reference": 48,
    "declared_dependency": 36,
}


@dataclass
class InfraCandidate:
    entity_type: str
    name: str
    kind: str
    component: Optional[str]
    technology: Optional[str] = None
    provider: Optional[str] = None
    signals: set[str] = field(default_factory=set)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    manifest_paths: set[str] = field(default_factory=set)
    docker_services: set[str] = field(default_factory=set)


def detect_infrastructure(
    files: list[dict],
    root: str,
    components: list[dict],
    dependencies: dict[str, list[dict]],
    docker_services: list[dict],
    env_variables: list[str],
    service_graph: list[dict],
) -> dict[str, Any]:
    component_lookup = _component_lookup(components)
    enriched_dependencies = _annotate_dependencies(dependencies, component_lookup)
    enriched_docker_services, docker_index = _annotate_docker_services(docker_services)
    candidates: dict[tuple[str, str, str, str], InfraCandidate] = {}

    for language, dep_entries in enriched_dependencies.items():
        if not isinstance(dep_entries, list):
            continue
        for entry in dep_entries:
            if not isinstance(entry, dict):
                continue
            infra_meta = entry.get("infrastructure") or {}
            if not infra_meta:
                continue
            component_name = entry.get("component")
            candidate = _ensure_candidate(
                candidates,
                entity_type=infra_meta.get("entity_type") or "data_store",
                name=infra_meta.get("name") or entry.get("name") or "dependency",
                kind=infra_meta.get("kind") or "dependency",
                component=component_name,
                technology=infra_meta.get("technology") or entry.get("name"),
                provider=infra_meta.get("provider"),
            )
            candidate.signals.add("declared_dependency")
            manifest_path = entry.get("manifest_path") or "."
            candidate.manifest_paths.add(manifest_path)
            candidate.evidence.append({
                "type": "declared_dependency",
                "source": entry.get("manifest_type") or "dependency_manifest",
                "file": manifest_path,
                "detail": entry.get("name"),
            })

    _apply_docker_links(candidates, components, component_lookup, docker_index, enriched_docker_services, service_graph)
    _apply_code_signals(candidates, files, root, component_lookup)
    _apply_env_signals(candidates, env_variables, components)

    component_items = _finalize_component_items(candidates)
    enriched_components: list[dict] = []
    for component in components:
        infra_items = component_items.get(component.get("name"), [])
        enriched_components.append({
            **component,
            "infrastructure": infra_items,
        })

    return {
        "dependencies": enriched_dependencies,
        "docker_services": enriched_docker_services,
        "components": enriched_components,
    }


def _annotate_dependencies(
    dependencies: dict[str, list[dict]],
    component_lookup: dict[str, Any],
) -> dict[str, list[dict]]:
    enriched: dict[str, list[dict]] = {}
    for language, dep_entries in dependencies.items():
        if not isinstance(dep_entries, list):
            enriched[language] = dep_entries
            continue
        output: list[dict] = []
        for raw_entry in dep_entries:
            if isinstance(raw_entry, dict):
                entry = dict(raw_entry)
            else:
                entry = {"name": str(raw_entry)}
            dep_name = str(entry.get("name") or "")
            manifest_path = str(entry.get("manifest_path") or ".")
            entry["component"] = _component_for_path(manifest_path, component_lookup)
            infra_meta = _classify_dependency(dep_name)
            if infra_meta:
                entry["infrastructure"] = {
                    **infra_meta,
                    "technology": dep_name,
                    "confidence": 0.45 if infra_meta["entity_type"] == "external_integration" else 0.52,
                    "detection_rule": "dependency_name_mapping",
                }
            output.append(entry)
        enriched[language] = _dedupe_dependency_entries(output)
    return enriched


def _annotate_docker_services(docker_services: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    enriched: list[dict] = []
    index: dict[str, dict] = {}
    for raw_service in docker_services:
        if not isinstance(raw_service, dict):
            continue
        service = dict(raw_service)
        classified = _classify_docker_service(str(service.get("name") or ""), str(service.get("image") or ""))
        if classified:
            service["infrastructure"] = {
                **classified,
                "technology": str(service.get("image") or service.get("name") or ""),
                "confidence": 0.92,
                "detection_rule": "docker_service_mapping",
            }
            service["evidence"] = [{
                "type": "docker_service",
                "source": "docker-compose",
                "detail": service.get("name") or service.get("image"),
            }]
        enriched.append(service)
        name = str(service.get("name") or "").lower()
        if name:
            index[name] = service
    return enriched, index


def _apply_docker_links(
    candidates: dict[tuple[str, str, str, str], InfraCandidate],
    components: list[dict],
    component_lookup: dict[str, Any],
    docker_index: dict[str, dict],
    docker_services: list[dict],
    service_graph: list[dict],
) -> None:
    alias_to_component = _component_aliases(components)
    for service in docker_services:
        infra_meta = service.get("infrastructure") or {}
        if not infra_meta:
            continue
        service_name = str(service.get("name") or "")
        candidate = _ensure_candidate(
            candidates,
            entity_type=infra_meta.get("entity_type") or "data_store",
            name=infra_meta.get("name") or service_name,
            kind=infra_meta.get("kind") or "service",
            component=None,
            technology=infra_meta.get("technology") or str(service.get("image") or service_name),
            provider=infra_meta.get("provider"),
        )
        candidate.signals.add("docker_service")
        candidate.docker_services.add(service_name)
        candidate.evidence.append({
            "type": "docker_service",
            "source": "docker-compose",
            "detail": service_name or service.get("image"),
        })

    for link in service_graph:
        if not isinstance(link, dict):
            continue
        source_name = str(link.get("from") or "").lower()
        target_name = str(link.get("to") or "").lower()
        target_service = docker_index.get(target_name)
        if not target_service:
            continue
        infra_meta = target_service.get("infrastructure") or {}
        if not infra_meta:
            continue
        component_name = alias_to_component.get(source_name)
        if not component_name:
            component_name = _component_for_path(source_name, component_lookup)
        if not component_name:
            continue
        candidate = _ensure_candidate(
            candidates,
            entity_type=infra_meta.get("entity_type") or "data_store",
            name=infra_meta.get("name") or target_name,
            kind=infra_meta.get("kind") or "service",
            component=component_name,
            technology=infra_meta.get("technology") or str(target_service.get("image") or target_name),
            provider=infra_meta.get("provider"),
        )
        candidate.signals.add("docker_dependency")
        candidate.docker_services.add(str(target_service.get("name") or target_name))
        candidate.evidence.append({
            "type": "docker_dependency",
            "source": "service_graph",
            "detail": f"{link.get('from')} -> {link.get('to')}",
        })


def _apply_code_signals(
    candidates: dict[tuple[str, str, str, str], InfraCandidate],
    files: list[dict],
    root: str,
    component_lookup: dict[str, Any],
) -> None:
    for file_info in files:
        rel_path = str(file_info.get("path") or "")
        ext = str(file_info.get("extension") or "")
        size = int(file_info.get("size_bytes") or 0)
        if any(rel_path.endswith(suffix) for suffix in _SKIP_SCAN_PATH_SUFFIXES):
            continue
        if ext not in SOURCE_EXTENSIONS or size <= 0 or size > _MAX_CODE_BYTES:
            continue
        full_path = os.path.join(root, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as handle:
                content = handle.read()
        except OSError:
            continue
        component_name = _component_for_path(rel_path, component_lookup)
        _apply_uri_matches(candidates, content, rel_path, component_name)
        _apply_line_matches(candidates, content, rel_path, component_name)


def _apply_env_signals(
    candidates: dict[tuple[str, str, str, str], InfraCandidate],
    env_variables: list[str],
    components: list[dict],
) -> None:
    target_components = [component.get("name") for component in components if component.get("type") in {"backend", "service", "worker"}]
    if not target_components and len(components) == 1:
        target_components = [components[0].get("name")]
    for env_name in env_variables:
        if not isinstance(env_name, str):
            continue
        for pattern, meta in _ENV_TOKEN_RULES:
            if not pattern.search(env_name):
                continue
            for component_name in target_components:
                candidate = _ensure_candidate(
                    candidates,
                    entity_type=meta["entity_type"],
                    name=meta["name"],
                    kind=meta["kind"],
                    component=component_name,
                    provider=meta.get("provider"),
                )
                candidate.signals.add("env_reference")
                candidate.evidence.append({
                    "type": "env_reference",
                    "source": "env_file",
                    "detail": env_name,
                })


def _apply_uri_matches(
    candidates: dict[tuple[str, str, str, str], InfraCandidate],
    content: str,
    rel_path: str,
    component_name: Optional[str],
) -> None:
    for pattern, meta in _URI_PATTERNS:
        for match in pattern.finditer(content):
            candidate = _ensure_candidate(
                candidates,
                entity_type=meta["entity_type"],
                name=meta["name"],
                kind=meta["kind"],
                component=component_name,
            )
            candidate.signals.add("connection_string")
            candidate.evidence.append({
                "type": "connection_string",
                "source": "code",
                "file": rel_path,
                "line_start": _line_for_offset(content, match.start()),
                "detail": match.group(0)[:140],
            })


def _apply_line_matches(
    candidates: dict[tuple[str, str, str, str], InfraCandidate],
    content: str,
    rel_path: str,
    component_name: Optional[str],
) -> None:
    for pattern, meta, signal_type in _CODE_SIGNAL_RULES:
        for match in pattern.finditer(content):
            candidate = _ensure_candidate(
                candidates,
                entity_type=meta["entity_type"],
                name=meta["name"],
                kind=meta["kind"],
                component=component_name,
                provider=meta.get("provider"),
            )
            candidate.signals.add(signal_type)
            candidate.evidence.append({
                "type": signal_type,
                "source": "code",
                "file": rel_path,
                "line_start": _line_for_offset(content, match.start()),
                "detail": match.group(0)[:140],
            })

    for pattern, meta in _ENV_TOKEN_RULES:
        for match in pattern.finditer(content):
            candidate = _ensure_candidate(
                candidates,
                entity_type=meta["entity_type"],
                name=meta["name"],
                kind=meta["kind"],
                component=component_name,
                provider=meta.get("provider"),
            )
            candidate.signals.add("env_reference")
            candidate.evidence.append({
                "type": "env_reference",
                "source": "code",
                "file": rel_path,
                "line_start": _line_for_offset(content, match.start()),
                "detail": match.group(0),
            })

    for pattern, meta in _URL_RULES:
        for match in pattern.finditer(content):
            candidate = _ensure_candidate(
                candidates,
                entity_type=meta["entity_type"],
                name=meta["name"],
                kind=meta["kind"],
                component=component_name,
                provider=meta.get("provider"),
            )
            candidate.signals.add("active_usage")
            candidate.evidence.append({
                "type": "active_usage",
                "source": "code",
                "file": rel_path,
                "line_start": _line_for_offset(content, match.start()),
                "detail": match.group(0)[:140],
            })


def _finalize_component_items(
    candidates: dict[tuple[str, str, str, str], InfraCandidate],
) -> dict[str, list[dict[str, Any]]]:
    component_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates.values():
        if not candidate.component:
            continue
        confidence = _confidence_for(candidate.signals)
        evidence = _sort_evidence(_dedupe_evidence(candidate.evidence))
        best_target = _best_target_from_evidence(evidence)
        item = {
            "entity_type": candidate.entity_type,
            "name": candidate.name,
            "kind": candidate.kind,
            "technology": candidate.technology,
            "provider": candidate.provider,
            "signals": sorted(candidate.signals),
            "confidence": confidence,
            "confidence_label": _confidence_label(confidence),
            "evidence": evidence,
            "best_target": best_target,
            "manifest_paths": sorted(candidate.manifest_paths),
            "docker_services": sorted(candidate.docker_services),
        }
        component_items[candidate.component].append(item)

    for component_name, items in component_items.items():
        specific_sql_names = {
            item["name"]
            for item in items
            if item["entity_type"] == "data_store" and item["kind"] == "sql" and item["name"] != "Database"
        }
        if specific_sql_names:
            items = [
                item
                for item in items
                if not (item["entity_type"] == "data_store" and item["kind"] == "sql" and item["name"] == "Database")
            ]
        items = [
            item
            for item in items
            if not (
                item["entity_type"] == "external_integration"
                and set(item.get("signals") or []) == {"declared_dependency"}
                and item["confidence"] < 0.6
            )
        ]
        component_items[component_name] = sorted(
            items,
            key=lambda item: (-item["confidence"], item["entity_type"], item["name"], item["kind"]),
        )
    return component_items


def _ensure_candidate(
    candidates: dict[tuple[str, str, str, str], InfraCandidate],
    entity_type: str,
    name: str,
    kind: str,
    component: Optional[str],
    technology: Optional[str] = None,
    provider: Optional[str] = None,
) -> InfraCandidate:
    key = (entity_type, name.lower(), kind.lower(), (component or "").lower())
    if key not in candidates:
        candidates[key] = InfraCandidate(
            entity_type=entity_type,
            name=name,
            kind=kind,
            component=component,
            technology=technology,
            provider=provider,
        )
    candidate = candidates[key]
    if technology and not candidate.technology:
        candidate.technology = technology
    if provider and not candidate.provider:
        candidate.provider = provider
    return candidate


def _component_lookup(components: list[dict]) -> dict[str, Any]:
    prepared: list[dict[str, Any]] = []
    for component in components:
        if not isinstance(component, dict):
            continue
        root_path = _normalize_path(component.get("root_path") or ".")
        prepared.append({
            "name": component.get("name"),
            "root_path": root_path,
            "type": component.get("type"),
            "priority": len(root_path.split("/")) if root_path != "." else 0,
        })
    prepared.sort(key=lambda item: item["priority"], reverse=True)
    return {"components": prepared}


def _component_for_path(rel_path: str, component_lookup: dict[str, Any]) -> Optional[str]:
    normalized = _normalize_path(rel_path)
    best_match: Optional[str] = None
    best_priority = -1
    for component in component_lookup.get("components", []):
        root_path = component["root_path"]
        if root_path == ".":
            if best_match is None:
                best_match = component["name"]
                best_priority = 0
            continue
        if normalized == root_path or normalized.startswith(f"{root_path}/"):
            if component["priority"] > best_priority:
                best_match = component["name"]
                best_priority = component["priority"]
    return best_match


def _component_aliases(components: list[dict]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for component in components:
        if not isinstance(component, dict):
            continue
        component_name = component.get("name")
        if not component_name:
            continue
        aliases[component_name.lower()] = component_name
        root_path = _normalize_path(component.get("root_path") or ".")
        if root_path != ".":
            aliases[os.path.basename(root_path).lower()] = component_name
        entry_file = _normalize_path(component.get("entry_file") or ".")
        if entry_file != ".":
            aliases[os.path.basename(os.path.dirname(entry_file)).lower()] = component_name
    return aliases


def _classify_dependency(dep_name: str) -> Optional[dict[str, str]]:
    normalized = dep_name.strip().lower()
    if normalized in _DEPENDENCY_RULES:
        return dict(_DEPENDENCY_RULES[normalized])
    if normalized.startswith("@aws-sdk/"):
        return {"entity_type": "external_integration", "name": "AWS / S3", "kind": "object_storage", "provider": "AWS"}
    if normalized.startswith("@sendgrid/"):
        return {"entity_type": "external_integration", "name": "SendGrid", "kind": "email", "provider": "SendGrid"}
    return None


def _classify_docker_service(name: str, image: str) -> Optional[dict[str, str]]:
    combined = f"{name} {image}".lower()
    for keyword, meta in _DOCKER_KEYWORDS.items():
        if keyword in combined:
            return dict(meta)
    return None


def _dedupe_dependency_entries(entries: list[dict]) -> list[dict]:
    merged: dict[tuple[str, str, str], dict] = {}
    for entry in entries:
        key = (
            str(entry.get("name") or "").lower(),
            str(entry.get("manifest_path") or "."),
            str(entry.get("section") or "dependencies"),
        )
        if key not in merged:
            merged[key] = dict(entry)
            continue
        current = merged[key]
        if entry.get("version") and not current.get("version"):
            current["version"] = entry.get("version")
        if entry.get("component") and not current.get("component"):
            current["component"] = entry.get("component")
        if entry.get("infrastructure") and not current.get("infrastructure"):
            current["infrastructure"] = entry.get("infrastructure")
    return sorted(merged.values(), key=lambda item: (item.get("manifest_path") or ".", item.get("name") or ""))


def _dedupe_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, int]] = set()
    output: list[dict[str, Any]] = []
    for item in evidence:
        key = (
            str(item.get("type") or ""),
            str(item.get("file") or item.get("source") or ""),
            str(item.get("detail") or ""),
            int(item.get("line_start") or 0),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _sort_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        evidence,
        key=lambda item: (
            _evidence_priority(item),
            1 if item.get("file") else 0,
            1 if item.get("line_start") is not None else 0,
            str(item.get("file") or item.get("source") or ""),
            -int(item.get("line_start") or 0),
        ),
        reverse=True,
    )


def _best_target_from_evidence(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    if not evidence:
        return {
            "file_path": None,
            "line_start": None,
            "line_end": None,
            "anchor_kind": "unknown",
            "target_rank": 0,
            "selection_reason": "no concrete infrastructure evidence was retained",
        }
    best = evidence[0]
    return {
        "file_path": best.get("file"),
        "line_start": best.get("line_start"),
        "line_end": best.get("line_start"),
        "anchor_kind": str(best.get("type") or "unknown"),
        "target_rank": _evidence_priority(best),
        "selection_reason": _selection_reason_for_evidence(best),
    }


def _evidence_priority(item: dict[str, Any]) -> int:
    priority = _EVIDENCE_TYPE_PRIORITY.get(str(item.get("type") or ""), 0)
    if item.get("file"):
        priority += 6
    if item.get("line_start") is not None:
        priority += 4
    return priority


def _selection_reason_for_evidence(item: dict[str, Any]) -> str:
    signal_type = str(item.get("type") or "evidence")
    if item.get("file") and item.get("line_start") is not None:
        return f"strongest infrastructure evidence is a concrete {signal_type} code anchor"
    if item.get("file"):
        return f"strongest infrastructure evidence is a concrete {signal_type} file anchor"
    return f"strongest infrastructure evidence falls back to {signal_type} metadata"


def _line_for_offset(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


def _normalize_path(path: str) -> str:
    normalized = (path or ".").replace("\\", "/").strip()
    if not normalized:
        return "."
    return normalized.strip("/") or "."


def _confidence_for(signals: set[str]) -> float:
    score = 0.0
    for signal in signals:
        score += _SIGNAL_WEIGHTS.get(signal, 0.0)
    score = min(0.96, 0.18 + score)
    return round(score, 2)


def _confidence_label(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"