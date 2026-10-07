# AI-Powered CI/CD Pipeline — Complete GitHub Copilot Build Guide
### End-to-End Project Construction Prompts: Every Step, Every File, Every Detail

---

## HOW TO USE THIS DOCUMENT

Open VS Code. Open GitHub Copilot Chat (Ctrl+Shift+I). Paste each numbered prompt block **exactly as written** into the Copilot Chat panel. Work through them **in order** — each block builds on the last. Every prompt is self-contained and tells Copilot precisely what file to create, what dependencies to install, what schema to use, and what logic to implement.

---

## PROJECT OVERVIEW

**What you are building:** A fully autonomous, AI-agent-powered CI/CD pipeline system. When a developer pushes code to GitHub, a webhook triggers a backend server. That server runs a chain of AI agents — Code Analysis, Security, QA, Stress Testing, Approval, Deployment, and Monitoring — each powered by the Anthropic Claude API. The orchestrator coordinates every agent, gates the pipeline on failures, and auto-rolls back bad deployments. The entire system is built with FastAPI, Celery, Redis, PostgreSQL, Docker, and the Anthropic Python SDK.

**Tech Stack:**
- Backend: Python 3.11, FastAPI, Celery, SQLAlchemy (async), Alembic
- Database: PostgreSQL 15
- Queue/Cache: Redis 7
- AI: Anthropic Claude API (claude-sonnet-4-20250514)
- Container: Docker, Docker Compose
- Notifications: Slack Webhooks, GitHub Commit Status API
- Testing: pytest, locust
- Code Analysis: pylint, bandit, safety

---

## PART 1 — PROJECT SCAFFOLD AND ENVIRONMENT

### Prompt 1.1 — Initialize project structure

```
Create the following complete directory and file structure for a Python FastAPI project called "ai-cicd-pipeline". 
Create every folder and every file listed. Leave files empty for now except __init__.py files which should have a single docstring comment describing the module.

ai-cicd-pipeline/
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── alembic.ini
├── README.md
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── pipeline_run.py
│   │   └── pipeline_artifact.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── pipeline_run.py
│   │   └── webhook.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── webhook.py
│   │   │   └── pipeline.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py
│   │   ├── orchestrator.py
│   │   ├── code_analysis_agent.py
│   │   ├── security_agent.py
│   │   ├── qa_agent.py
│   │   ├── stress_test_agent.py
│   │   ├── approval_agent.py
│   │   ├── deployment_agent.py
│   │   └── monitoring_agent.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── github_service.py
│   │   ├── slack_service.py
│   │   └── git_service.py
│   ├── tasks/
│   │   ├── __init__.py
│   │   └── pipeline_tasks.py
│   └── utils/
│       ├── __init__.py
│       ├── logger.py
│       └── hmac_validator.py
├── alembic/
│   ├── env.py
│   └── versions/
│       └── .gitkeep
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_webhook.py
    ├── test_agents/
    │   ├── __init__.py
    │   ├── test_code_analysis.py
    │   ├── test_security.py
    │   └── test_qa.py
    └── fixtures/
        ├── sample_diff.txt
        └── sample_pytest_report.json
```
```

---

### Prompt 1.2 — Write requirements.txt

```
Write the complete requirements.txt file for the ai-cicd-pipeline project. Include every package with a pinned version. The file must include:

fastapi==0.111.0
uvicorn[standard]==0.29.0
pydantic==2.7.1
pydantic-settings==2.2.1
sqlalchemy[asyncio]==2.0.30
asyncpg==0.29.0
alembic==1.13.1
celery==5.4.0
redis==5.0.4
anthropic==0.26.0
gitpython==3.1.43
httpx==0.27.0
python-dotenv==1.0.1
pylint==3.2.0
bandit==1.7.8
safety==3.2.0
pytest-json-report==1.5.0
locust==2.28.0
docker==7.1.0
psutil==5.9.8
pytest==8.2.0
pytest-asyncio==0.23.7
pytest-mock==3.14.0
python-multipart==0.0.9

Write it as a plain text file, one package per line, no comments.
```

---

### Prompt 1.3 — Write .env.example

```
Write the complete .env.example file for ai-cicd-pipeline. Include every environment variable the app needs with placeholder values and inline comments explaining each one. Include these variables:

# Application
APP_ENV=development
APP_PORT=8000
SECRET_KEY=your-secret-key-here-min-32-chars

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/aicicd
SYNC_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/aicicd

# Redis
REDIS_URL=redis://localhost:6379/0

# Anthropic
ANTHROPIC_API_KEY=sk-ant-your-key-here
ANTHROPIC_MODEL=claude-sonnet-4-20250514

# GitHub
GITHUB_WEBHOOK_SECRET=your-webhook-secret
GITHUB_TOKEN=ghp_your-github-token
GITHUB_OWNER=your-github-username

# Slack
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzz

# Deployment
STAGING_URL=http://localhost:8080
CONTAINER_REGISTRY=your-registry.io
APP_NAME=my-app
DEPLOY_ENVIRONMENT=staging

# Pipeline Thresholds
MAX_SECURITY_SEVERITY=medium
STRESS_TEST_USERS=1000
STRESS_TEST_DURATION=60
STRESS_TEST_SPAWN_RATE=50
MONITORING_POLL_INTERVAL_SECONDS=30
MONITORING_WINDOW_MINUTES=5
HEALTH_CHECK_TIMEOUT_SECONDS=180
```

---

### Prompt 1.4 — Write docker-compose.yml

```
Write the complete docker-compose.yml for ai-cicd-pipeline. It must define these services:

1. postgres: image postgres:15-alpine, environment POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres POSTGRES_DB=aicicd, ports 5432:5432, volume postgres_data:/var/lib/postgresql/data, healthcheck using pg_isready

2. redis: image redis:7-alpine, ports 6379:6379, volume redis_data:/data, command redis-server --appendonly yes, healthcheck using redis-cli ping

3. app: build from Dockerfile, ports 8000:8000, env_file .env, depends_on postgres and redis with condition service_healthy, volumes ./:/app, command uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

4. worker: same build as app, env_file .env, depends_on postgres and redis, command celery -A app.tasks.pipeline_tasks.celery_app worker --loglevel=info --concurrency=4

5. flower: image mher/flower:2.0.0, ports 5555:5555, env_file .env, depends_on redis, command celery --broker=${REDIS_URL} flower

Define volumes postgres_data and redis_data at the bottom. Use version: "3.9".
```

---

### Prompt 1.5 — Write Dockerfile

```
Write the complete Dockerfile for ai-cicd-pipeline using Python 3.11-slim as base. It must:
1. Set WORKDIR /app
2. Install system dependencies: git, gcc, libpq-dev, curl using apt-get with --no-install-recommends and clean up apt cache after
3. Copy requirements.txt first (layer caching), then run pip install --no-cache-dir -r requirements.txt
4. Install bandit and safety as global CLI tools: pip install bandit safety pylint
5. Copy the entire project into /app
6. Set environment variable PYTHONUNBUFFERED=1 and PYTHONDONTWRITEBYTECODE=1
7. Expose port 8000
8. Set the default CMD to: uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## PART 2 — CONFIGURATION AND DATABASE LAYER

