# Deploying Duo on Render (+ Aiven PostgreSQL)

One Render **web service** runs a Docker image that serves both the website and the API from the
same address. The database is your **Aiven** PostgreSQL.

```
Browser ──HTTPS / WSS──▶ Render (Docker: website + FastAPI)  ──SSL──▶  Aiven PostgreSQL
```

## 0. Before you start

- Aiven service status is **Running** (the hostname only exists once it is running).
- **Rotate the Aiven password** if it was ever shared (chat, screenshots): Aiven console → your
  service → *Users* → reset `avnadmin` password, then copy the new **Service URI**.
- Pick the same region for Aiven and Render (e.g. both in Singapore / Mumbai) for fast messages.

## 1. Prepare the database (from your computer, once)

Put the Aiven Service URI in `backend/.env.production` (git-ignored, never commit it):

```
DATABASE_URL=postgres://avnadmin:<password>@<host>:<port>/defaultdb?sslmode=require
```

Then, in `backend/` (Git Bash):

```bash
export DATABASE_URL="$(grep ^DATABASE_URL= .env.production | cut -d= -f2-)"
.venv/Scripts/python -m alembic upgrade head        # create the tables on Aiven
.venv/Scripts/python -m app.cli create-user --username shizuka --display-name Shizuka
.venv/Scripts/python -m app.cli create-user --username doremon --display-name Doremon
.venv/Scripts/python -m app.cli list-users
```

(PowerShell: `$env:DATABASE_URL = "postgres://..."` instead of `export`.)
The container also runs `alembic upgrade head` on every start, so later schema changes apply automatically.

## 2. Put the code on GitHub

Render deploys from a Git repository. In the project root:

```bash
git init
git add .
git status          # check: no .env, .env.production, .venv, node_modules in the list
git commit -m "Duo chat"
git branch -M main
git remote add origin https://github.com/<you>/duo-chat.git   # create an empty PRIVATE repo first
git push -u origin main
```

`.gitignore` already excludes `.env`, `.env.*` (except `.env.example`), `.venv/`, `node_modules/`.

## 3. Create the service on Render

**Option A — Blueprint (uses `render.yaml`)**
1. Render dashboard → **New** → **Blueprint** → connect the GitHub repo.
2. Render reads `render.yaml` and asks for the secret values (step 4).

**Option B — manually**
1. **New** → **Web Service** → pick the repo.
2. Language/Runtime: **Docker** (it finds the `Dockerfile` in the root).
3. Name: e.g. `duo-chat` → your address becomes `https://duo-chat.onrender.com`.
4. Region: same as Aiven. Instance type: Free (sleeps when idle) or Starter (always on).

## 4. Environment variables (Render → service → Environment)

| Key | Value |
| --- | --- |
| `DATABASE_URL` | the Aiven **Service URI** exactly as shown (`postgres://…?sslmode=require`) |
| `SECRET_KEY` | long random string (Blueprint generates it; or `python -c "import secrets; print(secrets.token_urlsafe(48))"`) |
| `ALLOWED_ORIGINS` | `https://duo-chat.onrender.com` (your real address, with `https://`, no trailing `/`) |
| `ALLOWED_HOSTS` | `duo-chat.onrender.com` (no `https://`) |
| `LOGIN_RATE_LIMIT_ENABLED` | `true` |
| `MIN_PASSWORD_LENGTH` | `4` |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `4` / `4` (Aiven free allows 15 connections) |

Already set inside the image: `ENVIRONMENT=production`, `COOKIE_SECURE=true`, `STATIC_DIR=/app/static`.

If you add a custom domain later, add it to both `ALLOWED_ORIGINS` (comma-separated) and `ALLOWED_HOSTS`.

## 5. Deploy and check

1. Click **Deploy** (or push to `main` — auto-deploy is on).
2. Logs should end with `Uvicorn running on http://0.0.0.0:10000`.
3. Open `https://duo-chat.onrender.com` → sign in as `shizuka` on one device and `doremon` on another.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `400 Invalid host header` | `ALLOWED_HOSTS` doesn't match the address in the browser |
| `403 Origin not allowed` on sign-in | `ALLOWED_ORIGINS` doesn't match exactly (`https://`, no trailing slash) |
| Signed in, but chat stays "Connecting…" | same as above (the WebSocket checks the origin too) |
| `failed to resolve host … aivencloud.com` | Aiven service not running, or wrong URI |
| `too many connections` | lower `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`; Aiven free allows 15 |
| First visit takes ~1 minute | free instance waking from sleep; use Starter to avoid |
| `429 Too many attempts` | login rate limit (5 wrong passwords / 15 min per account); wait |

## Admin commands against production

Run from `backend/` on your computer with `DATABASE_URL` set to the Aiven URI (as in step 1):

```bash
.venv/Scripts/python -m app.cli set-password    --username doremon
.venv/Scripts/python -m app.cli revoke-sessions --username doremon
.venv/Scripts/python -m app.cli list-users
```
