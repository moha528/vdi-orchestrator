"""Pages admin (HTML)."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..database import db_cursor
from ..services import clone_manager, guacamole
from .auth import current_user

log = logging.getLogger("vdi-orchestrator")
router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _load_templates() -> list[dict]:
    with db_cursor(dict_rows=True) as (conn, cur):
        cur.execute("""
            SELECT t.*,
                   COALESCE(array_agg(tg.guacamole_group_name) FILTER (WHERE tg.guacamole_group_name IS NOT NULL), '{}') AS groups
            FROM vdi_template t
            LEFT JOIN vdi_template_group tg ON tg.template_id = t.id
            GROUP BY t.id
            ORDER BY t.display_name
        """)
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            d["groups"] = list(d["groups"])
            if d.get("created_at") is not None:
                d["created_at"] = str(d["created_at"])
            rows.append(d)
        return rows


def _load_history(limit: int = 100) -> list[dict]:
    with db_cursor(dict_rows=True) as (conn, cur):
        cur.execute("""
            SELECT * FROM vdi_session_log
            ORDER BY created_at DESC LIMIT %s
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]


def _stats() -> dict:
    with db_cursor() as (conn, cur):
        cur.execute("SELECT COUNT(*) FROM vdi_session_log")
        total = cur.fetchone()[0]
        cur.execute("""
            SELECT AVG(duration_seconds)::INT
            FROM vdi_session_log WHERE duration_seconds IS NOT NULL
        """)
        avg = cur.fetchone()[0] or 0
        cur.execute("""
            SELECT template_name, COUNT(*) AS c
            FROM vdi_session_log
            WHERE template_name IS NOT NULL
            GROUP BY template_name ORDER BY c DESC LIMIT 1
        """)
        top = cur.fetchone()
    return {
        "total_sessions": total,
        "avg_duration_seconds": avg,
        "top_template": top[0] if top else None,
    }


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not user.get("is_admin"):
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": user,
        "vdi_templates": _load_templates(),
        "active_clones": clone_manager.list_clones(),
        "history": _load_history(),
        "stats": _stats(),
        "guac_users": guacamole.list_users(),
        "guac_groups": guacamole.list_groups(),
    })
