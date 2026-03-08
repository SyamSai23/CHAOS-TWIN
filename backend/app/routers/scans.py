import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.config import WORKSPACE_DIR
from app.models.project import Project
from app.models.upload import Upload
from app.models.scan import Scan
from app.schemas import ScanResponse
from app.services.scanner import (
    collect_file_inventory,
    collect_entry_points,
    collect_key_files,
    collect_top_level_dirs,
    count_extensions,
    detect_components,
    detect_frameworks,
    detect_languages,
    extract_zip,
    infer_project_type,
    unwrap_root_dir,
)

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

    # 4. Walk files and collect inventory (relative to effective root)
    files = collect_file_inventory(effective_root)

    # 5. Detect languages/frameworks and build richer summary fields
    languages = detect_languages(files)
    frameworks = detect_frameworks(files)
    key_files = collect_key_files(files)
    top_level_dirs = collect_top_level_dirs(effective_root)
    extension_counts = count_extensions(files)
    entry_points = collect_entry_points(files)
    components = detect_components(top_level_dirs, files, key_files, entry_points)
    project_type = infer_project_type(files, languages, frameworks, top_level_dirs, components)

    # 6. Save scan result
    scan = Scan(
        project_id=project_id,
        upload_id=upload.id,
        status="completed",
        file_count=len(files),
        files=files,
        languages=languages,
        frameworks=frameworks,
        key_files=key_files,
        top_level_dirs=top_level_dirs,
        extension_counts=extension_counts,
        project_type=project_type,
        entry_points=entry_points,
        components=components,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan
