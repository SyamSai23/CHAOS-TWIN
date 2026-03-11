"""Best-effort canonical ProjectModel production and storage.

This service is intentionally additive:
- scan remains the source of truth for the public scan API response.
- canonical model production happens after scan commit.
- failures are logged and captured in snapshot storage without breaking scan success.

Next migration stage:
- graph builder should read the latest successful ProjectModelSnapshot for a scan.
- route analysis can enrich snapshot content or produce follow-on derived snapshots.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.domain.system_model import build_project_model_from_scan, validate_project_model
from app.models.project import Project
from app.models.project_model_snapshot import ProjectModelSnapshot
from app.models.scan import Scan
from app.models.upload import Upload

logger = logging.getLogger(__name__)


def produce_project_model_snapshot(scan_id: str) -> None:
    """Build and persist a canonical ProjectModel for a completed scan.

    Failure handling:
    - Any canonical build or validation failure is logged.
    - A failed snapshot row is recorded when possible.
    - No exception is allowed to escape because scan success must not be downgraded.
    """

    db = SessionLocal()
    try:
        _produce_project_model_snapshot(db, scan_id)
    except Exception:
        logger.exception(
            "Unexpected canonical ProjectModel production failure for scan %s",
            scan_id,
        )
        db.rollback()
    finally:
        db.close()


def _produce_project_model_snapshot(db: Session, scan_id: str) -> None:
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        logger.warning("Skipping canonical ProjectModel build: scan %s not found", scan_id)
        return

    project = db.query(Project).filter(Project.id == scan.project_id).first()
    if not project:
        logger.warning(
            "Skipping canonical ProjectModel build: project %s not found for scan %s",
            scan.project_id,
            scan_id,
        )
        return

    upload = db.query(Upload).filter(Upload.id == scan.upload_id).first()
    snapshot = _get_or_create_snapshot(db, scan.project_id, scan.id)
    snapshot.model_version = "system-model/v1"
    snapshot.status = "building"
    snapshot.error_message = None
    snapshot.validation_errors = []
    snapshot.build_metadata = {
        "project_id": project.id,
        "scan_id": scan.id,
        "producer": "produce_project_model_snapshot",
    }
    db.flush()

    try:
        model = build_project_model_from_scan(project=project, scan=scan, upload=upload)
        validation_errors = validate_project_model(model)
        snapshot.validation_errors = validation_errors
        snapshot.build_metadata = {
            **snapshot.build_metadata,
            "entity_counts": {
                "sources": len(model.sources),
                "components": len(model.components),
                "modules": len(model.modules),
                "routes": len(model.routes),
                "services": len(model.services),
                "data_stores": len(model.data_stores),
                "external_integrations": len(model.external_integrations),
                "runtime_nodes": len(model.runtime_nodes),
                "relations": len(model.relations),
                "evidence": len(model.evidence),
            },
        }
        if validation_errors:
            snapshot.status = "rejected_invalid"
            snapshot.model_data = None
            snapshot.error_message = "ProjectModel validation failed"
            db.commit()
            logger.warning(
                "Canonical ProjectModel rejected for project %s scan %s with %s validation errors",
                project.id,
                scan.id,
                len(validation_errors),
            )
            return

        snapshot.model_data = model.to_dict()
        snapshot.status = "completed"
        snapshot.error_message = None
        db.commit()
        logger.info(
            "Canonical ProjectModel produced for project %s scan %s with status %s",
            project.id,
            scan.id,
            snapshot.status,
        )
    except Exception as exc:
        db.rollback()
        logger.exception(
            "Canonical ProjectModel build failed for project %s scan %s",
            project.id,
            scan.id,
        )
        _record_failed_snapshot(
            db=db,
            project_id=project.id,
            scan_id=scan.id,
            error_message=str(exc),
        )


def _get_or_create_snapshot(db: Session, project_id: str, scan_id: str) -> ProjectModelSnapshot:
    snapshot = (
        db.query(ProjectModelSnapshot)
        .filter(ProjectModelSnapshot.scan_id == scan_id)
        .first()
    )
    if snapshot:
        return snapshot

    snapshot = ProjectModelSnapshot(
        project_id=project_id,
        scan_id=scan_id,
        model_version="system-model/v1",
        status="pending",
        model_data=None,
        validation_errors=[],
        build_metadata={},
        error_message=None,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _record_failed_snapshot(db: Session, project_id: str, scan_id: str, error_message: str) -> None:
    try:
        snapshot = _get_or_create_snapshot(db, project_id, scan_id)
        snapshot.status = "failed"
        snapshot.model_data = None
        snapshot.validation_errors = []
        snapshot.error_message = error_message[:4000]
        snapshot.build_metadata = {
            "project_id": project_id,
            "scan_id": scan_id,
            "producer": "produce_project_model_snapshot",
        }
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Failed to persist ProjectModelSnapshot failure record for project %s scan %s",
            project_id,
            scan_id,
        )


def get_latest_project_model_snapshot(db: Session, project_id: str) -> ProjectModelSnapshot | None:
    return (
        db.query(ProjectModelSnapshot)
        .filter(
            ProjectModelSnapshot.project_id == project_id,
            ProjectModelSnapshot.status == "completed",
        )
        .order_by(ProjectModelSnapshot.created_at.desc())
        .first()
    )


def get_project_model_snapshot_for_scan(db: Session, scan_id: str) -> ProjectModelSnapshot | None:
    return (
        db.query(ProjectModelSnapshot)
        .filter(ProjectModelSnapshot.scan_id == scan_id)
        .first()
    )