### Prompt 2.1 — Write app/config.py

```
Write app/config.py using pydantic-settings BaseSettings. Create a Settings class that reads all values from environment variables. Include every field that matches the .env.example file. Use proper Python types: str, int, bool. Add a @property called database_url_sync that returns SYNC_DATABASE_URL. Add a @property called is_production that returns True if APP_ENV == "production". At the bottom of the file, instantiate settings = Settings() so it can be imported directly. Use model_config = SettingsConfigDict(env_file=".env", case_sensitive=False).

Fields to include (with types and defaults):
- app_env: str = "development"
- app_port: int = 8000
- secret_key: str
- database_url: str
- sync_database_url: str
- redis_url: str = "redis://localhost:6379/0"
- anthropic_api_key: str
- anthropic_model: str = "claude-sonnet-4-20250514"
- github_webhook_secret: str
- github_token: str
- github_owner: str
- slack_webhook_url: str = ""
- staging_url: str = "http://localhost:8080"
- container_registry: str = ""
- app_name: str = "my-app"
- deploy_environment: str = "staging"
- max_security_severity: str = "medium"
- stress_test_users: int = 1000
- stress_test_duration: int = 60
- stress_test_spawn_rate: int = 50
- monitoring_poll_interval_seconds: int = 30
- monitoring_window_minutes: int = 5
- health_check_timeout_seconds: int = 180
```

---

### Prompt 2.2 — Write app/database.py

```
Write app/database.py for async SQLAlchemy with PostgreSQL. It must:

1. Import create_async_engine and AsyncSession from sqlalchemy.ext.asyncio
2. Import declarative_base from sqlalchemy.orm
3. Import settings from app.config
4. Create async_engine = create_async_engine(settings.database_url, echo=settings.app_env == "development", pool_size=10, max_overflow=20, pool_pre_ping=True)
5. Create AsyncSessionLocal = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False, autocommit=False, autoflush=False)
6. Create Base = declarative_base()
7. Write an async generator function get_db() that yields an AsyncSession, with a try/finally block that closes the session
8. Write an async function init_db() that calls async_engine.begin() and runs Base.metadata.create_all(bind=conn) — used for initial setup
9. Add a comment explaining that Alembic handles migrations in production but init_db is used for testing
```

---

### Prompt 2.3 — Write app/models/pipeline_run.py

```
Write app/models/pipeline_run.py. Create a SQLAlchemy ORM model class PipelineRun that maps to table "pipeline_runs". Include these columns exactly:

- id: UUID primary key, server_default=func.gen_random_uuid(), not nullable
- commit_id: String(40), not nullable, index=True (the full git SHA)
- short_commit_id: String(8), not nullable (first 8 chars, stored for convenience)
- branch: String(255), not nullable
- pusher: String(255), not nullable (GitHub username of who pushed)
- repo_full_name: String(255), not nullable (e.g. "owner/repo")
- clone_url: Text, not nullable
- status: String(50), not nullable, default="queued", index=True
  Valid statuses: queued, ingesting, analyzing_code, analyzing_security, running_qa, running_stress, awaiting_approval, deploying, deployed, monitoring, rolled_back, auto_rolled_back, blocked_code, blocked_security, blocked_tests, blocked_stress, rejected, failed
- has_warnings: Boolean, default=False, not nullable
- error_message: Text, nullable
- created_at: DateTime(timezone=True), server_default=func.now(), not nullable
- updated_at: DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), not nullable
- completed_at: DateTime(timezone=True), nullable

Add a __repr__ method returning f"<PipelineRun {self.id} commit={self.short_commit_id} status={self.status}>"

Import Base from app.database. Import all SQLAlchemy types needed.
```

---

### Prompt 2.4 — Write app/models/pipeline_artifact.py

```
Write app/models/pipeline_artifact.py. Create a SQLAlchemy ORM model PipelineArtifact that maps to table "pipeline_artifacts". Include:

- id: UUID primary key, server_default=func.gen_random_uuid()
- pipeline_run_id: UUID, ForeignKey("pipeline_runs.id", ondelete="CASCADE"), not nullable, index=True
- artifact_type: String(50), not nullable, index=True
  Valid types: diff, metadata, code_analysis, security_scan, qa_report, stress_report, approval, deployment_info, monitoring_alert, last_known_good_image
- content: JSON (use sqlalchemy JSON type), not nullable  (stores the full parsed result dict)
- raw_output: Text, nullable (stores raw CLI output before AI processing)
- agent_model: String(100), nullable (which AI model was used, e.g. claude-sonnet-4-20250514)
- tokens_used: Integer, nullable (track Anthropic API token usage)
- duration_seconds: Float, nullable (how long the agent took)
- created_at: DateTime(timezone=True), server_default=func.now(), not nullable

Add a relationship: pipeline_run = relationship("PipelineRun", back_populates="artifacts")
Also add to PipelineRun model: artifacts = relationship("PipelineArtifact", back_populates="pipeline_run", cascade="all, delete-orphan")

Add __repr__ returning f"<PipelineArtifact type={self.artifact_type} run={self.pipeline_run_id}>"
```

---

### Prompt 2.5 — Write Alembic migration setup

```
Write alembic/env.py for the ai-cicd-pipeline project. It must support both synchronous migrations (for alembic upgrade head CLI) and async engine. Configure it to:

1. Import settings from app.config and Base from app.database
2. Import both pipeline_run and pipeline_artifact models so their tables are registered with Base.metadata
3. Set config.set_main_option("sqlalchemy.url", settings.sync_database_url)
4. Set target_metadata = Base.metadata
5. In run_migrations_online(), use a synchronous engine via engine_from_config with pool=NullPool
6. In run_migrations_offline(), use the URL directly from config

Also write the alembic.ini file with script_location = alembic, prepend_sys_path = ., and sqlalchemy.url = placeholder (it will be overridden in env.py).

Add a comment at top: "Alembic migration environment. Run: alembic revision --autogenerate -m 'init' then alembic upgrade head"
```

---

## PART 3 — UTILITIES AND SERVICES

### Prompt 3.1 — Write app/utils/logger.py

```
Write app/utils/logger.py. Create a structured logger using Python's standard logging module. It must:

1. Create a function get_logger(name: str) -> logging.Logger that returns a configured logger
2. The logger must output JSON-formatted logs in production (APP_ENV=production) and human-readable colored logs in development
3. For JSON format, each log entry must include: timestamp (ISO 8601), level, name, message, and any extra kwargs passed to the log call
4. For human-readable format use: "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
5. Set level to DEBUG in development, INFO in production
6. Add a StreamHandler to stdout
7. At module level, create a root pipeline_logger = get_logger("pipeline") for import convenience
8. The JSON formatter should be a custom class JSONFormatter(logging.Formatter) that overrides format() to return json.dumps(log_record_dict)

Import settings from app.config to determine APP_ENV.
```

---

### Prompt 3.2 — Write app/utils/hmac_validator.py

