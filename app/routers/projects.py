"""Projects router for CritX backend.
Provides CRUD endpoints for project resources, respecting the access control
rules defined in `app.access.can_view` and role requirements.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from typing import Any, List, Dict

from app.deps import current_user, require_role
from app.access import can_view
from app.db import query_one, query_all, execute
from app.services.projects import create_project, publish_charter

router = APIRouter()

# Helper to serialize sqlite Row objects
def row_to_dict(row: Any) -> Dict[str, Any]:
    return dict(row) if row else {}

@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_new_project(request: Request, payload: Dict[str, Any], user: Any = Depends(require_role("sponsor"))):
    """Create a new project. Only users with the *sponsor* role may create.
    The payload is passed directly to the `create_project` service.
    """
    project_id = create_project(user, payload)
    return {"project_id": project_id}

@router.get("/projects")
async def list_projects(request: Request, user: Any = Depends(current_user)):
    """List projects visible to the caller.
    * Public projects are always listed.
    * Sponsors see their own projects regardless of sensitivity.
    * Authenticated non‑sponsor users see public projects only.
    """
    if user:
        rows = query_all(
            "SELECT * FROM projects WHERE sensitivity_label = 'public' OR sponsor_id = ?",
            (user["id"],),
        )
    else:
        rows = query_all(
            "SELECT * FROM projects WHERE sensitivity_label = 'public'",
        )
    return [row_to_dict(r) for r in rows]

@router.get("/projects/{project_id}")
async def get_project(project_id: int, request: Request, user: Any = Depends(current_user)):
    """Retrieve a single project.
    Access is granted if the caller can view the project's brief according to
    `can_view`. Public summary and charter are always visible; the confidential
    brief requires the appropriate permission.
    """
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # Determine if the caller may view the confidential brief
    if not can_view(user, project, "brief"):
        # Hide confidential fields but still return the rest
        public_project = dict(project)
        public_project.pop("confidential_brief", None)
        return public_project
    return row_to_dict(project)

@router.patch("/projects/{project_id}")
async def update_project(project_id: int, changes: Dict[str, Any], request: Request, user: Any = Depends(require_role("sponsor"))):
    """Publish a new charter version (partial update).
    Only the owning sponsor may publish changes. The service validates model
    transitions and rewards rules.
    """
    # Verify ownership
    proj = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if proj["sponsor_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the owning sponsor can modify this project")
    new_version = publish_charter(user, project_id, changes)
    return {"project_id": project_id, "new_charter_version": new_version}

@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: int, request: Request, user: Any = Depends(require_role("sponsor"))):
    """Delete a project.
    Only the owning sponsor may delete a project.
    """
    proj = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if proj["sponsor_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the owning sponsor can delete this project")
    execute("DELETE FROM projects WHERE id = ?", (project_id,))
    # Also cascade delete related charters, acceptances, milestones etc. SQLite FK cascades are enabled.
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)
