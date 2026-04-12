# VDI Orchestrator — Guide de déploiement

Middleware léger (Python FastAPI, ~30 Mo RAM) qui orchestre le provisioning
dynamique de desktops virtuels via Proxmox API + Guacamole.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Proxmox VE 8.4                       │
│                   192.168.80.10                         │
│                                                         │
│  ┌─────────────────── Docker ────────────────────────┐  │
│  │                                                    │  │
│  │  ┌──────────┐  ┌──────────┐  ┌─────────────────┐  │  │
│  │  │  guacd   │  │ guac-db  │  │   guacamole     │  │  │
│  │  │          │  │ Postgres │  │   :8080         │  │  │
│  │  └──────────┘  └────┬─────┘  └─────────────────┘  │  │
│  │                     │                              │  │
│  │              ┌──────┴──────────┐                   │  │
│  │              │ vdi-orchestrator│  ← NOUVEAU        │  │
│  │              │     :8000      │                    │  │
│  │              └────────────────┘                    │  │
│  └────────────────────────────────────────────────────┘  │
│                                                         │
│  ┌──────────┐  ┌──────────────────────────────────────┐  │
│  │ VM 100   │  │ VM 500-550 (Linked Clones)          │  │
│  │ Template │──│ vdi-default-500, vdi-default-501...  │  │
│  │ mint-xfce│  │ Créés à la demande, détruits après   │  │
│  └──────────┘  └──────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Prérequis

1. **VM 100 (mint-xfce) preparee** :
   ```bash
   # Dans la VM 100 :
   sudo apt update
   sudo apt install -y qemu-guest-agent xrdp openssh-server
   sudo systemctl enable --now qemu-guest-agent
   sudo systemctl enable --now xrdp
   sudo systemctl enable --now ssh
   ```
   Le serveur SSH est necessaire pour la sauvegarde/restauration du home.
   Puis dans Proxmox → VM 100 → Options → QEMU Guest Agent → Activer

2. **VM 100 convertie en template** :
   - Éteindre la VM 100
   - Clic droit → Convertir en modèle

## Déploiement (5 minutes)

### Étape 1 — Copier les fichiers sur Proxmox

Depuis ta machine locale, envoie le dossier sur Proxmox :

```bash
scp -r vdi-orchestrator/ root@192.168.80.10:/root/
```

Ou si tu travailles directement sur le shell Proxmox, copie les fichiers
dans `/root/vdi-orchestrator/`.

### Étape 2 — Configurer le mot de passe Proxmox

```bash
cd /root/vdi-orchestrator
cp .env.example .env
nano .env
# Mettre ton vrai mot de passe root Proxmox
```

### Étape 3 — Remplacer ton docker-compose existant

**IMPORTANT** : Sauvegarde d'abord ton ancien fichier :

```bash
# Aller dans ton répertoire Guacamole actuel
cd /root/guacamole  # ou là où est ton docker-compose.yml actuel

# Sauvegarder
cp docker-compose.yml docker-compose.yml.backup

# Arrêter le stack actuel
docker compose down

# Copier le nouveau docker-compose et le dossier app
cp /root/vdi-orchestrator/docker-compose.yml .
cp -r /root/vdi-orchestrator/app ./app
cp /root/vdi-orchestrator/.env .
```

### Étape 4 — Lancer le stack

```bash
docker compose up -d --build
```

