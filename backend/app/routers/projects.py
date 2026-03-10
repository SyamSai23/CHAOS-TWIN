import shutil

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import UPLOAD_DIR, WORKSPACE_DIR
from app.db.session import get_db
from app.models.project import Project
from app.models.upload import Upload
from app.models.scan import Scan
from app.models.graph_node import GraphNode
from app.models.graph_edge import GraphEdge
from app.models.simulation_run import SimulationRun
from app.models.sequence_diagram import SequenceDiagram
from app.schemas import ProjectCreate, ProjectResponse

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(name=data.name, path=data.path)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at.desc()).all()


@router.delete("/{project_id}", status_code=200)
def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Delete related DB rows (order matters due to FK constraints)
    # 1. sequence_diagrams (FK → projects, scans)
    db.query(SequenceDiagram).filter(SequenceDiagram.project_id == project_id).delete()
    # 2. simulation_runs (FK → projects, scans, graph_nodes)
    db.query(SimulationRun).filter(SimulationRun.project_id == project_id).delete()
    # 3. graph_edges (FK → graph_nodes)
    db.query(GraphEdge).filter(GraphEdge.project_id == project_id).delete()
    # 4. graph_nodes (FK → scans)
    db.query(GraphNode).filter(GraphNode.project_id == project_id).delete()
    # 5. scans (FK → uploads)
    db.query(Scan).filter(Scan.project_id == project_id).delete()

    # 6. uploads (collect storage paths first, then delete rows)
    uploads = db.query(Upload).filter(Upload.project_id == project_id).all()
    upload_paths = [u.storage_path for u in uploads]
    db.query(Upload).filter(Upload.project_id == project_id).delete()

    # 7. Delete the project itself
    db.delete(project)
    db.commit()

    # Clean up files on disk (best-effort, don't fail if missing)
    for path in upload_paths:
        try:
            full = UPLOAD_DIR / path
            if full.is_file():
                full.unlink()
        except OSError:
            pass

    # Remove workspace folder for this project
    workspace = WORKSPACE_DIR / project_id
    if workspace.is_dir():
        shutil.rmtree(workspace, ignore_errors=True)

    return {"deleted": True}
