"""Accès direct à la DB Guacamole : auth, users, groupes, connexions, historique."""
import base64
import hashlib
import logging
from typing import Optional

from ..config import settings
from ..database import get_db

log = logging.getLogger("vdi-orchestrator")


def ping() -> bool:
    try:
        conn = get_db()
        conn.close()
        return True
    except Exception as e:
        log.warning(f"Guacamole DB ping failed: {e}")
        return False


def authenticate_user(username: str, password: str) -> bool:
    """Vérifie SHA256(password + UPPER(HEX(salt))) == password_hash."""
    if not username or not password:
        return False
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT u.password_hash, u.password_salt, u.disabled
            FROM guacamole_user u
            JOIN guacamole_entity e ON u.entity_id = e.entity_id
            WHERE e.name = %s AND e.type = 'USER'
        """, (username,))
        row = cur.fetchone()
        if not row:
            return False
        pwd_hash, salt, disabled = row
        if disabled:
            return False
        if pwd_hash is None or salt is None:
            return False
        salt_hex = bytes(salt).hex().upper()
        computed = hashlib.sha256((password + salt_hex).encode("utf-8")).digest()
        return computed == bytes(pwd_hash)
    finally:
        conn.close()


def get_user_groups(username: str) -> list[str]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT ge.name
            FROM guacamole_entity ue
            JOIN guacamole_user_group_member m ON m.member_entity_id = ue.entity_id
            JOIN guacamole_user_group ug ON ug.user_group_id = m.user_group_id
            JOIN guacamole_entity ge ON ge.entity_id = ug.entity_id
            WHERE ue.name = %s AND ue.type = 'USER'
        """, (username,))
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def is_admin(username: str) -> bool:
    if username == "guacadmin":
        return True
    if username in settings.EXTRA_ADMINS:
        return True
    # Vérification supplémentaire : les permissions système ADMINISTER
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 1 FROM guacamole_system_permission sp
            JOIN guacamole_entity e ON sp.entity_id = e.entity_id
            WHERE e.name = %s AND e.type = 'USER' AND sp.permission = 'ADMINISTER'
            LIMIT 1
        """, (username,))
        return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        conn.close()


def list_users() -> list[dict]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT e.name, u.disabled,
                   COALESCE(array_agg(ge.name) FILTER (WHERE ge.name IS NOT NULL), '{}')
            FROM guacamole_entity e
            JOIN guacamole_user u ON u.entity_id = e.entity_id
            LEFT JOIN guacamole_user_group_member m ON m.member_entity_id = e.entity_id
            LEFT JOIN guacamole_user_group ug ON ug.user_group_id = m.user_group_id
            LEFT JOIN guacamole_entity ge ON ge.entity_id = ug.entity_id
            WHERE e.type = 'USER'
            GROUP BY e.name, u.disabled
            ORDER BY e.name
        """)
        return [
            {"username": r[0], "disabled": r[1], "groups": list(r[2])}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def list_groups() -> list[str]:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT e.name FROM guacamole_entity e
            JOIN guacamole_user_group ug ON ug.entity_id = e.entity_id
            WHERE e.type = 'USER_GROUP'
            ORDER BY e.name
        """)
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def create_connection(name: str, protocol: str, hostname: str, port: int,
                      username: str = "", password: str = "") -> int:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO guacamole_connection
                (connection_name, protocol, max_connections, max_connections_per_user)
            VALUES (%s, %s, 1, 1)
            RETURNING connection_id
        """, (name, protocol))
        cid = cur.fetchone()[0]

        params = {
            "hostname": hostname,
            "port": str(port),
            "ignore-cert": "true",
            "security": "any",
            "resize-method": "display-update",
        }
        if username:
            params["username"] = username
        if password:
            params["password"] = password
        for k, v in params.items():
            cur.execute("""
                INSERT INTO guacamole_connection_parameter
                    (connection_id, parameter_name, parameter_value)
                VALUES (%s, %s, %s)
            """, (cid, k, v))
        conn.commit()
        log.info(f"Guacamole connection {cid} created ({name})")
        return cid
    finally:
        conn.close()


def grant_connection_permission(connection_id: int, username: str):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO guacamole_connection_permission (entity_id, connection_id, permission)
            SELECT entity_id, %s, 'READ'
            FROM guacamole_entity WHERE name = %s AND type = 'USER'
            ON CONFLICT DO NOTHING
        """, (connection_id, username))
        conn.commit()
    finally:
        conn.close()


def delete_connection(connection_id: int):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM guacamole_connection_parameter WHERE connection_id = %s", (connection_id,))
        cur.execute("DELETE FROM guacamole_connection_permission WHERE connection_id = %s", (connection_id,))
        cur.execute("DELETE FROM guacamole_connection WHERE connection_id = %s", (connection_id,))
        conn.commit()
        log.info(f"Guacamole connection {connection_id} deleted")
    except Exception as e:
        conn.rollback()
        log.warning(f"Delete connection {connection_id} failed: {e}")
    finally:
        conn.close()


def session_state(connection_id: int) -> dict:
    """Retourne {has_history, active, last_end}."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE end_date IS NULL) AS active,
                MAX(end_date) AS last_end
            FROM guacamole_connection_history
            WHERE connection_id = %s
        """, (connection_id,))
        total, active, last_end = cur.fetchone()
        return {
            "has_history": total > 0,
            "active": active > 0,
            "last_end": last_end,
        }
    finally:
        conn.close()


def guac_client_url(connection_id: int) -> str:
    """Deep link vers Guacamole pour cette connexion."""
    token = base64.b64encode(f"{connection_id}\0c\0postgresql".encode()).decode()
    return f"{settings.GUAC_URL}/#/client/{token}"