```
Write app/utils/hmac_validator.py. Create a function validate_github_signature(payload_body: bytes, signature_header: str, secret: str) -> bool that:

1. Returns False immediately if signature_header is None or empty
2. Checks that signature_header starts with "sha256=" — return False if not
3. Uses hmac.new(secret.encode(), payload_body, hashlib.sha256) to compute expected signature
4. Formats expected as "sha256=" + hexdigest
5. Uses hmac.compare_digest(expected, signature_header) for timing-safe comparison
6. Returns the result of compare_digest

Also write a FastAPI dependency function get_validated_github_payload(request: Request, x_hub_signature_256: str = Header(None)) -> bytes that:
1. Reads the raw request body as bytes
2. Calls validate_github_signature with the body, header, and settings.github_webhook_secret
3. Raises HTTPException(status_code=403, detail="Invalid signature") if validation fails
4. Returns the body bytes

Import settings from app.config.
```

---

### Prompt 3.3 — Write app/services/github_service.py

```
Write app/services/github_service.py. Create a class GitHubService with an __init__ that creates an httpx.AsyncClient with base_url="https://api.github.com", headers including Authorization: token {settings.github_token} and Accept: application/vnd.github.v3+json.

Implement these async methods:

1. async def set_commit_status(self, repo_full_name: str, commit_sha: str, state: str, description: str, context: str = "ai-cicd-pipeline/pipeline") -> dict
   - POST to /repos/{repo_full_name}/statuses/{commit_sha}
   - Payload: {"state": state, "description": description[:140], "context": context}
   - state must be one of: pending, success, failure, error
   - Returns response JSON or raises httpx.HTTPStatusError

2. async def create_check_run(self, repo_full_name: str, commit_sha: str, name: str, status: str, conclusion: str = None, output: dict = None) -> dict
   - POST to /repos/{repo_full_name}/check-runs
   - Payload: {"name": name, "head_sha": commit_sha, "status": status, "conclusion": conclusion, "output": output}
   - Returns response JSON

3. async def close(self) -> None: closes the httpx client

Add a module-level singleton github_service = GitHubService() and import settings from app.config.
```

---

### Prompt 3.4 — Write app/services/slack_service.py

```
Write app/services/slack_service.py. Create a class SlackService with async methods for sending notifications:

1. async def send_pipeline_start(self, run_id: str, commit_id: str, branch: str, pusher: str) -> None
   - Sends a Slack message with a green attachment saying pipeline started

2. async def send_pipeline_blocked(self, run_id: str, reason: str, agent: str, details: dict) -> None
   - Sends a red attachment listing what blocked the pipeline

3. async def send_pipeline_deployed(self, run_id: str, commit_id: str, environment: str) -> None
   - Sends a green attachment with deployment success

4. async def send_monitoring_alert(self, run_id: str, anomalies: list, recommended_action: str) -> None
   - Sends an orange/red attachment with anomalies list and recommended action

Each method must:
- Build a Slack Block Kit message payload with header text, mrkdwn section, and colored attachment
- Use httpx.AsyncClient to POST to settings.slack_webhook_url
- Return silently if settings.slack_webhook_url is empty (do not raise)
- Catch all exceptions, log them using get_logger("slack"), but never raise (notifications are non-critical)

Include a helper _send(payload: dict) private async method that does the actual POST.
```

---

### Prompt 3.5 — Write app/services/git_service.py

```
Write app/services/git_service.py. Create a class GitService with these methods:

1. async def clone_repo(self, clone_url: str, run_id: str) -> str
   - Creates directory /tmp/pipeline/{run_id}
   - Clones the repo using subprocess.run(["git", "clone", "--depth=1", clone_url, dest_path])
   - Returns dest_path
   - Logs clone start and completion with timing

2. async def get_diff(self, repo_path: str) -> str
   - Runs subprocess.run(["git", "diff", "HEAD~1", "HEAD"], cwd=repo_path)
   - Returns stdout as string
   - Falls back to subprocess.run(["git", show, "HEAD"]) if HEAD~1 fails (first commit case)

3. async def get_changed_files(self, repo_path: str) -> list[str]
   - Runs git diff --name-only HEAD~1 HEAD
   - Returns list of file paths

4. def cleanup_repo(self, run_id: str) -> None
   - Deletes /tmp/pipeline/{run_id} using shutil.rmtree with ignore_errors=True
   - Logs cleanup

5. async def get_commit_message(self, repo_path: str) -> str
   - Runs git log -1 --pretty=%B
   - Returns the commit message string

Use asyncio.to_thread() to wrap all subprocess.run calls so they don't block the event loop. Import get_logger from app.utils.logger.
```

---

## PART 4 — FASTAPI APPLICATION AND WEBHOOK HANDLER

### Prompt 4.1 — Write app/schemas/webhook.py and pipeline_run.py

```
Write app/schemas/webhook.py with Pydantic v2 models for GitHub webhook parsing:

class GitHubCommit(BaseModel):
    id: str
    message: str
    author: dict
    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []

class GitHubRepository(BaseModel):
    id: int
    full_name: str
    clone_url: str
    default_branch: str

class GitHubPusher(BaseModel):
    name: str
    email: str = ""

class GitHubPushPayload(BaseModel):
    ref: str  (e.g. "refs/heads/main")
    after: str  (the new commit SHA)
    before: str  (the previous commit SHA)
    repository: GitHubRepository
    pusher: GitHubPusher
    head_commit: GitHubCommit
    commits: list[GitHubCommit] = []
    
    @property
    def branch(self) -> str: returns ref split by "/" last part

Also write app/schemas/pipeline_run.py with:

class PipelineRunResponse(BaseModel):
    id: str
    commit_id: str
    short_commit_id: str
    branch: str
    pusher: str
    repo_full_name: str
    status: str
    has_warnings: bool
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class PipelineRunListResponse(BaseModel):
    total: int
    runs: list[PipelineRunResponse]
```

---

### Prompt 4.2 — Write app/api/routes/webhook.py

```
Write app/api/routes/webhook.py. Create a FastAPI APIRouter with prefix="/webhook" and tag="Webhooks".

Implement POST /github endpoint:
1. Parameters: request: Request, db: AsyncSession = Depends(get_db)
2. Use the get_validated_github_payload dependency to validate HMAC signature
3. Parse the body bytes as JSON, then as GitHubPushPayload using model_validate
4. Reject pushes to tags (ref starts with "refs/tags/") with 200 OK and {"status": "ignored", "reason": "tag push"}
5. Create a new PipelineRun SQLAlchemy object with all fields from the payload
6. Add and commit to db
7. Call github_service.set_commit_status with state="pending", description="Pipeline queued"
8. Call slack_service.send_pipeline_start (non-blocking, use asyncio.create_task)
9. Dispatch the Celery task run_pipeline_task.delay(str(pipeline_run.id))
10. Return 202 Accepted with {"status": "accepted", "pipeline_run_id": str(pipeline_run.id), "commit_id": payload.after}

Handle json.JSONDecodeError and ValidationError — return 400 with detail. Handle all other exceptions — return 500 with detail and log the full traceback.

Import everything needed: router, get_db, PipelineRun, GitHubPushPayload, github_service, slack_service, run_pipeline_task, get_validated_github_payload, get_logger.
```

