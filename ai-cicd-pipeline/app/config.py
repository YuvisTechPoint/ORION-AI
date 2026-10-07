import json
import os
import tempfile

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_MARKERS = ("your-", "xxx/yyy/zzz", "sk-ant-api03-your", "ghp_your")


def _is_placeholder(value: str | None) -> bool:
    if not value or not value.strip():
        return True
    low = value.strip().lower()
    return any(marker in low for marker in _PLACEHOLDER_MARKERS)


def _settings_env_files() -> tuple[str, ...]:
    if os.getenv("APP_ENV", "").lower() in {"production", "prod"}:
        return (".env.production", ".env")
    return (".env",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_settings_env_files(),
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    app_env: str = Field(default="development")
    app_port: int = Field(default=8001)
    stack_host: str = Field(default="127.0.0.1", alias="STACK_HOST")
    hub_url: str = Field(default="http://127.0.0.1:5180")
    canonical_api_url: str = Field(default="http://127.0.0.1:8000")
    canonical_ui_url: str = Field(default="http://127.0.0.1:5173")
    devops_api_url: str = Field(default="http://127.0.0.1:8002")
    devops_ui_url: str = Field(default="http://127.0.0.1:3000")
    secret_key: str = Field(default="orion-secret-key-min-32-chars-here")
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/aicicd"
    )
    sync_database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/aicicd"
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    anthropic_api_key: str = Field(default="sk-ant-api03-your-key-here")
    anthropic_model: str = Field(default="claude-sonnet-4-20250514")
    github_webhook_secret: str = Field(default="your-webhook-secret")
    github_token: str = Field(default="ghp_your-personal-access-token")
    github_owner: str = Field(default="your-github-username")
    github_client_id: str = Field(default="your-oauth-app-client-id")
    github_client_secret: str = Field(default="your-oauth-app-client-secret")
    github_redirect_uri: str = Field(
        default="http://127.0.0.1:8001/api/v1/auth/github/callback"
    )
    github_app_enabled: bool = Field(default=False, alias="GITHUB_APP_ENABLED")
    github_app_id: str = Field(default="", alias="GITHUB_APP_ID")
    github_app_client_id: str = Field(default="", alias="GITHUB_APP_CLIENT_ID")
    github_app_private_key: str = Field(default="", alias="GITHUB_APP_PRIVATE_KEY")
    github_app_webhook_secret: str = Field(default="", alias="GITHUB_APP_WEBHOOK_SECRET")
    github_app_name: str = Field(default="ORION DevOps", alias="GITHUB_APP_NAME")
    github_app_description: str = Field(
        default="AI-native CI/CD pipeline, PR intelligence, and release gates for your repositories.",
        alias="GITHUB_APP_DESCRIPTION",
    )
    github_app_installation_mode: str = Field(default="repository", alias="GITHUB_APP_INSTALLATION_MODE")
    github_app_config_json: str = Field(default="{}", alias="GITHUB_APP_CONFIG_JSON")
    session_secret_key: str = Field(default="orion-super-secret-session-key-abc123")
    frontend_url: str = Field(default="http://127.0.0.1:8001/ui/")
    cors_origins: str = Field(
        default=(
            "http://127.0.0.1:8001,http://127.0.0.1:5173,http://127.0.0.1:3000,http://127.0.0.1:5180,"
            "http://localhost:8001,http://localhost:5173,http://localhost:3000,http://localhost:5180"
        )
    )
    oauth_token_expiry_hours: int = Field(default=24)
    slack_webhook_url: str = Field(
        default="https://hooks.slack.com/services/xxx/yyy/zzz"
    )
    slo_alert_slack_enabled: bool = Field(default=True, alias="SLO_ALERT_SLACK_ENABLED")
    slo_alert_cooldown_seconds: int = Field(default=3600, alias="SLO_ALERT_COOLDOWN_SECONDS")
    staging_url: str = Field(default="http://localhost:8080")
    staging_container_port: int = Field(default=8000)
    staging_host_port: int = Field(default=8080)
    container_registry: str = Field(default="your-registry.io")
    app_name: str = Field(default="orion-app")
    deploy_environment: str = Field(default="staging")
    max_security_severity: str = Field(default="medium")
    stress_test_users: int = Field(default=1000)
    stress_test_duration: int = Field(default=60)
    stress_test_spawn_rate: int = Field(default=50)
    stress_test_profile: str = Field(default="standard", alias="STRESS_TEST_PROFILE")
    performance_baseline_gate_enabled: bool = Field(default=False, alias="PERFORMANCE_BASELINE_GATE_ENABLED")
    performance_p95_regression_percent: float = Field(default=25.0, alias="PERFORMANCE_P95_REGRESSION_PERCENT")
    performance_p95_regression_ms: float = Field(default=500.0, alias="PERFORMANCE_P95_REGRESSION_MS")
    performance_error_rate_delta_percent: float = Field(default=1.0, alias="PERFORMANCE_ERROR_RATE_DELTA_PERCENT")
    performance_intelligence_model: str = Field(default="claude-sonnet-4-20250514")
    monitoring_poll_interval_seconds: int = Field(default=30)
    monitoring_window_minutes: int = Field(default=5)
    health_check_timeout_seconds: int = Field(default=180)
    pipeline_workdir: str = Field(default=os.path.join(tempfile.gettempdir(), "orion-pipeline"))
    pipeline_workdir_cleanup_retries: int = Field(default=5, alias="PIPELINE_WORKDIR_CLEANUP_RETRIES")
    pipeline_workdir_stale_hours: int = Field(default=24, alias="PIPELINE_WORKDIR_STALE_HOURS")
    stale_run_timeout_minutes: int = Field(default=120)
    # auto: Celery when REDIS_URL answers, otherwise run pipelines inside the API process.
    pipeline_executor: str = Field(default="auto")
    pipeline_inline_concurrency: int = Field(default=2)
    # auto: deploy with Docker when the daemon answers, otherwise simulate deployment so the
    # pipeline still reaches deployed + monitoring without a local Docker install.
    deploy_mode: str = Field(default="auto")
    progressive_delivery_enabled: bool = Field(default=True, alias="PROGRESSIVE_DELIVERY_ENABLED")
    canary_stages: str = Field(default="5,25,50,100", alias="CANARY_STAGES")
    canary_max_p95_ms: int = Field(default=2000, alias="CANARY_MAX_P95_MS")
    deployment_strategy: str = Field(default="canary", alias="DEPLOYMENT_STRATEGY")
    deployment_slo_gate_enabled: bool = Field(default=False, alias="DEPLOYMENT_SLO_GATE_ENABLED")
    deployment_intelligence_model: str = Field(default="claude-sonnet-4-20250514")
    observability_anomaly_gate_enabled: bool = Field(default=False, alias="OBSERVABILITY_ANOMALY_GATE_ENABLED")
    observability_intelligence_model: str = Field(default="claude-sonnet-4-20250514")
    remediation_autonomy_max_level: str = Field(default="L4", alias="REMEDIATION_AUTONOMY_MAX_LEVEL")
    remediation_l5_auto_retry_enabled: bool = Field(default=False, alias="REMEDIATION_L5_AUTO_RETRY_ENABLED")
    remediation_l6_auto_deploy_enabled: bool = Field(default=False, alias="REMEDIATION_L6_AUTO_DEPLOY_ENABLED")
    remediation_intelligence_model: str = Field(default="claude-sonnet-4-20250514")
    incident_p0_slack_enabled: bool = Field(default=True, alias="INCIDENT_P0_SLACK_ENABLED")
    incident_intelligence_model: str = Field(default="claude-sonnet-4-20250514")
    preview_base_url: str = Field(
        default="http://{pr}.preview.orion.internal", alias="PREVIEW_BASE_URL"
    )
    slo_target_availability: float = Field(default=0.999, alias="SLO_TARGET_AVAILABILITY")
    synthetic_monitoring_live: bool = Field(default=False, alias="SYNTHETIC_MONITORING_LIVE")
    policy_enforcement_enabled: bool = Field(default=True, alias="POLICY_ENFORCEMENT_ENABLED")
    policy_strict_requirements: bool = Field(default=False, alias="POLICY_STRICT_REQUIREMENTS")
    policy_org_rules_json: str = Field(default="{}", alias="POLICY_ORG_RULES_JSON")
    policy_repo_rules_json: str = Field(default="{}", alias="POLICY_REPO_RULES_JSON")
    policy_env_rules_json: str = Field(default="{}", alias="POLICY_ENV_RULES_JSON")
    policy_ai_autonomy_max_level: str = Field(default="", alias="POLICY_AI_AUTONOMY_MAX_LEVEL")
    policy_ai_autonomy_enforcement_enabled: bool = Field(default=False, alias="POLICY_AI_AUTONOMY_ENFORCEMENT_ENABLED")
    policy_intelligence_model: str = Field(default="claude-sonnet-4-20250514")
    approval_required_count: int = Field(default=1, alias="APPROVAL_REQUIRED_COUNT")
    approval_four_eyes_enabled: bool = Field(default=False, alias="APPROVAL_FOUR_EYES_ENABLED")
    approval_signed_required: bool = Field(default=False, alias="APPROVAL_SIGNED_REQUIRED")
    approval_org_workflow_json: str = Field(default="{}", alias="APPROVAL_ORG_WORKFLOW_JSON")
    approval_repo_workflow_json: str = Field(default="{}", alias="APPROVAL_REPO_WORKFLOW_JSON")
    approval_env_workflow_json: str = Field(default="{}", alias="APPROVAL_ENV_WORKFLOW_JSON")
    approval_high_risk_threshold: int = Field(default=70, alias="APPROVAL_HIGH_RISK_THRESHOLD")
    approval_high_risk_required_count: int = Field(default=2, alias="APPROVAL_HIGH_RISK_REQUIRED_COUNT")
    enterprise_approval_enforcement_enabled: bool = Field(
        default=False, alias="ENTERPRISE_APPROVAL_ENFORCEMENT_ENABLED"
    )
    enterprise_approval_simulated: bool = Field(default=True, alias="ENTERPRISE_APPROVAL_SIMULATED")
    approval_signature_secret: str = Field(default="", alias="APPROVAL_SIGNATURE_SECRET")
    kubernetes_manifest_scan_enabled: bool = Field(default=True, alias="KUBERNETES_MANIFEST_SCAN_ENABLED")
    cloud_deploy_target: str = Field(default="", alias="CLOUD_DEPLOY_TARGET")
    cloud_target_json: str = Field(default="{}", alias="CLOUD_TARGET_JSON")
    cloud_intelligence_gate_enabled: bool = Field(default=False, alias="CLOUD_INTELLIGENCE_GATE_ENABLED")
    cloud_intelligence_model: str = Field(default="claude-sonnet-4-20250514")
    service_catalog_scan_enabled: bool = Field(default=True, alias="SERVICE_CATALOG_SCAN_ENABLED")
    service_catalog_json: str = Field(default="{}", alias="SERVICE_CATALOG_JSON")
    idp_golden_paths_json: str = Field(default="{}", alias="IDP_GOLDEN_PATHS_JSON")
    service_catalog_gate_enabled: bool = Field(default=False, alias="SERVICE_CATALOG_GATE_ENABLED")
    service_catalog_min_completeness_percent: int = Field(default=60, alias="SERVICE_CATALOG_MIN_COMPLETENESS_PERCENT")
    service_catalog_intelligence_model: str = Field(default="claude-sonnet-4-20250514")
    require_signed_builds: bool = Field(default=False, alias="REQUIRE_SIGNED_BUILDS")
    tenant_isolation_mode: str = Field(default="org", alias="TENANT_ISOLATION_MODE")
    compliance_packs: str = Field(default="soc2,iso27001,owasp,cis", alias="COMPLIANCE_PACKS")
    finops_llm_cost_per_1k_tokens: float = Field(default=0.003, alias="FINOPS_LLM_COST_PER_1K_TOKENS")
    finops_compute_cost_per_minute: float = Field(default=0.008, alias="FINOPS_COMPUTE_COST_PER_MINUTE")
    finops_budget_usd_per_run: float = Field(default=5.0, alias="FINOPS_BUDGET_USD_PER_RUN")
    finops_budget_usd_monthly: float = Field(default=500.0, alias="FINOPS_BUDGET_USD_MONTHLY")
    finops_budget_json: str = Field(default="{}", alias="FINOPS_BUDGET_JSON")
    finops_gate_enabled: bool = Field(default=False, alias="FINOPS_GATE_ENABLED")
    release_max_risk_score: float = Field(default=60.0, alias="RELEASE_MAX_RISK_SCORE")
    release_prediction_block_threshold: float = Field(default=70.0, alias="RELEASE_PREDICTION_BLOCK_THRESHOLD")
    release_require_passport_pass: bool = Field(default=True, alias="RELEASE_REQUIRE_PASSPORT_PASS")
    release_policy_json: str = Field(default="{}", alias="RELEASE_POLICY_JSON")
    release_intelligence_gate_enabled: bool = Field(default=False, alias="RELEASE_INTELLIGENCE_GATE_ENABLED")
    sso_saml_entity_id: str = Field(default="", alias="SSO_SAML_ENTITY_ID")
    sso_saml_metadata_url: str = Field(default="", alias="SSO_SAML_METADATA_URL")
    sso_oidc_issuer: str = Field(default="", alias="SSO_OIDC_ISSUER")
    sso_oidc_client_id: str = Field(default="", alias="SSO_OIDC_CLIENT_ID")
    iam_policy_json: str = Field(default="{}", alias="IAM_POLICY_JSON")
    iam_gate_enabled: bool = Field(default=False, alias="IAM_GATE_ENABLED")
    iam_mfa_required: bool = Field(default=False, alias="IAM_MFA_REQUIRED")
    iam_min_readiness_score: float = Field(default=70.0, alias="IAM_MIN_READINESS_SCORE")
    iam_require_sso_in_production: bool = Field(default=False, alias="IAM_REQUIRE_SSO_IN_PRODUCTION")
    chaos_policy_json: str = Field(default="{}", alias="CHAOS_POLICY_JSON")
    chaos_simulated_default: bool = Field(default=True, alias="CHAOS_SIMULATED_DEFAULT")
    chaos_live_enabled: bool = Field(default=False, alias="CHAOS_LIVE_ENABLED")
    reliability_gate_enabled: bool = Field(default=False, alias="RELIABILITY_GATE_ENABLED")
    reliability_min_resilience_score: float = Field(default=70.0, alias="RELIABILITY_MIN_RESILIENCE_SCORE")
    reliability_require_synthetic_pass: bool = Field(default=False, alias="RELIABILITY_REQUIRE_SYNTHETIC_PASS")
    dr_policy_json: str = Field(default="{}", alias="DR_POLICY_JSON")
    dr_backup_dir: str = Field(default="", alias="DR_BACKUP_DIR")
    dr_gate_enabled: bool = Field(default=False, alias="DR_GATE_ENABLED")
    dr_rto_target_hours: float = Field(default=4.0, alias="DR_RTO_TARGET_HOURS")
    dr_rpo_target_hours: float = Field(default=24.0, alias="DR_RPO_TARGET_HOURS")
    dr_max_backup_age_hours: float = Field(default=24.0, alias="DR_MAX_BACKUP_AGE_HOURS")
    dr_backup_retention_count: int = Field(default=7, alias="DR_BACKUP_RETENTION_COUNT")
    dr_restore_drill_simulated: bool = Field(default=True, alias="DR_RESTORE_DRILL_SIMULATED")
    knowledge_graph_policy_json: str = Field(default="{}", alias="KNOWLEDGE_GRAPH_POLICY_JSON")
    knowledge_graph_gate_enabled: bool = Field(default=False, alias="KNOWLEDGE_GRAPH_GATE_ENABLED")
    knowledge_graph_min_nodes: int = Field(default=5, alias="KNOWLEDGE_GRAPH_MIN_NODES")
    knowledge_graph_min_coverage_percent: int = Field(default=40, alias="KNOWLEDGE_GRAPH_MIN_COVERAGE_PERCENT")
    knowledge_graph_require_service_graph: bool = Field(default=False, alias="KNOWLEDGE_GRAPH_REQUIRE_SERVICE_GRAPH")
    knowledge_graph_require_repository_intel: bool = Field(
        default=False, alias="KNOWLEDGE_GRAPH_REQUIRE_REPOSITORY_INTEL"
    )
    autopilot_enabled: bool = Field(default=True, alias="AUTOPILOT_ENABLED")
    autopilot_simulate_only: bool = Field(default=True, alias="AUTOPILOT_SIMULATE_ONLY")
    autopilot_gate_enabled: bool = Field(default=False, alias="AUTOPILOT_GATE_ENABLED")
    autopilot_policy_json: str = Field(default="{}", alias="AUTOPILOT_POLICY_JSON")
    autopilot_max_autonomy_level: str = Field(default="L4", alias="AUTOPILOT_MAX_AUTONOMY_LEVEL")
    autopilot_auto_pr_allowed: bool = Field(default=True, alias="AUTOPILOT_AUTO_PR_ALLOWED")
    autopilot_retry_allowed: bool = Field(default=False, alias="AUTOPILOT_RETRY_ALLOWED")
    autopilot_deploy_allowed: bool = Field(default=True, alias="AUTOPILOT_DEPLOY_ALLOWED")
    autopilot_require_approval_above_risk: float = Field(default=60.0, alias="AUTOPILOT_REQUIRE_APPROVAL_ABOVE_RISK")
    unified_risk_enabled: bool = Field(default=True, alias="UNIFIED_RISK_ENABLED")
    unified_risk_gate_enabled: bool = Field(default=False, alias="UNIFIED_RISK_GATE_ENABLED")
    unified_risk_max_score: float = Field(default=60.0, alias="UNIFIED_RISK_MAX_SCORE")
    unified_risk_block_on_high: bool = Field(default=False, alias="UNIFIED_RISK_BLOCK_ON_HIGH")
    unified_risk_require_gate_fusion_pass: bool = Field(default=True, alias="UNIFIED_RISK_REQUIRE_GATE_FUSION_PASS")
    unified_risk_policy_json: str = Field(default="{}", alias="UNIFIED_RISK_POLICY_JSON")
    prompt_injection_gate_enabled: bool = Field(default=True, alias="PROMPT_INJECTION_GATE_ENABLED")
    prompt_injection_max_diff_chars: int = Field(default=500_000, alias="PROMPT_INJECTION_MAX_DIFF_CHARS")
    prompt_injection_exclude_globs: str = Field(
        default=(
            "**/*_test.go,**/*_test.py,**/test_*.py,**/tests/**,"
            "**/prompt_injection*.go,**/*_ci_test.go,**/docs/**,"
            "**/production_slo.go,**/*self_check*"
        ),
        alias="PROMPT_INJECTION_EXCLUDE_GLOBS",
    )
    model_router_enabled: bool = Field(default=True, alias="MODEL_ROUTER_ENABLED")
    agent_eval_min_score: float = Field(default=0.6, alias="AGENT_EVAL_MIN_SCORE")
    agent_eval_gate_enabled: bool = Field(default=False, alias="AGENT_EVAL_GATE_ENABLED")
    patch_auto_pr_enforcement: bool = Field(default=True, alias="PATCH_AUTO_PR_ENFORCEMENT")
    devops_rag_max_chunks: int = Field(default=8, alias="DEVOPS_RAG_MAX_CHUNKS")
    agent_memory_enabled: bool = Field(default=True, alias="AGENT_MEMORY_ENABLED")
    agent_memory_sqlite_path: str = Field(default="", alias="AGENT_MEMORY_SQLITE_PATH")
    agent_memory_context_limit: int = Field(default=3, alias="AGENT_MEMORY_CONTEXT_LIMIT")
    agent_memory_max_entries_per_scope: int = Field(default=20, alias="AGENT_MEMORY_MAX_ENTRIES_PER_SCOPE")
    retriever_backend: str = Field(default="hybrid", alias="RETRIEVER_BACKEND")
    retriever_chunk_size: int = Field(default=800, alias="RETRIEVER_CHUNK_SIZE")
    rag_index_enabled: bool = Field(default=True, alias="RAG_INDEX_ENABLED")
    rag_index_max_files: int = Field(default=120, alias="RAG_INDEX_MAX_FILES")
    rag_index_max_file_bytes: int = Field(default=80_000, alias="RAG_INDEX_MAX_FILE_BYTES")
    devops_rag_model: str = Field(default="claude-sonnet-4-20250514", alias="DEVOPS_RAG_MODEL")
    agent_mesh_gate_enabled: bool = Field(default=False, alias="AGENT_MESH_GATE_ENABLED")
    agent_mesh_min_coverage_percent: float = Field(default=40.0, alias="AGENT_MESH_MIN_COVERAGE_PERCENT")
    agent_mesh_overrides_json: str = Field(default="{}", alias="AGENT_MESH_OVERRIDES_JSON")
    ai_governance_gate_enabled: bool = Field(default=False, alias="AI_GOVERNANCE_GATE_ENABLED")
    ai_governance_min_confidence: float = Field(default=0.70, alias="AI_GOVERNANCE_MIN_CONFIDENCE")
    ai_governance_escalation_threshold: float = Field(default=0.70, alias="AI_GOVERNANCE_ESCALATION_THRESHOLD")
    ai_governance_min_score: float = Field(default=0.55, alias="AI_GOVERNANCE_MIN_SCORE")
    ai_governance_policy_json: str = Field(default="{}", alias="AI_GOVERNANCE_POLICY_JSON")
    small_model_slug: str = Field(default="claude-haiku-3-20250325", alias="SMALL_MODEL_SLUG")
    api_require_auth: bool = Field(default=False)
    # Optional automation key (X-ORION-API-Key header) when API_REQUIRE_AUTH is enabled.
    orion_api_key: str = Field(default="")
    auth_api_keys_json: str = Field(default="{}", alias="AUTH_API_KEYS_JSON")
    rate_limit_requests: int = Field(default=60, alias="RATE_LIMIT_REQUESTS")
    rate_limit_window_seconds: int = Field(default=60, alias="RATE_LIMIT_WINDOW_SECONDS")
    sql_echo: bool = Field(default=False)
    journald_enabled: bool = Field(default=True)
    model_device_mode: str = Field(default="cpu")
    orchestrator_model: str = Field(default="claude-sonnet-4-20250514")
    code_analysis_model: str = Field(default="claude-sonnet-4-20250514")
    security_model: str = Field(default="claude-sonnet-4-20250514")
    qa_model: str = Field(default="claude-sonnet-4-20250514")
    stress_model: str = Field(default="claude-sonnet-4-20250514")
    approval_model: str = Field(default="claude-sonnet-4-20250514")
    deployment_model: str = Field(default="claude-sonnet-4-20250514")
    monitoring_model: str = Field(default="claude-sonnet-4-20250514")
    repository_intelligence_model: str = Field(default="claude-sonnet-4-20250514")
    security_gitleaks_enabled: bool = Field(default=True, alias="SECURITY_GITLEAKS_ENABLED")
    security_trivy_enabled: bool = Field(default=True, alias="SECURITY_TRIVY_ENABLED")
    security_checkov_enabled: bool = Field(default=True, alias="SECURITY_CHECKOV_ENABLED")
    security_semgrep_enabled: bool = Field(default=True, alias="SECURITY_SEMGREP_ENABLED")
    gitleaks_path: str = Field(default="", alias="GITLEAKS_PATH")
    trivy_path: str = Field(default="", alias="TRIVY_PATH")
    checkov_path: str = Field(default="", alias="CHECKOV_PATH")
    semgrep_path: str = Field(default="", alias="SEMGREP_PATH")
    sbom_syft_enabled: bool = Field(default=True, alias="SBOM_SYFT_ENABLED")
    syft_path: str = Field(default="", alias="SYFT_PATH")
    security_zap_enabled: bool = Field(default=True, alias="SECURITY_ZAP_ENABLED")
    zap_path: str = Field(default="", alias="ZAP_PATH")
    zap_timeout_seconds: int = Field(default=300, alias="ZAP_TIMEOUT_SECONDS")
    dast_gate_enabled: bool = Field(default=False, alias="DAST_GATE_ENABLED")
    epss_enabled: bool = Field(default=True, alias="EPSS_ENABLED")
    test_coverage_gate_enabled: bool = Field(default=False, alias="TEST_COVERAGE_GATE_ENABLED")
    test_coverage_min_percent: float = Field(default=50.0, alias="TEST_COVERAGE_MIN_PERCENT")
    test_coverage_max_regression_percent: float = Field(default=5.0, alias="TEST_COVERAGE_MAX_REGRESSION_PERCENT")
    test_coverage_probe_enabled: bool = Field(default=False, alias="TEST_COVERAGE_PROBE_ENABLED")
    test_coverage_probe_timeout_seconds: int = Field(default=120, alias="TEST_COVERAGE_PROBE_TIMEOUT_SECONDS")
    test_flaky_gate_enabled: bool = Field(default=False, alias="TEST_FLAKY_GATE_ENABLED")
    test_mutation_warn_threshold: int = Field(default=3, alias="TEST_MUTATION_WARN_THRESHOLD")
    test_intelligence_model: str = Field(default="claude-sonnet-4-20250514")
    multimodal_payment_model: str = Field(default="claude-sonnet-4-20250514")
    multimodal_git_model: str = Field(default="claude-sonnet-4-20250514")
    nginx_mode: str = Field(default="development")
    flower_basic_auth_user: str = Field(default="admin")
    flower_basic_auth_password: str = Field(default="orion_admin")
    production_local_sim: bool = Field(default=False, alias="PRODUCTION_LOCAL_SIM")

    @property
    def compliance_pack_list(self) -> list[str]:
        return [p.strip() for p in self.compliance_packs.split(",") if p.strip()]

    @property
    def prompt_injection_exclude_glob_list(self) -> list[str]:
        return [p.strip() for p in self.prompt_injection_exclude_globs.split(",") if p.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def use_secure_session_cookies(self) -> bool:
        """HTTPS-only / SameSite=None cookies — real production only, not local HTTP sim."""
        return self.is_production and not self.production_local_sim

    @property
    def database_url_sync(self) -> str:
        return self.sync_database_url

    @property
    def llm_enabled(self) -> bool:
        return not _is_placeholder(self.anthropic_api_key)

    @property
    def github_enabled(self) -> bool:
        return not _is_placeholder(self.github_token)

    @property
    def slack_enabled(self) -> bool:
        return not _is_placeholder(self.slack_webhook_url)

    @property
    def registry_enabled(self) -> bool:
        return not _is_placeholder(self.container_registry)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def orion_api_url(self) -> str:
        return f"http://{self.stack_host}:{self.app_port}"

    @property
    def orion_ui_url(self) -> str:
        base = self.frontend_url.rstrip("/")
        if base.endswith("/ui"):
            return f"{base}/"
        if "/ui/" in base:
            return base if base.endswith("/") else f"{base}/"
        return f"{self.orion_api_url}/ui/"

    @model_validator(mode="after")
    def _production_defaults(self) -> "Settings":
        if self.is_production and not self.api_require_auth:
            object.__setattr__(self, "api_require_auth", True)
        return self

    def validate_settings_integrity(self) -> list[str]:
        """Return missing optional enterprise fields (stale process / partial deploy detection)."""
        required = (
            "tenant_isolation_mode",
            "compliance_packs",
            "policy_enforcement_enabled",
            "agent_eval_min_score",
            "devops_rag_max_chunks",
            "model_router_enabled",
            "finops_llm_cost_per_1k_tokens",
            "slo_target_availability",
        )
        return [name for name in required if not hasattr(self, name)]

    def validate_startup(self) -> None:
        """Fail fast when production is misconfigured."""
        missing = self.validate_settings_integrity()
        if missing:
            raise RuntimeError(
                "Settings schema is incomplete (restart the API process after upgrading): "
                + ", ".join(missing)
            )
        if not self.is_production:
            return
        problems: list[str] = []
        if _is_placeholder(self.secret_key) or self.secret_key.startswith("orion-secret-key"):
            problems.append("SECRET_KEY must be set to a non-placeholder value in production.")
        if _is_placeholder(self.session_secret_key) or self.session_secret_key.startswith("orion-super-secret"):
            problems.append("SESSION_SECRET_KEY must be set to a non-placeholder value in production.")
        if _is_placeholder(self.github_webhook_secret):
            problems.append("GITHUB_WEBHOOK_SECRET must be set in production.")
        if "sqlite" in (self.database_url or "").lower() and not self.production_local_sim:
            problems.append("DATABASE_URL must use PostgreSQL in production (SQLite is dev-only).")
        has_keys = False
        raw_keys = (self.auth_api_keys_json or "").strip()
        if raw_keys and raw_keys != "{}":
            try:
                parsed = json.loads(raw_keys)
                has_keys = isinstance(parsed, dict) and bool(parsed)
            except ValueError:
                has_keys = False
        legacy_key = (self.orion_api_key or "").strip()
        if legacy_key and not _is_placeholder(legacy_key):
            has_keys = True
        if not has_keys:
            problems.append(
                "AUTH_API_KEYS_JSON or ORION_API_KEY must be configured in production."
            )
        if problems:
            raise RuntimeError(" ".join(problems))


def _github_oauth_ready(cfg: Settings) -> bool:
    cid = (cfg.github_client_id or "").strip()
    csec = (cfg.github_client_secret or "").strip()
    return bool(cid and csec and "your-oauth" not in cid.lower())


settings = Settings()
