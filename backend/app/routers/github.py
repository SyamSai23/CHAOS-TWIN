import asyncio
import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, urlopen
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import (
    FRONTEND_URL,
    GITHUB_CLIENT_ID,
    GITHUB_CLIENT_SECRET,
    UPLOAD_DIR,
    WORKSPACE_DIR,
)
from app.db.session import get_db
from app.models.graph_edge import GraphEdge
from app.models.graph_node import GraphNode
from app.models.project import Project
from app.models.project_understanding import ProjectUnderstanding
from app.models.route_analysis import RouteAnalysis
from app.models.scan import Scan
from app.models.sequence_diagram import SequenceDiagram
from app.models.simulation_run import SimulationRun
from app.models.upload import Upload
from app.services.file_indexer import run_indexing_pipeline
from app.services.project_model_storage import produce_project_model_snapshot
from app.services.scanner_v3 import extract_zip, run_full_scan, unwrap_root_dir

router = APIRouter(tags=["github"])

GITHUB_TIMEOUT_SECONDS = 30
GITHUB_OAUTH_STATES: dict[str, datetime] = {}


class GitHubImportRequest(BaseModel):
    owner: str
    repo: str
    branch: str
    github_token: str
    project_name: str


class GitHubHTTPResponse:
    def __init__(self, status_code: int, headers: Message, body: bytes):
        self.status_code = status_code
        self.headers = headers
        self._body = body

    def json(self) -> Any:
        if not self._body:
            return {}
        return json.loads(self._body.decode("utf-8"))

    def iter_content(self, chunk_size: int = 1024 * 1024):
        for index in range(0, len(self._body), chunk_size):
            yield self._body[index:index + chunk_size]

    def close(self) -> None:
        return None


def _cleanup_oauth_states() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    expired = [state for state, created_at in GITHUB_OAUTH_STATES.items() if created_at < cutoff]
    for state in expired:
        GITHUB_OAUTH_STATES.pop(state, None)


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="GitHub session expired — reconnect")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="GitHub session expired — reconnect")

    return token.strip()


