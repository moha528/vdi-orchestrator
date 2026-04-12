"""Authentification (login/logout) + middleware session."""
import logging

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from ..services import guacamole

log = logging.getLogger("vdi-orchestrator")
router = APIRouter()
templates = Jinja2Templates(directory="templates")


def current_user(request: Request) -> dict | None:
    user = request.session.get("user")
    if not user:
        return None
    return user


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Non authentifié")
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if not user.get("is_admin"):
        raise HTTPException(403, "Accès administrateur requis")
    return user


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if current_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    ok = False
    try:
        ok = guacamole.authenticate_user(username, password)
    except Exception as e:
        log.error(f"Auth error: {e}")
    if not ok:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Identifiants invalides"},
            status_code=401,
        )
    is_admin = guacamole.is_admin(username)
    groups = guacamole.get_user_groups(username)
    request.session["user"] = {
        "username": username,
        "is_admin": is_admin,
        "groups": groups,
    }
    log.info(f"Login OK: {username} (admin={is_admin})")
    target = "/admin" if is_admin else "/"
    return RedirectResponse(target, status_code=303)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
