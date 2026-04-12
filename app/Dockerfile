FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Le dossier build context est déjà app/ (voir docker-compose.yml).
# On recopie l'ensemble comme package Python `app/` pour permettre les imports relatifs.
COPY . /srv/app/

# Les templates Jinja2 sont chargés via `Jinja2Templates(directory="templates")`
# → on exécute depuis /srv/app pour que ce chemin soit relatif au package.
WORKDIR /srv/app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/srv"]
