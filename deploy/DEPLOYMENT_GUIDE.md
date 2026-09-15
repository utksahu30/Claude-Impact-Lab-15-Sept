# CivicTrace Bhopal — Production Hosting & Deployment Guide

This guide provides step-by-step instructions to host and deploy the **CivicTrace Bhopal (PS-5)** application across major cloud platforms and self-hosted environments.

---

## 📦 Directory Overview (`deploy/`)

The `deploy/` directory is a self-contained, standalone production package:

```
deploy/
├── Dockerfile              # Multi-stage production container image
├── docker-compose.yml      # Local / VPS orchestration with healthchecks & volumes
├── requirements.txt        # Production Python dependencies
├── start.sh                # Auto-seeding entrypoint script
├── Procfile                # PaaS entrypoint (Railway / Heroku / Dokku)
├── render.yaml             # 1-Click Render deployment blueprint
├── .env.example            # Production environment template
├── app/                    # Complete application code (routers, models, logic, templates, CSS)
└── data/                   # Reference datasets (taxonomy.json, gazetteer.json, seed complaints)
```

---

## 🚀 Option 1: Render (Recommended — 1-Click PaaS)

Render provides free SSL certificates, automated Git deployments, and custom domain support.

### Method A: Using Render Blueprint (Fastest)
1. Fork or push this repository to GitHub.
2. Log in to [Render Dashboard](https://dashboard.render.com).
3. Click **New +** &rarr; **Blueprint**.
4. Connect your GitHub repository. Render will automatically detect `deploy/render.yaml`.
5. Enter your `DASHSCOPE_API_KEY` when prompted.
6. Click **Apply**. Your app will be live at `https://civictrace-bhopal.onrender.com` in ~3 minutes.

### Method B: Manual Web Service
1. Click **New +** &rarr; **Web Service**.
2. Connect your GitHub repo.
3. Select **Docker** as the runtime.
4. Set:
   - **Root Directory**: `deploy`
   - **Dockerfile Path**: `Dockerfile`
5. Under **Environment Variables**, add:
   - `DASHSCOPE_API_KEY`: `your-aliyun-dashscope-key`
   - `ALLOW_EXTERNAL_AI`: `true`
6. Click **Deploy Web Service**.

---

## ☁️ Option 2: Google Cloud Run (Serverless Container)

Google Cloud Run runs containers serverlessly, auto-scaling to zero when idle.

### Prerequisites
- Google Cloud SDK (`gcloud`) installed.
- Docker installed locally (or use Google Cloud Build).

### Steps
1. Navigate to the deployment folder:
   ```bash
   cd deploy
   ```
2. Build and submit container image via Cloud Build:
   ```bash
   gcloud builds submit --tag gcr.io/[YOUR_PROJECT_ID]/civictrace:latest .
   ```
3. Deploy to Cloud Run:
   ```bash
   gcloud run deploy civictrace \
     --image gcr.io/[YOUR_PROJECT_ID]/civictrace:latest \
     --platform managed \
     --region asia-south1 \
     --allow-unauthenticated \
     --port 8000 \
     --set-env-vars DASHSCOPE_API_KEY="[YOUR_API_KEY]",ALLOW_EXTERNAL_AI="true"
   ```
4. Cloud Run will output your live URL: `https://civictrace-xxxx-el.a.run.app`.

---

## 🚂 Option 3: Railway or Fly.io

### Railway
1. Install Railway CLI: `npm i -g @railway/cli` or use the [Railway Web Console](https://railway.app).
2. From the repository root:
   ```bash
   cd deploy
   railway init
   railway up
   ```
3. In Railway project settings, add variable `DASHSCOPE_API_KEY`.
4. Click **Generate Domain** under Networking.

### Fly.io
1. Install Flyctl: `curl -L https://fly.io/install.sh | sh`.
2. In `deploy/`:
   ```bash
   fly launch --dockerfile Dockerfile
   fly secrets set DASHSCOPE_API_KEY="your_api_key"
   fly deploy
   ```

---

## 🖥️ Option 4: Self-Hosted Docker VPS (Ubuntu / Debian / EC2 / Hetzner)

For high-security, internal intranet, or private municipal zone office servers.

### Steps
1. Clone the repository on your Linux server:
   ```bash
   git clone https://github.com/utksahu30/Claude-Impact-Lab-15-Sept.git
   cd Claude-Impact-Lab-15-Sept/deploy
   ```
2. Copy and configure `.env`:
   ```bash
   cp .env.example .env
   nano .env
   # Set DASHSCOPE_API_KEY and DEMO_TOKEN
   ```
3. Start the application with Docker Compose:
   ```bash
   docker compose up -d --build
   ```
4. Check running status and health:
   ```bash
   docker compose ps
   docker compose logs -f
   ```
5. *(Optional)* Put **Caddy** in front for automated Let's Encrypt HTTPS:
   ```caddyfile
   civictrace.yourcity.gov.in {
       reverse_proxy 127.0.0.1:8000
   }
   ```

---

## 🔐 Environment Variables Reference

| Variable | Default | Description |
| :--- | :--- | :--- |
| `DASHSCOPE_API_KEY` | *(Required)* | Alibaba Cloud DashScope API key for Qwen 3.8 Max. |
| `DASHSCOPE_BASE_URL` | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | OpenAI-compatible endpoint. |
| `QWEN_MODEL` | `qwen3.8-max` | Model identifier for deep civic reasoning. |
| `ALLOW_EXTERNAL_AI` | `true` | Set `false` to test 100% deterministic offline fallback. |
| `DATABASE_URL` | `sqlite:///bhopal_triage.db` | SQLite database URI with WAL journal mode. |
| `DEMO_TOKEN` | *(auto-generated)* | Token for header `X-Demo-Token`. |
| `PORT` | `8000` | Port bound by Uvicorn. |

---

## 🛠️ Verification & Smoke Testing

Once hosted, test all primary endpoints:
1. **Queue View**: `GET /tickets` (Verify 200 OK and Neobrutalist UI)
2. **Batch Ingestion**: `GET /upload` & `POST /upload` with CSV
3. **Executive Digest**: `GET /digest` & `GET /digest/export.csv`
4. **Benchmark**: `GET /eval` & `POST /eval/run`
5. **Offline Mode**: Toggle `ALLOW_EXTERNAL_AI=false` to verify the deterministic fallback sentinel.
