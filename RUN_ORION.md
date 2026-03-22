# ORION Dev Runbook

This document explains how to run the ORION CI/CD assistant locally (backend + frontend) and defines the key terminology used in the project, including the new multimodal analysis system.

## 1. Backend (FastAPI) – how to run

**Backend directory:** `backend/`

### 1.1. Activate the virtual environment (Windows, PowerShell)

From the repo root:

```powershell
cd backend
..\.venv\Scripts\Activate.ps1
```

> If the `.venv` folder does not exist, create one and install dependencies first:
>
> ```powershell
> cd backend
> python -m venv ..\.venv
> ..\.venv\Scripts\Activate.ps1
> pip install -r requirements.txt
> ```

### 1.2. Start the backend server

From the `backend` directory **with the venv activated**:

```powershell
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

- API base URL in dev: **http://127.0.0.1:8001**
- Main API routes (excerpt):
  - Core DevOps API: `/submit-code`, `/submit-github`, `/pipeline-status/{id}`, `/trigger-deployment`, `/health`
  - Auth: `/api/v1/auth/github`, `/api/v1/auth/callback`, `/api/v1/auth/status`, `/api/v1/auth/me`, `/api/v1/auth/logout`
  - Legacy multimodal agents (pipeline-focused): `/api/v1/multimodal/analyze`, `/api/v1/multimodal/triage`
  - **New dedicated multimodal analyzers:**
    - Git logs: `POST /api/v1/multimodal/git-logs`
    - Payment: `POST /api/v1/multimodal/payment`

### 1.3. Required environment variables

Defined in [backend/core/config.py](backend/core/config.py) and loaded from `.env` in the repo root. Important ones for local dev:

- `APP_PORT` – default `8001`
- `SESSION_SECRET_KEY` – session/HMAC secret
- `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` – GitHub OAuth app credentials
- `FRONTEND_URL` – normally `http://localhost:5173`
- `ANTHROPIC_API_KEY` – Claude API key for multimodal analysis
- `ANTHROPIC_MODEL` – Anthropic model ID (default `claude-3-7-sonnet-latest`)

## 2. Frontend (Vite + React) – how to run

**Frontend directory:** `frontend/`

### 2.1. Install dependencies (first time only)

From the repo root:

```powershell
cd frontend
npm install
```

### 2.2. Start the dev server

```powershell
npm run dev -- --host 0.0.0.0 --port 5173
```

- Frontend URL in dev: **http://localhost:5173**
- The dashboard expects the backend at `http://127.0.0.1:8001` by default.

## 3. Key terminology

### 3.1. Backend

- **Backend**: The FastAPI service in the `backend/` folder.
- **Agents**: Python classes under `backend/agents/` that encapsulate specific responsibilities (code analysis, security, pipeline, deployment, monitoring, etc.).
- **Multimodal agents (legacy)**: Existing agents in `backend/agents/multimodal/` that use a generic multimodal envelope and the LLM client (`LLMClient`).
- **New dedicated multimodal agents (Claude API)**:
  - `GitLogAgent` – analyzes git/server logs, build output, and screenshots.
  - `PaymentAgent` – analyzes payment CSVs, webhook payloads, dashboards, and PDFs.
  - Both live under `backend/app/agents/multimodal/` and call Anthropic Claude directly with full multimodal support.

### 3.2. Frontend

- **Frontend**: Vite + React single-page dashboard in `frontend/`.
- **Pipeline view**: Shows pipeline ID, current stage, status badges, stage timeline, logs, and artifacts.
- **Auth banner**: Indicates whether the user is authenticated with GitHub and whether a token is available.
- **Multimodal modals**:
  - **Git Log Analyzer modal**:
    - Triggered from the header button “Git Log Analyzer”.
    - Lets you drop `.log`, `.txt`, `.zip` (GitHub Actions logs), `.png`, `.jpg`, `.csv` files or paste log text.
    - Calls `POST /api/v1/multimodal/git-logs` and renders:
      - Overall severity and issue count
      - Issue cards (category, description, root cause, fix commands)
      - Server timeout analysis and build error analysis when present
      - Immediate actions, plus JSON export & copyable fix commands
  - **Payment Analyzer modal**:
    - Triggered from the header button “Payment Analyzer”.
    - Accepts `.csv`, `.png`, `.jpg`, `.jpeg`, `.pdf`, `.json` and text (transactions, webhook payloads, error output).
    - Calls `POST /api/v1/multimodal/payment` and renders:
      - Overall severity
      - Success rate percentage
      - Reconciliation status badge (balanced / discrepancy / unable)
      - Failed transaction cards, error patterns, fraud indicators, immediate actions
      - JSON export of the full analysis

### 3.3. Multimodal artifacts

Inside the new Anthropic-based agents, every uploaded asset is normalized to an **artifact**:

```python
{
    "type": "text" | "image" | "csv" | "log" | "zip" | "pdf",
    "content": bytes | str,   # raw file bytes or text
    "filename": str,
    "mime_type": str,
}
```

- **type=image**: Sent to Claude as base64-encoded `image` blocks.
- **type=pdf**: Sent as a base64-encoded `document` block.
- **type=zip**: The ZIP is opened server-side and any `.txt`/`.log` files inside are added as separate text blocks.
- **type=text/csv/log**: Sent as `text` blocks, prefixed with the filename and type.

### 3.4. Authentication

- ORION uses GitHub OAuth for login:
  - Start at `/api/v1/auth/github` (linked from the dashboard).
  - Callback at `/api/v1/auth/github/callback` stores session + GitHub token.
- Many operations, including the new multimodal endpoints, require a valid authenticated session and will return `401` if the user is not logged in.

## 4. Quick start summary

1. **Backend**
   - `cd backend`
   - `..\.venv\Scripts\Activate.ps1`
   - `python -m uvicorn main:app --reload --host 127.0.0.1 --port 8001`
2. **Frontend**
   - `cd frontend`
   - `npm install` (first time)
   - `npm run dev -- --host 0.0.0.0 --port 5173`
3. Open **http://localhost:5173** in your browser.
4. Login with GitHub from the top-right of the dashboard.
5. Use the **Git Log Analyzer** and **Payment Analyzer** buttons to open the new multimodal analysis modals and run Claude-powered analyses against logs and payment data.