def _github_request(
    method: str,
    url: str,
    token: str,
    *,
    json_payload: Optional[dict[str, Any]] = None,
    data_payload: Optional[dict[str, Any]] = None,
    accept: str = "application/vnd.github+json",
    allow_redirects: bool = True,
    stream: bool = False,
) -> GitHubHTTPResponse:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "User-Agent": "Chaos-Twin",
    }
    payload: Optional[bytes] = None
    if json_payload is not None:
        payload = json.dumps(json_payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif data_payload is not None:
        payload = urlencode(data_payload).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = URLRequest(url, data=payload, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=GITHUB_TIMEOUT_SECONDS) as response:
            body = response.read()
            return GitHubHTTPResponse(response.getcode(), response.headers, body)
    except HTTPError as response:
        body = response.read()
        status_code = response.code
        detail = "GitHub request failed."
        try:
            parsed_body = json.loads(body.decode("utf-8"))
            detail = str(parsed_body.get("message") or detail)
        except Exception:
            pass
        if status_code == 401:
            raise HTTPException(status_code=401, detail="GitHub session expired — reconnect")
        if status_code == 403:
            if response.headers.get("X-RateLimit-Remaining") == "0":
                raise HTTPException(status_code=403, detail="GitHub rate limit reached. Try again in an hour.")
            raise HTTPException(status_code=403, detail="Could not download repository. Make sure it's accessible.")
        raise HTTPException(status_code=400, detail=detail)
    except URLError:
        raise HTTPException(status_code=502, detail="GitHub request failed.")


def _save_temp_zip_from_github(owner: str, repo: str, branch: str, token: str) -> Path:
    response = _github_request(
        "GET",
        f"https://api.github.com/repos/{owner}/{repo}/zipball/{branch}",
        token,
        allow_redirects=True,
        stream=True,
        accept="application/vnd.github+json",
    )
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    try:
        with temp_file as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    finally:
        response.close()
    return Path(temp_file.name)


def _store_download_as_upload(project_id: str, repo: str, branch: str, temp_zip_path: Path, db: Session) -> Upload:
    project_upload_dir = Path(UPLOAD_DIR) / project_id
    project_upload_dir.mkdir(parents=True, exist_ok=True)
    safe_filename = os.path.basename(f"{repo}-{branch}.zip")
    file_path = project_upload_dir / safe_filename
    shutil.copyfile(temp_zip_path, file_path)

    upload = Upload(
        project_id=project_id,
        filename=safe_filename,
        storage_path=str(file_path),
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return upload


def _cleanup_project_import(project_id: str, db: Session) -> None:
    db.query(SequenceDiagram).filter(SequenceDiagram.project_id == project_id).delete()
    db.query(SimulationRun).filter(SimulationRun.project_id == project_id).delete()
    db.query(GraphEdge).filter(GraphEdge.project_id == project_id).delete()
    db.query(GraphNode).filter(GraphNode.project_id == project_id).delete()
    db.query(RouteAnalysis).filter(RouteAnalysis.project_id == project_id).delete()
    db.query(Scan).filter(Scan.project_id == project_id).delete()
    db.query(Upload).filter(Upload.project_id == project_id).delete()
    db.query(ProjectUnderstanding).filter(ProjectUnderstanding.project_id == project_id).delete()
    db.query(Project).filter(Project.id == project_id).delete()
    db.commit()

    upload_dir = Path(UPLOAD_DIR) / project_id
    workspace_dir = Path(WORKSPACE_DIR) / project_id
    shutil.rmtree(upload_dir, ignore_errors=True)
    shutil.rmtree(workspace_dir, ignore_errors=True)


def _scan_project_upload(project: Project, upload: Upload, db: Session) -> Scan:
    project_workspace_dir = Path(WORKSPACE_DIR) / project.id
    workspace_path = project_workspace_dir / upload.id
    if project_workspace_dir.is_dir():
        shutil.rmtree(project_workspace_dir)
    extract_zip(upload.storage_path, str(workspace_path))
    effective_root = unwrap_root_dir(str(workspace_path))

    result = run_full_scan(effective_root)
    key_files_flat = [item["path"] if isinstance(item, dict) else item for item in result["key_files"]]

    scan = Scan(
        project_id=project.id,
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

    project.executive_summary = None
    db.query(SequenceDiagram).filter(SequenceDiagram.project_id == project.id).delete()
    db.query(SimulationRun).filter(SimulationRun.project_id == project.id).delete()
    db.query(GraphEdge).filter(GraphEdge.project_id == project.id).delete()
    db.query(GraphNode).filter(GraphNode.project_id == project.id).delete()
    db.query(RouteAnalysis).filter(RouteAnalysis.project_id == project.id).delete()

    understanding = db.query(ProjectUnderstanding).filter(ProjectUnderstanding.project_id == project.id).first()
    if not understanding:
        understanding = ProjectUnderstanding(project_id=project.id, status="pending")
        db.add(understanding)
    else:
        understanding.status = "pending"

    db.commit()
    db.refresh(scan)

    try:
        produce_project_model_snapshot(scan.id)
    except Exception:
        pass

    scan_dict = {
        "project_name": project.name,
        "files": scan.files,
        "import_graph": scan.import_graph,
        "dependencies": scan.dependencies,
        "routes": scan.routes,
        "components": scan.components,
        "frameworks": scan.frameworks,
        "languages": scan.languages,
    }
    asyncio.create_task(run_indexing_pipeline(project.id, upload.storage_path, scan_dict))
    return scan


@router.get("/auth/github")
def auth_github(request: Request):
    if not GITHUB_CLIENT_ID:
        raise HTTPException(status_code=503, detail="GitHub OAuth is not configured.")

    _cleanup_oauth_states()
    state = str(uuid4())
    GITHUB_OAUTH_STATES[state] = datetime.now(timezone.utc)
    redirect_uri = str(request.url_for("github_oauth_callback"))
    params = urlencode(
        {
            "client_id": GITHUB_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "public_repo",
            "state": state,
        }
    )
    return RedirectResponse(url=f"https://github.com/login/oauth/authorize?{params}")


@router.get("/auth/github/callback", name="github_oauth_callback")
def github_oauth_callback(code: str, state: str, request: Request):
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="GitHub OAuth is not configured.")

    _cleanup_oauth_states()
    created_at = GITHUB_OAUTH_STATES.pop(state, None)
    if created_at is None:
        raise HTTPException(status_code=400, detail="GitHub session expired — reconnect")

    redirect_uri = str(request.url_for("github_oauth_callback"))
    token_request = URLRequest(
        "https://github.com/login/oauth/access_token",
        data=urlencode(
            {
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            }
        ).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "User-Agent": "Chaos-Twin",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlopen(token_request, timeout=GITHUB_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="GitHub authorization failed.")

    access_token = str(body.get("access_token") or "").strip()
    if not access_token:
        raise HTTPException(status_code=400, detail="GitHub authorization failed.")

    frontend_target = f"{FRONTEND_URL.rstrip('/')}/github/repos?{urlencode({'token': access_token})}"
    return RedirectResponse(url=frontend_target)


@router.get("/github/repos")
def list_github_repos(authorization: Optional[str] = Header(default=None)):
    token = _extract_bearer_token(authorization)
    response = _github_request(
        "GET",
        "https://api.github.com/user/repos?sort=updated&per_page=50&type=all",
        token,
    )
    repos = response.json()
    return [
        {
            "id": repo.get("id"),
            "name": repo.get("name"),
            "full_name": repo.get("full_name"),
            "description": repo.get("description"),
            "language": repo.get("language"),
            "updated_at": repo.get("updated_at"),
            "default_branch": repo.get("default_branch"),
            "private": bool(repo.get("private")),
            "stargazers_count": int(repo.get("stargazers_count") or 0),
        }
        for repo in repos
    ]


@router.get("/github/repos/{owner}/{repo}/branches")
def list_github_branches(owner: str, repo: str, authorization: Optional[str] = Header(default=None)):
    token = _extract_bearer_token(authorization)
    response = _github_request(
        "GET",
        f"https://api.github.com/repos/{owner}/{repo}/branches",
        token,
    )
    branches = response.json()
    return [{"name": branch.get("name")} for branch in branches if branch.get("name")]


@router.post("/github/import")
async def import_github_repo(payload: GitHubImportRequest, db: Session = Depends(get_db)):
    project = Project(
        name=payload.project_name,
        path=f"github://{payload.owner}/{payload.repo}@{payload.branch}",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    temp_zip_path: Optional[Path] = None
    try:
        temp_zip_path = _save_temp_zip_from_github(payload.owner, payload.repo, payload.branch, payload.github_token)
        upload = _store_download_as_upload(project.id, payload.repo, payload.branch, temp_zip_path, db)
        _scan_project_upload(project, upload, db)
        return {
            "project_id": project.id,
            "status": "scanning",
            "project": {
                "id": project.id,
                "name": project.name,
                "path": project.path,
                "created_at": project.created_at.isoformat() if project.created_at else None,
            },
        }
    except HTTPException:
        db.rollback()
        _cleanup_project_import(project.id, db)
        raise
    except Exception as exc:
        db.rollback()
        _cleanup_project_import(project.id, db)
        raise HTTPException(status_code=500, detail=str(exc) or "Repository import failed.")
    finally:
        if temp_zip_path and temp_zip_path.exists():
            temp_zip_path.unlink(missing_ok=True)
