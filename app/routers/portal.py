"""Portail utilisateur."""
import logging

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..database import db_cursor
from ..services import clone_manager, guacamole
from .auth import current_user, require_user

log = logging.getLogger("vdi-orchestrator")
router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _templates_for_user(username: str, user_groups: list[str]) -> list[dict]:
    with db_cursor(dict_rows=True) as (conn, cur):
        cur.execute("""
            SELECT t.*,
                   COALESCE(array_agg(tg.guacamole_group_name) FILTER (WHERE tg.guacamole_group_name IS NOT NULL), '{}') AS groups
            FROM vdi_template t
            LEFT JOIN vdi_template_group tg ON tg.template_id = t.id
            WHERE t.enabled = true
            GROUP BY t.id
            ORDER BY t.display_name
        """)
        rows = [dict(r) for r in cur.fetchall()]

    visible = []
    for row in rows:
        allowed_groups = list(row["groups"])
        # Un template sans groupe assigné est visible par tous
        if not allowed_groups or set(allowed_groups) & set(user_groups):
            row["groups"] = allowed_groups
            visible.append(row)
    return visible


@router.get("/", response_class=HTMLResponse)
async def portal(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    username = user["username"]
    visible = _templates_for_user(username, user["groups"])
    my_clones = clone_manager.list_clones(username=username)

    clone_by_template = {c["template_id"]: c for c in my_clones}
    for c in my_clones:
        if c.get("guac_connection_id"):
            c["guac_url"] = guacamole.guac_client_url(c["guac_connection_id"])

    # Compter les clones actifs par template pour l'affichage de capacité
    counts = {}
    with db_cursor() as (conn, cur):
        cur.execute("SELECT template_id, COUNT(*) FROM vdi_clone GROUP BY template_id")
        counts = {r[0]: r[1] for r in cur.fetchall()}

    for tpl in visible:
        tpl["current_clones"] = counts.get(tpl["id"], 0)
        tpl["my_clone"] = clone_by_template.get(tpl["id"])
        if tpl["my_clone"] and tpl["my_clone"].get("guac_connection_id"):
            tpl["my_clone"]["guac_url"] = guacamole.guac_client_url(tpl["my_clone"]["guac_connection_id"])

    return templates.TemplateResponse("portal.html", {
        "request": request,
        "user": user,
        "templates_list": visible,
        "my_clones": my_clones,
    })
