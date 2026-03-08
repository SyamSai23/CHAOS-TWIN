import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.config import UPLOAD_DIR
from app.models.project import Project
from app.models.upload import Upload
from app.schemas import UploadResponse

router = APIRouter(prefix="/projects/{project_id}/upload", tags=["uploads"])

@router.post("", response_model=UploadResponse, status_code=201)
def upload_zip(
    project_id: str,
    file: UploadFile,
    db: Session = Depends(get_db),
):
    # Check that the project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate the file is a ZIP
    if file.content_type not in ("application/zip", "application/x-zip-compressed"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")

    # Build storage directory: uploads/<project_id>/
    project_upload_dir = os.path.join(str(UPLOAD_DIR), project_id)
    os.makedirs(project_upload_dir, exist_ok=True)

    # Save file to disk
    safe_filename = os.path.basename(file.filename or "upload.zip")
    file_path = os.path.join(project_upload_dir, safe_filename)
    with open(file_path, "wb") as f:
        while chunk := file.file.read(1024 * 1024):  # 1 MB chunks
            f.write(chunk)

    # Save metadata in DB
    upload = Upload(
        project_id=project_id,
        filename=safe_filename,
        storage_path=file_path,
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return upload
