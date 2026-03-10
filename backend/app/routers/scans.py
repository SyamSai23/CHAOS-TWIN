import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.config import WORKSPACE_DIR
from app.models.project import Project
from app.models.upload import Upload
from app.models.scan import Scan
from app.schemas import ScanResponse
from app.services.scanner_v3 import extract_zip, unwrap_root_dir, run_full_scan

router = APIRouter(prefix="/projects/{project_id}/scan", tags=["scans"])

@router.post("", response_model=ScanResponse, status_code=201)
def scan_project(project_id: str, db: Session = Depends(get_db)):
    # 1. Check project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 2. Find the latest upload for this project
    upload = (
        db.query(Upload)
        .filter(Upload.project_id == project_id)
        .order_by(Upload.created_at.desc())
        .first()
    )
    if not upload:
        raise HTTPException(status_code=404, detail="No uploads found for this project")

    # 3. Extract the ZIP into a workspace folder
    workspace_path = os.path.join(
        str(WORKSPACE_DIR), project_id, upload.id
    )
    extract_zip(upload.storage_path, workspace_path)

    # 3b. Unwrap single wrapper folder (e.g. PROJECT-main/)
    effective_root = unwrap_root_dir(workspace_path)

    # 4. Run the full V3 scan
    result = run_full_scan(effective_root)

    # 5. Map key_files from list[dict] to list[str] for backward compat
    key_files_flat = [kf["path"] if isinstance(kf, dict) else kf for kf in result["key_files"]]

    # 6. Save scan result
    scan = Scan(
        project_id=project_id,
        upload_id=upload.id,
        status="completed",
        file_count=len(result["files"]),
        files=result["files"],
        languages=result["languages"],
        frameworks=result["frameworks"],
        key_files=key_files_flat,
        top_level_dirs=result["top_level_dirs"],
        extension_counts=result["extension_counts"],
        project_type=result["project_type"],
        entry_points=result["entry_points"],
        components=result["components"],
        # V3 fields
        confidence_scores=result["confidence_scores"],
        dependencies=result["dependencies"],
        service_graph=result["service_graph"],
        routes=result["routes"],
        import_graph=result["import_graph"],
        execution_flow=result["execution_flow"],
        env_variables=result["env_variables"],
        docker_services=result["docker_services"],
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan
