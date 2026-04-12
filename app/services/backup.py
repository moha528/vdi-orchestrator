"""Sauvegarde et restauration du /home utilisateur des VMs."""
import os
import logging
import asyncio
from pathlib import Path
from typing import Optional

import paramiko

from ..config import settings

log = logging.getLogger("vdi-orchestrator")


def _backup_path(username: str, template_id: int) -> Path:
    """Chemin du fichier backup pour un user+template."""
    d = Path(settings.BACKUP_DIR) / username
    d.mkdir(parents=True, exist_ok=True)
    return d / f"template_{template_id}.tar.gz"


def _ssh_client(ip: str, vm_user: str, vm_password: str) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=ip, port=22,
        username=vm_user, password=vm_password,
        timeout=15, banner_timeout=15, auth_timeout=15,
    )
    return client


def has_backup(username: str, template_id: int) -> bool:
    return _backup_path(username, template_id).exists()


def backup_info(username: str, template_id: int) -> Optional[dict]:
    p = _backup_path(username, template_id)
    if not p.exists():
        return None
    stat = p.stat()
    return {
        "path": str(p),
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "modified": stat.st_mtime,
    }


async def backup_home(ip: str, username: str, template_id: int,
                       vm_user: str, vm_password: str) -> Optional[dict]:
    """Sauvegarde /home/{vm_user} depuis la VM vers le stockage local.

    Returns dict avec les infos du backup, ou None en cas d'echec.
    """
    dest = _backup_path(username, template_id)
    remote_tar = "/tmp/_vdi_home_backup.tar.gz"
    max_bytes = settings.BACKUP_MAX_SIZE_MB * 1024 * 1024

    def _do_backup():
        ssh = None
        try:
            ssh = _ssh_client(ip, vm_user, vm_password)

            # Vérifier la taille du home avant de tar
            stdin, stdout, stderr = ssh.exec_command(
                f"du -sb /home/{vm_user} 2>/dev/null | cut -f1"
            )
            size_str = stdout.read().decode().strip()
            if size_str and size_str.isdigit():
                home_size = int(size_str)
                if home_size > max_bytes:
                    log.warning(
                        f"Backup skip: /home/{vm_user} trop volumineux "
                        f"({home_size // (1024*1024)} Mo > {settings.BACKUP_MAX_SIZE_MB} Mo) "
                        f"pour {username}/template_{template_id}"
                    )
                    return None

            # Créer le tar.gz sur la VM
            stdin, stdout, stderr = ssh.exec_command(
                f"tar czf {remote_tar} -C /home {vm_user} 2>/dev/null"
            )
            exit_code = stdout.channel.recv_exit_status()
            if exit_code != 0:
                err = stderr.read().decode().strip()
                log.warning(f"Backup tar failed (exit {exit_code}): {err}")
                return None

            # Vérifier la taille du tar
            stdin, stdout, stderr = ssh.exec_command(f"stat -c%s {remote_tar}")
            tar_size_str = stdout.read().decode().strip()
            if tar_size_str.isdigit() and int(tar_size_str) > max_bytes:
                log.warning(f"Backup tar trop volumineux ({int(tar_size_str)} bytes), skip")
                ssh.exec_command(f"rm -f {remote_tar}")
                return None

            # Télécharger via SFTP
            sftp = ssh.open_sftp()
            try:
                sftp.get(remote_tar, str(dest))
            finally:
                sftp.close()

            # Nettoyage distant
            ssh.exec_command(f"rm -f {remote_tar}")

            return backup_info(username, template_id)

        except Exception as e:
            log.error(f"Backup /home/{vm_user} failed pour {username}: {e}")
            # Supprimer un fichier partiel
            if dest.exists():
                dest.unlink(missing_ok=True)
            return None
        finally:
            if ssh:
                ssh.close()

    return await asyncio.to_thread(_do_backup)


async def restore_home(ip: str, username: str, template_id: int,
                        vm_user: str, vm_password: str) -> bool:
    """Restaure le backup du home sur la nouvelle VM.

    Returns True si la restauration a réussi, False sinon.
    """
    src = _backup_path(username, template_id)
    if not src.exists():
        return False

    remote_tar = "/tmp/_vdi_home_restore.tar.gz"

    def _do_restore():
        ssh = None
        try:
            ssh = _ssh_client(ip, vm_user, vm_password)

            # Upload via SFTP
            sftp = ssh.open_sftp()
            try:
                sftp.put(str(src), remote_tar)
            finally:
                sftp.close()

            # Extraire par-dessus le home existant
            stdin, stdout, stderr = ssh.exec_command(
                f"tar xzf {remote_tar} -C /home 2>/dev/null"
            )
            exit_code = stdout.channel.recv_exit_status()
            if exit_code != 0:
                err = stderr.read().decode().strip()
                log.warning(f"Restore tar extract failed (exit {exit_code}): {err}")
                return False

            # Remettre les bons droits
            stdin, stdout, stderr = ssh.exec_command(
                f"chown -R {vm_user}:{vm_user} /home/{vm_user} 2>/dev/null"
            )
            stdout.channel.recv_exit_status()

            # Nettoyage
            ssh.exec_command(f"rm -f {remote_tar}")

            log.info(f"Restore OK: {username}/template_{template_id} -> /home/{vm_user}")
            return True

        except Exception as e:
            log.error(f"Restore /home/{vm_user} failed pour {username}: {e}")
            return False
        finally:
            if ssh:
                ssh.close()

    return await asyncio.to_thread(_do_restore)


def delete_backup(username: str, template_id: int) -> bool:
    p = _backup_path(username, template_id)
    if p.exists():
        p.unlink()
        log.info(f"Backup supprimé: {username}/template_{template_id}")
        return True
    return False


def list_backups(username: Optional[str] = None) -> list[dict]:
    base = Path(settings.BACKUP_DIR)
    if not base.exists():
        return []
    results = []
    dirs = [base / username] if username else base.iterdir()
    for user_dir in dirs:
        if not user_dir.is_dir():
            continue
        for f in user_dir.glob("template_*.tar.gz"):
            try:
                tid = int(f.stem.replace("template_", ""))
            except ValueError:
                continue
            stat = f.stat()
            results.append({
                "username": user_dir.name,
                "template_id": tid,
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "modified": stat.st_mtime,
            })
    return results