---

### Prompt 4.3 — Write app/api/routes/pipeline.py

```
Write app/api/routes/pipeline.py. Create a FastAPI APIRouter with prefix="/pipeline" and tag="Pipeline".

Implement these endpoints:

1. GET /runs — list all pipeline runs
   - Query params: limit: int = 20, offset: int = 0, status: str | None = None, branch: str | None = None
   - Returns PipelineRunListResponse
   - Filters by status and branch if provided
   - Orders by created_at DESC

2. GET /runs/{run_id} — get single run
   - Returns PipelineRunResponse or 404

3. GET /runs/{run_id}/artifacts — get all artifacts for a run
   - Returns list of dicts with artifact_type, content, created_at
   - Orders by created_at ASC

4. GET /runs/{run_id}/artifacts/{artifact_type} — get specific artifact
   - Returns the single artifact content dict or 404

5. POST /runs/{run_id}/retry — retry a blocked or failed run
   - Only allowed if status starts with "blocked_" or equals "failed"
   - Resets status to "queued", clears error_message
   - Re-dispatches Celery task
   - Returns {"status": "retrying", "pipeline_run_id": run_id}

6. GET /health — simple health check
   - Returns {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

All DB queries use SQLAlchemy async select statements. Use get_db dependency. Use select(PipelineRun).where(...).
```

---

### Prompt 4.4 — Write app/main.py

```
Write app/main.py. Create the main FastAPI application. It must:

1. Create app = FastAPI(title="AI CI/CD Pipeline", version="1.0.0", description="Autonomous AI-powered CI/CD pipeline with multi-agent orchestration") 

2. Add CORSMiddleware allowing all origins, credentials=True, all methods, all headers

3. Add a middleware that logs every request: method, path, status code, and duration in ms using get_logger("http")

4. Include routers: webhook router at /api/v1, pipeline router at /api/v1

5. Add startup event handler (@app.on_event("startup")) that:
   - Logs "Starting AI CI/CD Pipeline server"
   - Calls init_db() to ensure tables exist in dev mode
   - Logs the environment (APP_ENV)

6. Add shutdown event handler that logs "Shutting down"

7. Add GET / root endpoint returning {"name": "AI CI/CD Pipeline API", "version": "1.0.0", "docs": "/docs"}

8. Add exception handler for all Exception types that returns 500 with {"detail": "Internal server error", "error": str(exc)} and logs the traceback

9. At bottom: if __name__ == "__main__": uvicorn.run("app.main:app", host="0.0.0.0", port=settings.app_port, reload=True)

Import app.models.pipeline_run and app.models.pipeline_artifact to ensure models are registered.
```

---

## PART 5 — CELERY TASK WORKER

### Prompt 5.1 — Write app/tasks/pipeline_tasks.py

```
Write app/tasks/pipeline_tasks.py. This file sets up Celery and defines the main pipeline task.

1. Create celery_app = Celery("ai_cicd_pipeline", broker=settings.redis_url, backend=settings.redis_url)

2. Configure celery_app.conf with:
   task_serializer = "json"
   result_serializer = "json"
   accept_content = ["json"]
   timezone = "UTC"
   enable_utc = True
   task_track_started = True
   task_acks_late = True
   worker_prefetch_multiplier = 1
   task_max_retries = 3
   task_default_retry_delay = 60

3. Create a synchronous wrapper run_pipeline_sync(pipeline_run_id: str) that:
   - Creates a new asyncio event loop using asyncio.new_event_loop()
   - Runs the async orchestrator: loop.run_until_complete(orchestrator.execute_pipeline(pipeline_run_id))
   - Closes the loop in a finally block
   - This is needed because Celery workers are synchronous but the orchestrator is async

4. Define @celery_app.task(name="run_pipeline", bind=True, max_retries=3) 
   def run_pipeline_task(self, pipeline_run_id: str):
   - Wraps run_pipeline_sync in a try/except
   - On exception: calls self.retry(exc=exc, countdown=60) if retry count < max_retries
   - Logs start and end of task with pipeline_run_id
   - On final failure after all retries: updates PipelineRun status to "failed" synchronously using a sync SQLAlchemy session

5. Import orchestrator from app.agents.orchestrator (lazy import inside function to avoid circular imports)

Add module-level logger = get_logger("celery.pipeline").
```

---

## PART 6 — BASE AGENT AND ORCHESTRATOR

### Prompt 6.1 — Write app/agents/base_agent.py

```
Write app/agents/base_agent.py. Create an abstract base class BaseAgent using Python's abc module.

The class must have:
1. __init__(self, pipeline_run_id: str, db: AsyncSession, anthropic_client: anthropic.AsyncAnthropic)
   - Stores all three as instance attributes
   - Creates self.logger = get_logger(f"agent.{self.__class__.__name__}")
   - Sets self.start_time = None

2. Abstract method: async def execute(self) -> dict  (each agent implements this)

3. Protected method: async def _call_claude(self, system_prompt: str, user_message: str, max_tokens: int = 2000) -> tuple[str, int]
   - Calls self.anthropic_client.messages.create with model=settings.anthropic_model
   - Uses system=system_prompt, messages=[{"role":"user","content":user_message}]
   - Extracts text from response.content[0].text
   - Returns (text_response, total_tokens_used)
   - Logs the call with agent name, token count, duration
   - Handles anthropic.APIError and re-raises as RuntimeError with context

4. Protected method: async def _call_claude_json(self, system_prompt: str, user_message: str, max_tokens: int = 2000) -> dict
   - Calls _call_claude but instructs system_prompt to end with "Return ONLY valid JSON, no markdown, no backticks, no explanation."
   - Strips any remaining ```json or ``` from response
   - Parses with json.loads()
   - If JSONDecodeError: retries once with a stricter prompt "Your previous response was not valid JSON. Return ONLY the JSON object."
   - Returns parsed dict or raises ValueError with the raw response appended

5. Protected method: async def _save_artifact(self, artifact_type: str, content: dict, raw_output: str = None, tokens_used: int = None, duration_seconds: float = None) -> PipelineArtifact
   - Creates and saves a PipelineArtifact to the database
   - Commits and returns the artifact

6. Protected method: async def _update_run_status(self, status: str, error_message: str = None) -> None
   - Fetches PipelineRun by pipeline_run_id
   - Updates status and optionally error_message
   - Commits

7. Property: elapsed_seconds -> float: returns time.time() - self.start_time if start_time else 0
```

---

### Prompt 6.2 — Write app/agents/orchestrator.py

