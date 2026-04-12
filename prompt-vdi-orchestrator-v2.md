# Prompt Claude Code — VDI Orchestrator v2

## Contexte

Tu travailles sur `vdi-orchestrator`, un middleware FastAPI (Python) qui orchestre le provisioning dynamique de desktops virtuels (VDI) en combinant l'API REST Proxmox VE (linked clones) et Apache Guacamole (accès RDP/SSH/VNC via navigateur).

Le projet tourne en Docker aux côtés de Guacamole (guacd, guac-db PostgreSQL 15, guacamole) sur un hôte Proxmox 8.4 à `192.168.80.10`. Le docker-compose existant contient déjà les 4 services (guacd, guac-db, guacamole, vdi-orchestrator).

Le code actuel est un mono-fichier `app/main.py` (~1000 lignes) fonctionnel mais non structuré. Il faut le refactorer en architecture propre et ajouter les fonctionnalités manquantes.

## Stack technique

- **Python 3.12** + **FastAPI** + **Jinja2** (templates HTML server-side)
- **PostgreSQL 15** (base Guacamole existante `guacamole_db`, on ajoute nos tables VDI dans la même DB)
- **httpx** (client async pour l'API Proxmox)
- **psycopg2** (accès direct à la DB Guacamole/VDI)
- **Docker** (un seul conteneur pour l'orchestrator, Dockerfile existant)
- **PAS de framework JS frontend** — HTML + CSS + vanilla JS, rendu server-side avec Jinja2
- UI dark theme, police DM Sans, design épuré et professionnel

## Architecture cible

```
app/
├── main.py                 # FastAPI app factory, lifespan, middlewares
├── config.py               # Settings depuis les variables d'environnement
├── database.py             # Connexion PostgreSQL, init des tables VDI
├── models.py               # Pydantic schemas + dataclasses métier
├── routers/
│   ├── auth.py             # Routes login/logout, gestion session
│   ├── portal.py           # Routes pages utilisateur (HTML)
│   ├── admin.py            # Routes pages admin (HTML)
│   └── api.py              # Routes API REST JSON (clones, templates, health)
├── services/
│   ├── proxmox.py          # Client API Proxmox (auth ticket, clone, start, stop, destroy, agent)
│   ├── guacamole.py        # Lecture/écriture dans les tables Guacamole (users, groups, connections, permissions, connection_history)
│   ├── clone_manager.py    # Logique métier du cycle de vie des clones (request, provision, destroy)
│   └── session_monitor.py  # Tâche async de monitoring : polling des sessions Guacamole + auto-destroy + cleanup orphelins
├── templates/
│   ├── base.html           # Layout de base (header, nav, footer, CSS intégré)
│   ├── login.html          # Page de connexion
│   ├── portal.html         # Portail utilisateur — desktops disponibles + sessions actives
│   └── admin.html          # Dashboard admin — templates, clones, users, logs, stats
└── static/                 # (optionnel, le CSS peut être dans base.html)
```

## Tables VDI à créer dans la DB (en plus des tables Guacamole existantes)

```sql
-- Templates VDI disponibles
CREATE TABLE IF NOT EXISTS vdi_template (
    id SERIAL PRIMARY KEY,
    template_vmid INTEGER NOT NULL,         -- VMID du template Proxmox
    group_name VARCHAR(255) NOT NULL UNIQUE, -- Identifiant unique du template
    display_name VARCHAR(255) NOT NULL,      -- Nom affiché dans le portail
    protocol VARCHAR(10) NOT NULL DEFAULT 'rdp',  -- rdp, ssh, vnc
    port INTEGER NOT NULL DEFAULT 3389,
    default_username VARCHAR(255),           -- Username par défaut pour la connexion
    default_password VARCHAR(255),           -- Password par défaut pour la connexion
    cores INTEGER NOT NULL DEFAULT 2,
    memory INTEGER NOT NULL DEFAULT 2048,    -- Mo
    max_clones INTEGER NOT NULL DEFAULT 5,   -- Max clones simultanés pour ce template
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Association template <-> groupes Guacamole autorisés
CREATE TABLE IF NOT EXISTS vdi_template_group (
    id SERIAL PRIMARY KEY,
    template_id INTEGER REFERENCES vdi_template(id) ON DELETE CASCADE,
    guacamole_group_name VARCHAR(255) NOT NULL,  -- Nom du user_group Guacamole
    UNIQUE(template_id, guacamole_group_name)
);

-- Clones actifs
CREATE TABLE IF NOT EXISTS vdi_clone (
    id SERIAL PRIMARY KEY,
    vmid INTEGER NOT NULL UNIQUE,
    template_id INTEGER REFERENCES vdi_template(id),
    clone_name VARCHAR(255) NOT NULL,
    username VARCHAR(255) NOT NULL,          -- Username Guacamole du demandeur
    ip_address VARCHAR(45),
    guac_connection_id INTEGER,              -- ID de la connexion créée dans Guacamole
    status VARCHAR(50) NOT NULL DEFAULT 'creating',  -- creating, starting, waiting_ip, ready, destroying, error
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    connected_at TIMESTAMP,                  -- Première connexion effective
    last_activity TIMESTAMP                  -- Dernière activité détectée
);

-- Historique des sessions VDI (pour stats et mémoire)
CREATE TABLE IF NOT EXISTS vdi_session_log (
    id SERIAL PRIMARY KEY,
    vmid INTEGER NOT NULL,
    template_id INTEGER,
    template_name VARCHAR(255),
    username VARCHAR(255) NOT NULL,
    ip_address VARCHAR(45),
    created_at TIMESTAMP NOT NULL,
    destroyed_at TIMESTAMP,
    duration_seconds INTEGER,
    destroy_reason VARCHAR(50)              -- manual, auto_disconnect, timeout, cleanup, error
);
```

## Fonctionnalités à implémenter

### 1. Authentification (routers/auth.py + services/guacamole.py)

- Page de login (`/login`) avec username/password
- **Authentifier contre les users Guacamole existants** : lire `guacamole_entity` + `guacamole_user`, vérifier le hash du mot de passe (Guacamole utilise SHA-256 salté : le hash est `SHA256(password + password_salt)`, les deux champs sont en bytea dans `guacamole_user`)
- Session via cookie sécurisé (SessionMiddleware de Starlette)
- Rôle **admin** : le user `guacadmin` est automatiquement admin. On peut aussi marquer d'autres users comme admin via une table ou un flag
- Rôle **user** : tous les autres users Guacamole
- Middleware de protection : toutes les routes sauf `/login` et `/api/health` nécessitent une session active
- Redirect vers `/login` si non authentifié
- Route `/logout` qui détruit la session

### 2. Portail utilisateur (routers/portal.py)

- Route `GET /` → page portail (template `portal.html`)
- Afficher uniquement les templates VDI auxquels le user a accès (via ses groupes Guacamole → `vdi_template_group`)
- Si le user n'appartient à aucun groupe configuré, afficher un message "Aucun desktop disponible, contactez l'administrateur"
- Pour chaque template : carte avec nom, description, protocole, état (disponible / max atteint)
- **Si le user a déjà un clone actif sur ce template** → la carte affiche "Connecter" (lien vers Guacamole) et "Détruire" au lieu de "Lancer"
- **Si le user n'a pas de clone** → bouton "Lancer" qui déclenche le provisioning
- **Un seul clone par user par template** — vérifié côté serveur avec un verrou (asyncio.Lock par user+template) pour empêcher les race conditions même en cas de double-clic
- Section "Mes sessions actives" en bas avec la liste des clones du user
- Progress bar / étapes visuelles pendant le provisioning (cloning → starting → waiting IP → creating connection → ready) via polling AJAX sur `/api/clone/{vmid}/status`
- Bouton "Détruire" sur chaque session active

### 3. Administration (routers/admin.py)

- Route `GET /admin` → dashboard admin (template `admin.html`), accessible uniquement aux admins
- **Gestion des templates** :
  - Liste des templates configurés avec état (enabled/disabled)
  - Bouton "Ajouter un template" : formulaire avec VMID, nom, protocole, port, credentials par défaut, cores, RAM, max clones
  - **Auto-discovery Proxmox** : bouton "Scanner Proxmox" qui appelle `GET /api2/json/nodes/{node}/qemu` et liste toutes les VMs qui sont des templates (status = template). L'admin coche lesquelles activer et remplit les paramètres
  - Éditer / Supprimer un template
  - Assigner des groupes Guacamole à chaque template (multiselect des groupes existants dans Guacamole)
- **Gestion des clones actifs** :
  - Liste de tous les clones actifs (tous users)
  - Pour chaque clone : VMID, user, template, IP, statut, durée, bouton "Forcer la destruction"
  - Bouton "Détruire tous les clones"
- **Historique / Logs** :
  - Table des sessions passées (depuis `vdi_session_log`)
  - Filtres par user, template, date
  - Stats : nombre total de sessions, durée moyenne, template le plus utilisé
- **Vue des users/groupes Guacamole** (lecture seule) :
  - Liste des users Guacamole avec leurs groupes
  - Permet à l'admin de voir qui a accès à quoi sans aller dans l'admin Guacamole

### 4. Destruction automatique à la déconnexion (services/session_monitor.py)

- Tâche asyncio qui tourne en background, boucle toutes les 15 secondes
- Pour chaque clone actif en statut "ready" :
  1. Vérifier dans `guacamole_connection_history` si la connexion a un `end_date` non null (= session terminée)
  2. Si oui → déclencher la destruction du clone (stop VM, delete connexion Guacamole, delete VM Proxmox, log dans `vdi_session_log`)
  3. Si non (session encore active) → mettre à jour `last_activity`
- **Timeout de sécurité** : si un clone a `status = ready` mais aucune session Guacamole n'a jamais été ouverte dessus après 5 minutes → détruire (le user a quitté avant de se connecter)
- **Timeout d'inactivité** : si un clone tourne depuis plus de 4 heures (configurable) → détruire avec raison "timeout"
- **Cleanup orphelins** : détecter les VMs dans Proxmox qui commencent par le prefix `vdi-` mais ne sont pas dans la table `vdi_clone` → détruire
- Logger chaque action dans `vdi_session_log` avec la raison de destruction

### 5. API REST (routers/api.py)

Conserver les endpoints existants et ajouter :
- `GET /api/health` — health check (proxmox, guac_db, stats)
- `GET /api/templates` — lister les templates
- `POST /api/templates` — ajouter un template (admin only)
- `PUT /api/templates/{id}` — modifier un template (admin only)
- `DELETE /api/templates/{id}` — supprimer un template (admin only)
- `GET /api/proxmox/templates` — auto-discovery des templates Proxmox (admin only)
- `POST /api/clone/request` — demander un clone (avec vérification auth + groupe + unicité)
- `GET /api/clone/{vmid}/status` — statut d'un clone (pour le polling frontend)
- `POST /api/clone/{vmid}/destroy` — détruire un clone (le user peut détruire les siens, l'admin peut tout détruire)
- `POST /api/clones/destroy-all` — détruire tous les clones (admin only)
- `GET /api/clones` — lister tous les clones actifs (admin: tous, user: les siens)
- `GET /api/sessions/history` — historique des sessions (admin only)
- `GET /api/sessions/stats` — statistiques (admin only)
- Tous les endpoints qui modifient des données vérifient l'authentification et le rôle

### 6. Cycle de vie d'un clone (services/clone_manager.py)

Le pipeline de provisioning, extrait de main.py et structuré :
1. **Vérifier** : user authentifié, groupe autorisé, pas de clone existant, max clones pas atteint
2. **Réserver** : trouver un VMID libre (range 500-550), insérer dans `vdi_clone` avec status "creating" (le INSERT sert de verrou DB)
3. **Cloner** : `POST /nodes/{node}/qemu/{template}/clone` avec `full=0`
4. **Configurer** : `PUT /nodes/{node}/qemu/{vmid}/config` (cores, memory)
5. **Démarrer** : `POST /nodes/{node}/qemu/{vmid}/status/start`
6. **Attendre IP** : polling `GET /nodes/{node}/qemu/{vmid}/agent/network-get-interfaces`
7. **Créer connexion Guacamole** : INSERT dans `guacamole_connection` + `guacamole_connection_parameter` avec les credentials du template + permission uniquement pour le user demandeur
8. **Mettre à jour** : status "ready", guac_connection_id, ip_address dans `vdi_clone`
9. **En cas d'erreur** à n'importe quelle étape : cleanup (destroy VM si créée, delete connexion si créée, update status "error", log)

### 7. Intégration Guacamole (services/guacamole.py)

Ce service encapsule TOUS les accès à la DB Guacamole :
- `authenticate_user(username, password) -> bool` — vérifie le hash SHA-256 salté
- `get_user_groups(username) -> list[str]` — retourne les groupes d'un user
- `is_admin(username) -> bool` — vérifie si c'est guacadmin ou un admin configuré
- `list_users() -> list[dict]` — liste tous les users avec leurs groupes
- `list_groups() -> list[str]` — liste tous les groupes
- `create_connection(name, protocol, hostname, port, username, password) -> int` — crée une connexion
- `grant_connection_permission(connection_id, username)` — donne accès à un user spécifique uniquement
- `delete_connection(connection_id)` — supprime une connexion et ses permissions
- `get_active_sessions(connection_id) -> list` — vérifie dans `guacamole_connection_history` si une session est en cours
- `is_session_ended(connection_id) -> bool` — vérifie si toutes les sessions ont un `end_date`

## Contraintes techniques

- **Pas d'ORM** (pas de SQLAlchemy). Utiliser `psycopg2` directement avec des requêtes SQL. C'est plus simple et on contrôle exactement les requêtes sur les tables Guacamole
- **Un seul conteneur Docker** pour tout l'orchestrator
- **Pas de migration framework** — les tables VDI sont créées au démarrage si elles n'existent pas (IF NOT EXISTS)
- Le **docker-compose.yml** et le **Dockerfile** existants ne changent pas (sauf ajout éventuel de dépendances dans requirements.txt)
- Les **variables d'environnement** existantes ne changent pas, on peut en ajouter (timeouts, etc.)
- **Jinja2** pour le templating HTML, pas de framework JS
- Le CSS est intégré dans `base.html` (pas de fichier séparé pour simplifier le déploiement)
- **Toutes les erreurs** sont gérées proprement (try/except, logs, messages user-friendly)
- **Logging** structuré avec le module `logging` (INFO pour les actions normales, WARNING pour les anomalies, ERROR pour les échecs)

## Design UI

- Theme dark (fond `#0a0e1a`, surfaces `#111827`, bordures `#1e293b`)
- Police : DM Sans (Google Fonts)
- Couleurs d'accent : bleu `#3b82f6` (primaire), vert `#22c55e` (succès), rouge `#ef4444` (danger), orange `#f59e0b` (warning)
- Cards avec hover glow, badges de statut, progress steps visuels
- Responsive (fonctionne sur mobile)
- Page admin avec layout sidebar ou tabs pour naviguer entre templates/clones/logs
- Pas d'emojis comme icônes — utiliser des caractères Unicode simples ou des SVG inline minimalistes

## Ce qu'il ne faut PAS faire

- Ne PAS toucher aux tables Guacamole existantes (pas d'ALTER TABLE)
- Ne PAS créer un système d'auth séparé — utiliser les users Guacamole
- Ne PAS utiliser l'API REST de Guacamole (instable, tokens) — écrire directement dans la DB PostgreSQL
- Ne PAS utiliser localStorage dans le frontend
- Ne PAS créer de fichiers séparés CSS/JS — tout intégrer dans les templates Jinja2
- Ne PAS utiliser de framework JS (React, Vue, etc.)
- Ne PAS ajouter de dépendances lourdes au requirements.txt
