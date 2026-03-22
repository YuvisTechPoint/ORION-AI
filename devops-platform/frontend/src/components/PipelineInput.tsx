type Props = {
  repo: string;
  repoUrl: string;
  loading: boolean;
  onRepoChange: (v: string) => void;
  onRepoUrlChange: (v: string) => void;
  onSubmit: () => void;
};

export default function PipelineInput({
  repo,
  repoUrl,
  loading,
  onRepoChange,
  onRepoUrlChange,
  onSubmit,
}: Props) {
  return (
    <div className="card" style={{ padding: "1.5rem" }}>
      {/* Card header */}
      <div className="card-header">
        <div className="card-header-icon">🚀</div>
        <div>
          <h2 className="card-title">Pipeline Input</h2>
          <p style={{ fontSize: "0.7rem", color: "#9a8878", marginTop: "1px" }}>
            Trigger a new AI pipeline run
          </p>
        </div>
      </div>

      {/* Repository name field */}
      <div style={{ marginBottom: "1rem" }}>
        <label className="form-label" htmlFor="repo-name">
          Repository Name
        </label>
        <input
          id="repo-name"
          className="input-field"
          placeholder="payment-service"
          value={repo}
          onChange={(e) => onRepoChange(e.target.value)}
        />
      </div>

      {/* GitHub URL field */}
      <div style={{ marginBottom: "1.25rem" }}>
        <label className="form-label" htmlFor="github-url">
          GitHub URL
        </label>
        <div style={{ position: "relative" }}>
          <div style={{
            position: "absolute", left: "0.75rem", top: "50%", transform: "translateY(-50%)",
            color: "#b0a090",
          }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/>
            </svg>
          </div>
          <input
            id="github-url"
            className="input-field"
            style={{ paddingLeft: "2.25rem" }}
            placeholder="https://github.com/owner/repo"
            value={repoUrl}
            onChange={(e) => onRepoUrlChange(e.target.value)}
          />
        </div>
        <p style={{ fontSize: "0.68rem", color: "#b0a090", marginTop: "0.375rem" }}>
          GitHub URL takes priority. Up to 20 source files will be fetched for analysis.
        </p>
      </div>

      {/* Submit button */}
      <button
        id="trigger-pipeline-btn"
        type="button"
        disabled={loading}
        onClick={onSubmit}
        className="btn-primary"
        style={{ width: "100%", justifyContent: "center", padding: "0.75rem" }}
      >
        {loading ? (
          <>
            <div className="spinner" />
            Fetching &amp; Launching Pipeline…
          </>
        ) : (
          <>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polygon points="5 3 19 12 5 21 5 3"/>
            </svg>
            Fetch GitHub Repo &amp; Run
          </>
        )}
      </button>

      {/* Info note */}
      <div style={{
        marginTop: "1rem",
        padding: "0.625rem 0.875rem",
        background: "rgba(232, 131, 42, 0.06)",
        borderRadius: "8px",
        border: "1px solid rgba(232, 131, 42, 0.15)",
        display: "flex",
        alignItems: "flex-start",
        gap: "0.5rem",
      }}>
        <svg style={{ color: "#E8832A", flexShrink: 0, marginTop: "1px" }} width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
          <circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01" stroke="white" strokeWidth="2" strokeLinecap="round"/>
        </svg>
        <p style={{ fontSize: "0.7rem", color: "#7a6b5a", lineHeight: 1.5 }}>
          6 AI agents will run sequentially: Code Analysis → Security → QA → Stress → Deployment → Monitoring
        </p>
      </div>
    </div>
  );
}