```
Write app/agents/orchestrator.py. Create class PipelineOrchestrator.

__init__(self):
- Creates self.anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
- Creates self.git_service = GitService()
- Creates self.github_service = GitHubService()
- Creates self.slack_service = SlackService()
- Creates self.logger = get_logger("orchestrator")

async def execute_pipeline(self, pipeline_run_id: str) -> None:
This is the main method that runs the full pipeline. It must:

1. Open an AsyncSession using AsyncSessionLocal as context manager
2. Fetch PipelineRun by id, raise ValueError if not found
3. Log "Starting pipeline for run {pipeline_run_id} commit {run.short_commit_id}"
4. Call github_service.set_commit_status(pending, "Pipeline running...")
5. Execute each stage in sequence, wrapped in individual try/except blocks:

   STAGE 1 - Ingestion:
   - Update status to "ingesting"
   - Clone repo using git_service.clone_repo
   - Get diff using git_service.get_diff
   - Get changed files list
   - Save artifact type="metadata" with commit info and file list
   - Save artifact type="diff" with raw diff text

   STAGE 2 - Code Analysis:
   - Update status to "analyzing_code"
   - Instantiate CodeAnalysisAgent(pipeline_run_id, db, anthropic_client, repo_path, diff_text)
   - result = await agent.execute()
   - If result["severity"] == "fail": block pipeline, call _handle_block("blocked_code", result)
   - Continue if pass or warn

   STAGE 3 - Security:
   - Update status to "analyzing_security"
   - Instantiate SecurityAgent, execute, check highest_severity
   - If highest_severity in ["high","critical"]: block with "blocked_security"

   STAGE 4 - QA Testing:
   - Update status to "running_qa"
   - Instantiate QAAgent, execute
   - If result["verdict"] == "fail": block with "blocked_tests"

   STAGE 5 - Stress Testing:
   - Update status to "running_stress"
   - Instantiate StressTestAgent, execute
   - If result["performance_verdict"] == "fail": block with "blocked_stress"
   - If "warn": set run.has_warnings = True, commit

   STAGE 6 - Approval:
   - Update status to "awaiting_approval"
   - Instantiate ApprovalAgent, execute
   - If result["decision"] == "rejected": block with "rejected"

   STAGE 7 - Deployment:
   - Update status to "deploying"
   - Instantiate DeploymentAgent, execute
   - If deploy fails: update status "failed", call _handle_block

   STAGE 8 - Monitoring:
   - Update status to "monitoring"
   - Start MonitoringAgent as asyncio background task (not awaited immediately)

   SUCCESS:
   - Update status to "deployed"
   - github_service.set_commit_status("success", "Pipeline passed, deployed successfully")
   - slack_service.send_pipeline_deployed(...)

6. Cleanup: git_service.cleanup_repo(run_id) in a finally block

async def _handle_block(self, status: str, result: dict, run: PipelineRun) -> None:
   - Updates run.status and run.error_message with result summary
   - Calls github_service.set_commit_status("failure", f"Pipeline blocked: {status}")
   - Calls slack_service.send_pipeline_blocked(...)
   - Logs the block event

Create module-level singleton: orchestrator = PipelineOrchestrator()
```

---

## PART 7 — AI AGENTS (DETAILED)

### Prompt 7.1 — Write app/agents/code_analysis_agent.py

```
Write app/agents/code_analysis_agent.py. Create class CodeAnalysisAgent(BaseAgent).

__init__(self, pipeline_run_id: str, db: AsyncSession, anthropic_client, repo_path: str, diff_text: str):
- Calls super().__init__(pipeline_run_id, db, anthropic_client)
- Stores repo_path and diff_text

async def execute(self) -> dict:

STEP 1 - Run pylint:
- Find all .py files in repo_path using glob.glob("**/*.py", recursive=True)
- Filter to only files mentioned in diff_text (changed files only)
- For each file (max 20 files), run: subprocess.run(["pylint", "--output-format=json", "--disable=C0111,W0611", file_path], capture_output=True, text=True, timeout=30)
- Parse stdout as JSON list (handle JSONDecodeError per file)
- Accumulate all issues into list of dicts with keys: file, line, column, message_id, message, type (convention/warning/error/fatal)
- Also run: subprocess.run(["pylint", "--output-format=json", "--disable=C0111,W0611", repo_path], capture_output=True, text=True, timeout=60) as fallback

STEP 2 - Run AST analysis:
- For each changed .py file, read the source, run ast.parse(source)
- Count: undefined names (use pyflakes-style: ast.walk looking for Name nodes not in scope), unused imports, functions with no docstrings (ast.FunctionDef without ast.Expr(ast.Constant) as first body node)
- Build ast_issues list

STEP 3 - Prepare Claude prompt:
system_prompt = """You are a senior software engineer performing a code review. 
Analyze the provided code diff and lint results. Return ONLY valid JSON in this exact schema:
{
  "issues": [{"file": string, "line": int, "type": "error"|"warning"|"convention"|"info", "description": string, "suggestion": string}],
  "severity": "pass"|"warn"|"fail",
  "summary": string (2-3 sentences),
  "good_practices_found": [string],
  "critical_issues_count": int,
  "warnings_count": int
}
severity rules: "fail" if any fatal/error type AND critical_issues_count >= 3. "warn" if warnings_count >= 5. Otherwise "pass". Return ONLY valid JSON."""

user_message = f"DIFF:\n{diff_text[:8000]}\n\nPYLINT ISSUES:\n{json.dumps(pylint_issues[:50])}\n\nAST ISSUES:\n{json.dumps(ast_issues[:20])}"

STEP 4 - Call Claude and parse:
- result, tokens = await self._call_claude_json(system_prompt, user_message, max_tokens=2000)

STEP 5 - Save artifact:
- await self._save_artifact("code_analysis", result, raw_output=raw_pylint_output, tokens_used=tokens, duration_seconds=self.elapsed_seconds)

STEP 6 - Return result dict
```

---

### Prompt 7.2 — Write app/agents/security_agent.py

```
Write app/agents/security_agent.py. Create class SecurityAgent(BaseAgent).

__init__(self, pipeline_run_id, db, anthropic_client, repo_path: str, diff_text: str):
- super().__init__ + store repo_path, diff_text

async def execute(self) -> dict:

STEP 1 - Run Bandit:
- Run: subprocess.run(["bandit", "-r", repo_path, "-f", "json", "-ll"], capture_output=True, text=True, timeout=120)
- Parse stdout as JSON. The bandit JSON has structure: {"results": [...], "metrics": {...}}
- Each result has: filename, test_id, test_name, issue_severity ("LOW"/"MEDIUM"/"HIGH"), issue_confidence, issue_text, line_number
- If bandit exits with code 1 (found issues) that is NORMAL — still parse the JSON
- Store as bandit_findings list

STEP 2 - Run Safety:
- Check if requirements.txt exists in repo_path
- If exists: run subprocess.run(["safety", "check", "-r", f"{repo_path}/requirements.txt", "--json"], capture_output=True, text=True, timeout=60)
- Parse stdout as JSON. Safety output is a list of [package, installed_version, affected_version, description, vulnerability_id]
- Map to dicts: {"package": ..., "installed_version": ..., "vulnerability_id": ..., "description": ...[:200]}
- If requirements.txt missing: set safety_findings = []

STEP 3 - Claude enrichment:
system_prompt = """You are a security engineer reviewing code vulnerabilities. 
Analyze bandit scan results and dependency vulnerabilities. Return ONLY valid JSON:
{
  "vulnerabilities": [{"type": string, "severity": "low"|"medium"|"high"|"critical", "file": string, "line": int, "description": string, "recommendation": string, "cve": string|null}],
  "highest_severity": "none"|"low"|"medium"|"high"|"critical",
  "security_score": int (0-100, 100=perfect),
  "summary": string,
  "immediate_actions": [string],
  "total_count": int,
  "high_critical_count": int
}
severity mapping: bandit HIGH=high, MEDIUM=medium, LOW=low. safety findings default to high.
Return ONLY valid JSON."""

user_message = f"BANDIT FINDINGS:\n{json.dumps(bandit_findings[:30])}\n\nSAFETY FINDINGS:\n{json.dumps(safety_findings[:20])}\n\nDIFF CONTEXT:\n{diff_text[:3000]}"

STEP 4 - Call Claude, save artifact type="security_scan"
STEP 5 - Return result
```