La première exécution prend ~1-2 min (build de l'image Python).

### Étape 5 — Vérifier

```bash
# Vérifier que tous les containers tournent
docker compose ps

# Vérifier les logs du middleware
docker logs vdi-orchestrator

# Tester le health check
curl http://localhost:8000/api/health
```

Réponse attendue :
```json
{
  "status": "ok",
  "proxmox": true,
  "guacamole_db": true,
  "active_clones": 0,
  "templates": 1
}
```

## Utilisation

### Portail Web (pour les utilisateurs)

Ouvrir : **http://192.168.80.10:8000**

- Cliquer sur un desktop → le clone se cree automatiquement
- Si un backup existe (session precedente), le `/home/etudiant` est restaure automatiquement
- Une fois pret → bouton "Connecter" ouvre Guacamole
- Bouton "Detruire" → sauvegarde le home puis supprime le clone
- Shift + clic sur "Detruire" → supprime sans sauvegarde

### Sauvegarde du home utilisateur

Le systeme sauvegarde automatiquement `/home/etudiant` avant chaque destruction de VM. Au prochain lancement du meme template par le meme utilisateur, les fichiers sont restaures.

**Comportement par type de destruction :**

| Raison | Backup |
|--------|--------|
| Manuelle (bouton "Detruire") | Oui (desactivable via Shift+clic ou `backup: false` dans l'API) |
| Auto-deconnexion (session Guacamole terminee) | Oui |
| Timeout (duree de vie max atteinte) | Oui |
| Inutilise (jamais connecte) | Non |
| Erreur (provisioning echoue) | Non |

**Stockage :** Les backups sont stockes dans le volume Docker `vdi-backups` sous `/srv/backups/{username}/template_{id}.tar.gz`.

**Limite de taille :** Par defaut 500 Mo par backup. Configurable via `BACKUP_MAX_SIZE_MB`.

### API REST (pour l'automatisation)

```bash
# Lister les templates
curl http://192.168.80.10:8000/api/templates

# Demander un clone
curl -X POST http://192.168.80.10:8000/api/clone/request \
  -H "Content-Type: application/json" \
  -d '{"template_id": 1}'

# Lister les clones actifs
curl http://192.168.80.10:8000/api/clones

# Detruire un clone (avec backup par defaut)
curl -X POST http://192.168.80.10:8000/api/clone/501/destroy

# Detruire un clone sans backup
curl -X POST http://192.168.80.10:8000/api/clone/501/destroy \
  -H "Content-Type: application/json" \
  -d '{"backup": false}'

# Detruire tous les clones
curl -X POST http://192.168.80.10:8000/api/clones/destroy-all

# Lister les backups (admin : tous, user : les siens)
curl http://192.168.80.10:8000/api/backups

# Info sur un backup specifique
curl http://192.168.80.10:8000/api/backups/tidiane/1

# Supprimer un backup
curl -X DELETE http://192.168.80.10:8000/api/backups/tidiane/1

# Ajouter un template (ex: Ubuntu Server)
curl -X POST http://192.168.80.10:8000/api/templates \
  -H "Content-Type: application/json" \
  -d '{
    "template_vmid": 101,
    "group_name": "servers",
    "display_name": "Serveur Ubuntu",
    "protocol": "rdp",
    "port": 3389,
    "cores": 2,
    "memory": 2048
  }'
```

## Ajouter un nouveau type de desktop

1. Créer et configurer une VM dans Proxmox
2. Installer qemu-guest-agent + xrdp + tout ce qu'il faut
3. Convertir en template
4. Ajouter via l'API :
   ```bash
   curl -X POST http://192.168.80.10:8000/api/templates \
     -H "Content-Type: application/json" \
     -d '{
       "template_vmid": 102,
       "group_name": "design",
       "display_name": "Desktop Design (GIMP + Inkscape)",
       "protocol": "rdp",
       "cores": 4,
       "memory": 4096
     }'
   ```

## Troubleshooting

| Probleme | Solution |
|----------|----------|
| `proxmox: false` dans /api/health | Verifier PROXMOX_PASSWORD dans .env |
| `guacamole_db: false` | Verifier que guac-db est healthy : `docker compose ps` |
| Clone cree mais pas d'IP | qemu-guest-agent pas installe/active dans le template |
| Connexion Guacamole echoue | xrdp pas installe dans le template |
| Erreur "No free VMID" | Trop de clones actifs, detruire les anciens |
| Backup echoue | Verifier que `openssh-server` est installe dans le template et que le compte `etudiant` peut se connecter en SSH |
| Restore echoue | Les logs (`docker logs vdi-orchestrator`) montrent le detail de l'erreur SSH/SFTP |

## Variables d'environnement (backup)

| Variable | Defaut | Description |
|----------|--------|-------------|
| `BACKUP_ENABLED` | `true` | Active/desactive le systeme de backup |
| `BACKUP_DIR` | `/srv/backups` | Repertoire de stockage des backups |
| `BACKUP_MAX_SIZE_MB` | `500` | Taille max du home avant backup (Mo) |
| `BACKUP_VM_USER` | `etudiant` | Compte Linux utilise pour SSH dans les VMs |

## Consommation de ressources

- **vdi-orchestrator** : ~30 Mo RAM, CPU négligeable
- **Pas de nouveau service lourd** — réutilise le PostgreSQL de Guacamole
- Compatible avec une VM Proxmox de 6 Go RAM
