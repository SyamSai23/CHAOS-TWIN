import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import WORKSPACE_DIR
from app.db.session import get_db
from app.models.project import Project
from app.models.upload import Upload
from app.models.scan import Scan
from app.schemas import DeepDiveRequest, DeepDiveResponse
from app.services.deep_dive import run_deep_dive
from app.services.scanner_v3 import unwrap_root_dir

router = APIRouter(
    prefix="/projects/{project_id}/components",
    tags=["deep-dive"],
)


@router.post("/deep-dive", response_model=DeepDiveResponse, status_code=200)
def deep_dive(
    project_id: str,
    body: DeepDiveRequest,
    db: Session = Depends(get_db),
):
    """Run a deep-dive analysis for a single component."""

    # 1. Validate project
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 2. Get latest scan
    scan = (
        db.query(Scan)
        .filter(Scan.project_id == project_id)
        .order_by(Scan.created_at.desc())
        .first()
    )
    if not scan:
        raise HTTPException(status_code=404, detail="No scan found. Run a scan first.")

    # 3. Find matching component
    components = scan.components or []
    target_comp = None
    for comp in components:
        if comp.get("root_path") == body.component_root:
            target_comp = comp
            break

    if target_comp is None:
        available = [c.get("root_path", "?") for c in components]
        raise HTTPException(
            status_code=404,
            detail=f"Component '{body.component_root}' not found. "
                   f"Available: {available}",
        )

    # 4. Resolve workspace root (same logic as scan router)
    upload = (
        db.query(Upload)
        .filter(Upload.id == scan.upload_id)
        .first()
    )
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found for this scan.")

    workspace_path = os.path.join(str(WORKSPACE_DIR), project_id, upload.id)
    if not os.path.isdir(workspace_path):
        raise HTTPException(
            status_code=404,
            detail="Workspace files not found on disk. Re-upload and re-scan.",
        )
    effective_root = unwrap_root_dir(workspace_path)

    # 5. Run deep dive
    result = run_deep_dive(
        component=target_comp,
        all_files=scan.files,
        workspace_root=effective_root,
    )

    return DeepDiveResponse(project_id=project_id, **result)