---

### Prompt 7.3 — Write app/agents/qa_agent.py

```
Write app/agents/qa_agent.py. Create class QAAgent(BaseAgent).

__init__(self, pipeline_run_id, db, anthropic_client, repo_path: str):
- super().__init__ + store repo_path

async def execute(self) -> dict:

STEP 1 - Check for tests directory:
- Check if {repo_path}/tests or {repo_path}/test exists
- If neither: return early with {"verdict": "pass", "summary": "No test directory found, skipping QA", "test_summary": {"total": 0, "passed": 0, "failed": 0}, "skipped": True}

STEP 2 - Run pytest:
- json_report_path = f"/tmp/pipeline/{self.pipeline_run_id}/pytest_report.json"
- cmd = ["pytest", repo_path, "--tb=short", "--json-report", f"--json-report-file={json_report_path}", "--timeout=120", "-x", "--no-header", "-q"]
- Run with subprocess.run, capture_output=True, text=True, timeout=180
- Read and parse json_report_path if it exists
- Extract from report: summary.total, summary.passed, summary.failed, summary.error
- For each failed test: extract nodeid, call.longrepr (traceback), call.duration, stage

STEP 3 - Claude analysis:
system_prompt = """You are a QA engineer analyzing test results. Return ONLY valid JSON:
{
  "test_summary": {"total": int, "passed": int, "failed": int, "errors": int, "duration_seconds": float},
  "verdict": "pass"|"fail",
  "root_causes": [{"test": string, "cause": string, "category": "assertion"|"exception"|"timeout"|"import_error"|"other"}],
  "recommendations": [string],
  "summary": string,
  "flaky_test_indicators": [string]
}
verdict is "fail" if failed > 0 OR errors > 0. Return ONLY valid JSON."""

user_message = f"PYTEST REPORT SUMMARY:\n{json.dumps(pytest_summary)}\n\nFAILED TESTS:\n{json.dumps(failed_tests[:10])}\n\nSTDOUT:\n{stdout[:2000]}"

STEP 4 - Call Claude, save artifact type="qa_report"
STEP 5 - Return result
```

---

### Prompt 7.4 — Write app/agents/stress_test_agent.py

```
Write app/agents/stress_test_agent.py. Create class StressTestAgent(BaseAgent).

__init__(self, pipeline_run_id, db, anthropic_client, repo_path: str):
- super().__init__ + store repo_path

async def execute(self) -> dict:

STEP 1 - Generate locustfile:
- Write the following locustfile to /tmp/pipeline/{pipeline_run_id}/locustfile.py:

```python
from locust import HttpUser, task, between

class PipelineUser(HttpUser):
    wait_time = between(0.5, 2.0)
    
    @task(3)
    def health_check(self):
        self.client.get("/health", timeout=5)
    
    @task(2) 
    def get_runs(self):
        self.client.get("/api/v1/pipeline/runs?limit=10", timeout=5)
    
    @task(1)
    def get_root(self):
        self.client.get("/", timeout=5)
```

STEP 2 - Run locust headless:
- csv_prefix = f"/tmp/pipeline/{self.pipeline_run_id}/stress"
- cmd = ["locust", "--headless", f"-u {settings.stress_test_users}", f"-r {settings.stress_test_spawn_rate}", f"--run-time {settings.stress_test_duration}s", f"--csv={csv_prefix}", f"--host={settings.staging_url}", f"--locustfile=/tmp/pipeline/{self.pipeline_run_id}/locustfile.py", "--only-summary"]
- Run with subprocess.run, timeout=settings.stress_test_duration + 30

STEP 3 - Parse CSV results:
- Read {csv_prefix}_stats.csv using csv.DictReader
- Extract for each row: Name, Request Count, Failure Count, Average (ms), 95%ile (ms), Max (ms), Requests/s
- Calculate overall: total_requests, total_failures, failure_rate_pct, avg_response_ms, p95_ms, max_ms

STEP 4 - Claude analysis:
system_prompt = """You are a performance engineer analyzing load test results. Return ONLY valid JSON:
{
  "performance_verdict": "pass"|"warn"|"fail",
  "p95_ms": float,
  "avg_ms": float,
  "error_rate_pct": float,
  "requests_per_second": float,
  "bottlenecks": [string],
  "performance_score": int (0-100),
  "summary": string,
  "recommendations": [string]
}
verdict: "fail" if error_rate_pct > 5 OR p95_ms > 2000. "warn" if error_rate_pct > 1 OR p95_ms > 1000. "pass" otherwise.
Return ONLY valid JSON."""

STEP 5 - Save artifact type="stress_report", return result
```

---

### Prompt 7.5 — Write app/agents/approval_agent.py

```
Write app/agents/approval_agent.py. Create class ApprovalAgent(BaseAgent).

__init__(self, pipeline_run_id, db, anthropic_client):
- super().__init__ only (no repo needed)

async def execute(self) -> dict:

STEP 1 - Gather all prior artifacts:
- Query all PipelineArtifacts for this pipeline_run_id ordered by created_at
- Build a summary dict:
  {
    "code_analysis": {"severity": ..., "critical_issues_count": ..., "warnings_count": ..., "summary": ...},
    "security": {"highest_severity": ..., "high_critical_count": ..., "security_score": ..., "summary": ...},
    "qa": {"verdict": ..., "test_summary": ..., "summary": ...},
    "stress": {"performance_verdict": ..., "p95_ms": ..., "error_rate_pct": ..., "summary": ...},
    "has_warnings": run.has_warnings
  }

STEP 2 - Apply hard-coded rules first (before calling Claude):
- BLOCK immediately if: code severity=="fail" OR security highest_severity in ["high","critical"] OR qa verdict=="fail" OR stress verdict=="fail"
- If blocked by rules: skip Claude, return {"decision": "rejected", "confidence": 1.0, "reason": "Hard rule violated: ...", "blocked_by": "rule_engine"}

STEP 3 - Call Claude for nuanced decision:
system_prompt = """You are a principal engineer making a deployment approval decision. 
Review all pipeline results and decide whether to approve deployment to production.
Apply these rules strictly:
- REJECT if any security finding is high or critical severity
- REJECT if test failure rate > 0%
- REJECT if p95 response time > 2000ms under load
- REJECT if code analysis severity is "fail"
- APPROVE with warnings if there are minor warnings but no critical issues
Return ONLY valid JSON:
{
  "decision": "approved"|"rejected",
  "confidence": float (0.0-1.0),
  "reason": string (one sentence),
  "warnings": [string],
  "approval_conditions": [string],
  "risk_level": "low"|"medium"|"high"
}
Return ONLY valid JSON."""

user_message = f"PIPELINE RESULTS:\n{json.dumps(summary, indent=2)}"

STEP 4 - Save artifact type="approval", return result
```

