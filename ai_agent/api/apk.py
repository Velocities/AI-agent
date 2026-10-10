"""Admin download page for APKs copied by ``ai-agent apk publish``.

Off unless ``APK_DOWNLOADS_ENABLED`` is true and ``APK_PUBLISH_DIR`` is set.
Both are deployment settings (``.env``), read when the process starts.

The page is HTML, like a directory index: name, last-modified time, and size.
Only monitoring admins (``ai-agent config monitoring grant``) may open it.
Everyone else gets 403.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from ai_agent.api.auth import AuthenticatedUser
from ai_agent.api.deps import get_current_user
from ai_agent.api.monitoring import is_monitoring_admin
from ai_agent.apk.listing import list_apk_files, render_apk_index, resolve_published_apk
from ai_agent.config import Settings

router = APIRouter(prefix="/api/apk", tags=["apk"])

_APK_MEDIA_TYPE = "application/vnd.android.package-archive"
_NOT_ENABLED = (
    "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
    "<title>APK builds</title></head><body>"
    "<p>APK downloads are not enabled on this deployment.</p>"
    "</body></html>"
)


def require_apk_admin(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if not is_monitoring_admin(request, user.user_id):
        raise HTTPException(status_code=403, detail="Unauthorized")
    return user


def _enabled_directory(request: Request) -> Path | None:
    settings: Settings = request.app.state.settings
    raw = settings.apk_publish_dir.strip()
    if not settings.apk_downloads_enabled or not raw:
        return None
    return Path(raw).expanduser()


def _disabled_page() -> HTMLResponse:
    return HTMLResponse(_NOT_ENABLED, status_code=404)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def apk_index(
    request: Request,
    _user: AuthenticatedUser = Depends(require_apk_admin),
) -> HTMLResponse:
    directory = _enabled_directory(request)
    if directory is None:
        return _disabled_page()
    return HTMLResponse(render_apk_index(list_apk_files(directory)))


@router.get("/{filename}")
def apk_file(
    filename: str,
    request: Request,
    _user: AuthenticatedUser = Depends(require_apk_admin),
) -> FileResponse:
    directory = _enabled_directory(request)
    if directory is None:
        raise HTTPException(
            status_code=404,
            detail="APK downloads are not enabled on this deployment.",
        )
    path = resolve_published_apk(directory, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="APK not found.")
    return FileResponse(
        path,
        media_type=_APK_MEDIA_TYPE,
        filename=path.name,
    )