---

### Prompt 7.6 — Write app/agents/deployment_agent.py

```
Write app/agents/deployment_agent.py. Create class DeploymentAgent(BaseAgent).

__init__(self, pipeline_run_id, db, anthropic_client, repo_path: str, commit_id: str):
- super().__init__ + store repo_path, commit_id

async def execute(self) -> dict:

STEP 1 - Save last known good image (before deploying):
- Query for any existing "last_known_good_image" artifact for this project in recent successful runs
- This is used for rollback

STEP 2 - Build Docker image:
- image_tag = f"{settings.container_registry}/{settings.app_name}:{self.commit_id[:8]}"
- Check if Dockerfile exists in repo_path, if not: create a minimal one
- Run: subprocess.run(["docker", "build", "-t", image_tag, repo_path], capture_output=True, text=True, timeout=300)
- If returncode != 0: raise RuntimeError(f"Docker build failed:\n{stderr}")
- Log image_tag

STEP 3 - Push image (only if registry is configured):
- If settings.container_registry is not empty:
  - Run: subprocess.run(["docker", "push", image_tag], capture_output=True, text=True, timeout=300)
  - If fails: raise RuntimeError

STEP 4 - Deploy to environment:
- For staging/development: simulate by running the container locally
  - subprocess.run(["docker", "stop", f"{settings.app_name}-staging"], capture_output=True) [ignore error]
  - subprocess.run(["docker", "rm", f"{settings.app_name}-staging"], capture_output=True) [ignore error]
  - subprocess.run(["docker", "run", "-d", "--name", f"{settings.app_name}-staging", "-p", "8080:8000", image_tag], capture_output=True, text=True, timeout=60)

STEP 5 - Health check polling:
- Poll GET {settings.staging_url}/health every 5 seconds
- Use httpx.AsyncClient with timeout=5
- If returns 200: deployment healthy, break
- If 180 seconds pass with no 200: trigger rollback
- Write async def _poll_health(self, url: str, timeout_s: int) -> bool

STEP 6 - Rollback logic:
- async def _rollback(self, reason: str) -> None:
  - Fetch last_known_good_image artifact
  - If exists: re-run docker commands with previous image tag
  - Update run status to "rolled_back"
  - Call slack_service to notify

STEP 7 - Save artifact type="deployment_info":
{"image_tag": ..., "environment": ..., "deployed_at": ..., "health_check_passed": bool}

Return result dict
```

---

### Prompt 7.7 — Write app/agents/monitoring_agent.py

```
Write app/agents/monitoring_agent.py. Create class MonitoringAgent(BaseAgent).

__init__(self, pipeline_run_id, db, anthropic_client):
- super().__init__ only

async def execute(self) -> None:
This runs indefinitely as a background task. It must:

STEP 1 - Main monitoring loop:
- Run for maximum 30 minutes (settings.monitoring_window_minutes * 6) 
- Sleep settings.monitoring_poll_interval_seconds between each check
- Track consecutive_alerts counter

STEP 2 - Per-poll cycle: async def _collect_metrics(self) -> dict
- Read container logs: subprocess.run(["docker", "logs", "--since", f"{settings.monitoring_poll_interval_seconds}s", "--tail", "200", f"{settings.app_name}-staging"], capture_output=True, text=True)
- Parse logs to count: ERROR lines, WARNING lines, exception lines (contain "Traceback" or "Exception:")
- Attempt health endpoint: GET {settings.staging_url}/health, record response_time_ms and status_code
- Return metrics dict: {"error_count": N, "warning_count": N, "exception_count": N, "health_status_code": N, "response_time_ms": N, "log_lines": [...last 50...]}

STEP 3 - Claude anomaly detection (only if metrics show issues):
- Only call Claude if error_count > 5 OR exception_count > 0 OR health_status_code != 200
system_prompt = """You are a site reliability engineer monitoring a production deployment.
Analyze log metrics and decide if action is needed. Return ONLY valid JSON:
{
  "status": "healthy"|"degraded"|"critical",
  "anomalies": [{"type": string, "description": string, "severity": "low"|"medium"|"high"}],
  "recommended_action": "monitor"|"alert"|"rollback",
  "error_spike": bool,
  "performance_degraded": bool,
  "summary": string
}
recommended_action: "rollback" only if status=="critical" and error spike or health check failing.
Return ONLY valid JSON."""

STEP 4 - Act on recommendation:
- If recommended_action=="rollback" and consecutive_alerts >= 2:
  - Import DeploymentAgent and call _rollback(reason)
  - Update run status to "auto_rolled_back"
  - await slack_service.send_monitoring_alert(...)
  - Break the loop

- If recommended_action=="alert":
  - await slack_service.send_monitoring_alert(...)
  - Save artifact type="monitoring_alert"
  - Increment consecutive_alerts

- If status=="healthy":
  - Reset consecutive_alerts = 0

STEP 5 - End of monitoring window:
- Save final monitoring summary artifact
- Update run status to "deployed" (monitoring complete, all clear)
```

---

## PART 8 — TESTS

### Prompt 8.1 — Write tests/conftest.py

```
Write tests/conftest.py with pytest fixtures for the entire test suite.

1. @pytest.fixture(scope="session") async def test_db_engine():
   - Creates a test SQLite in-memory async engine using aiosqlite
   - Creates all tables using Base.metadata.create_all
   - Yields engine
   - Drops all tables after session

2. @pytest.fixture async def db_session(test_db_engine):
   - Creates an AsyncSession from the test engine
   - Wraps in a transaction that is always rolled back after test
   - Yields session

3. @pytest.fixture def mock_anthropic_client(mocker):
   - Creates a MagicMock for anthropic.AsyncAnthropic
   - Mock messages.create returns a mock with content=[Mock(text='{"severity":"pass","issues":[],"summary":"ok"}')]
   - Returns the mock client

4. @pytest.fixture def sample_github_payload():
   - Returns a dict matching GitHubPushPayload structure with fake data
   - commit id: "abc123def456abc123def456abc123def456abc1"
   - branch: "main"
   - repo: {"full_name": "testuser/testrepo", "clone_url": "https://github.com/testuser/testrepo.git"}

5. @pytest.fixture def sample_diff_text():
   - Returns a realistic Python diff string showing a modified function with a potential SQL injection vulnerability and an unused import

6. @pytest.fixture def sample_pytest_report():
   - Returns a dict matching pytest-json-report format with 5 passed, 2 failed tests
```

---

### Prompt 8.2 — Write tests/test_webhook.py

```
Write tests/test_webhook.py with the following test cases using pytest-asyncio and TestClient from FastAPI:

1. test_webhook_valid_signature — sends a valid POST /api/v1/webhook/github with correct HMAC signature, asserts 202 response and {"status": "accepted"} in body

2. test_webhook_invalid_signature — sends request with wrong signature, asserts 403 response

3. test_webhook_tag_push — sends payload where ref="refs/tags/v1.0.0", asserts 200 and {"status": "ignored"}

4. test_webhook_missing_signature_header — sends request with no X-Hub-Signature-256 header, asserts 403

5. test_webhook_invalid_json — sends garbage body with valid signature, asserts 400

Each test must mock: Celery task (so it doesn't actually run), database session (use the db_session fixture), github_service.set_commit_status (mock to return None), slack_service.send_pipeline_start (mock to return None).

Use @pytest.mark.asyncio for async tests. Use httpx.AsyncClient(app=app, base_url="http://test") as the test client.
```

---

### Prompt 8.3 — Write tests/test_agents/test_code_analysis.py

```
Write tests/test_agents/test_code_analysis.py with these tests:

1. test_code_analysis_pass — creates CodeAnalysisAgent with a simple clean diff, mocks subprocess.run to return empty pylint JSON, mocks _call_claude_json to return {"severity":"pass","issues":[],"summary":"Clean code","good_practices_found":[],"critical_issues_count":0,"warnings_count":0}, asserts execute() returns dict with severity=="pass"

2. test_code_analysis_fail_on_errors — mocks pylint to return 3 high-severity errors, mocks Claude to return {"severity":"fail",...}, asserts severity=="fail"

3. test_code_analysis_saves_artifact — asserts that after execute(), a PipelineArtifact with type=="code_analysis" exists in the test database

4. test_code_analysis_handles_pylint_crash — mocks subprocess.run to raise subprocess.TimeoutExpired, asserts execute() still completes (falls back to empty issues) and returns a result without raising

5. test_code_analysis_truncates_large_diff — creates a 20000-character diff, asserts that the user_message passed to Claude is no longer than 12000 characters (diff is truncated to 8000)

Use @pytest.mark.asyncio. Mock all subprocess calls. Use db_session and mock_anthropic_client fixtures.
```

---

## PART 9 — SAMPLE FIXTURES

### Prompt 9.1 — Write test fixtures

```
Write tests/fixtures/sample_diff.txt — a realistic git unified diff showing:
- A Python file app/api/users.py being modified
- An added function get_user_by_email(email) that constructs a raw SQL string with f-string interpolation (the SQL injection vulnerability that the security agent should catch)
- A removed import that is no longer used
- A modified function that now lacks a docstring
- At least 40 lines of realistic diff content with proper +/- prefix syntax

Write tests/fixtures/sample_pytest_report.json — a realistic pytest-json-report output with:
- 7 total tests: 5 passed, 2 failed
- Failing tests: test_user_creation (AssertionError: expected 200 got 422) and test_delete_cascade (sqlalchemy.exc.IntegrityError)
- Each test has nodeid, outcome, call.duration, and for failed: call.longrepr with traceback
- Matches the exact schema that pytest-json-report 1.5.0 produces
```

---

## PART 10 — ALEMBIC INITIAL MIGRATION

### Prompt 10.1 — Generate first migration

```
After running "alembic revision --autogenerate -m 'initial_tables'", write the content of the generated migration file in alembic/versions/. The migration must create both tables with exact column definitions matching the SQLAlchemy models:

For pipeline_runs table:
- id UUID primary key with gen_random_uuid() server default
- All string/text columns with correct lengths
- All timestamp columns with timezone=True and correct server defaults
- Correct index on commit_id and status columns

For pipeline_artifacts table:
- id UUID primary key
- pipeline_run_id UUID with FK to pipeline_runs.id with ON DELETE CASCADE
- artifact_type VARCHAR(50) with index
- content JSONB (use postgresql JSONB type, not plain JSON, for better query performance)
- raw_output TEXT nullable
- agent_model VARCHAR(100) nullable
- tokens_used INTEGER nullable
- duration_seconds FLOAT nullable
- created_at TIMESTAMPTZ with server default now()

The down() function must drop both tables in reverse order (artifacts first, then runs).
Also write a comment at top: "Run with: alembic upgrade head"
```

---

## PART 11 — README AND RUNNING THE PROJECT

### Prompt 11.1 — Write README.md

```
Write a complete README.md for ai-cicd-pipeline with these sections:

## Overview
Brief description of what the project does — autonomous AI CI/CD pipeline with 9-stage agent chain.

## Architecture
Text diagram showing the flow: GitHub Push → Webhook → Celery → Orchestrator → [8 Agents] → Production

## Prerequisites
- Python 3.11+
- Docker and Docker Compose
- PostgreSQL 15 (or use Docker Compose)
- Redis 7 (or use Docker Compose)
- GitHub account with webhook access
- Anthropic API key

## Quick Start
Step-by-step commands:
1. git clone and cd
2. cp .env.example .env and fill in values
3. docker-compose up -d postgres redis
4. pip install -r requirements.txt
5. alembic upgrade head
6. uvicorn app.main:app --reload (terminal 1)
7. celery -A app.tasks.pipeline_tasks.celery_app worker --loglevel=info (terminal 2)
8. Configure GitHub webhook: URL=http://your-server:8000/api/v1/webhook/github, Content-Type=application/json, Secret=your GITHUB_WEBHOOK_SECRET value, Events=Push

## Full Docker Setup
docker-compose up --build

## Environment Variables
Table of all env vars, their descriptions, and example values

## API Endpoints
Table: Method, Path, Description for all endpoints

## Agent Pipeline Stages
Numbered list of all 9 stages with what each checks and what causes it to block

## Running Tests
pytest tests/ -v

## Monitoring
Access Flower at http://localhost:5555 to monitor Celery tasks
```

---

## FINAL VERIFICATION CHECKLIST

### Prompt 12.1 — Final wiring check

```
Review the entire ai-cicd-pipeline project and fix any import errors, circular imports, or missing wiring. Specifically check and fix:

1. In app/models/__init__.py: import both PipelineRun and PipelineArtifact so SQLAlchemy registers them
2. In app/main.py: verify both routers are included and the import chain app→api→routes→agents does not create circular imports
3. In app/tasks/pipeline_tasks.py: verify the orchestrator is imported inside the task function body (not at module top) to prevent circular import
4. In app/agents/orchestrator.py: verify all 8 agent classes are imported correctly with their correct constructor signatures
5. In app/database.py: verify AsyncSessionLocal uses the correct import (sessionmaker from sqlalchemy.orm and AsyncSession from sqlalchemy.ext.asyncio)
6. Create a script scripts/verify_imports.py that attempts to import every module in the project and prints OK or the import error for each one
7. Write a health-check script scripts/smoke_test.py that: starts the app in test mode, sends a fake webhook payload with a valid HMAC signature, waits 2 seconds, then calls GET /api/v1/pipeline/runs and verifies a run was created

Also ensure the following module-level singletons are only instantiated when the module is imported (not during import of the module itself): orchestrator in orchestrator.py, github_service in github_service.py, slack_service in slack_service.py.
```

---

*End of build guide — 47 Copilot prompts covering every file, every class, every method, and every integration point in the AI CI/CD Pipeline project.*
