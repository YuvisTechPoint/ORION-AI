import axios from "axios";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8002";
const API_KEY =
  import.meta.env.VITE_ORION_API_KEY ||
  import.meta.env.VITE_DEPLOYMENT_API_KEY ||
  "";

export const api = axios.create({
  baseURL: API,
  headers: {
    "Content-Type": "application/json",
    ...(API_KEY ? { "X-ORION-API-Key": API_KEY } : {}),
  },
  timeout: 120000,
});

export type TriggerResponse = {
  pipeline_id: string;
  status: string;
};

export async function triggerPipeline(repoUrl: string, deploymentApiKey?: string) {
  const { data } = await api.post<TriggerResponse>("/api/pipeline/trigger", {
    repo_url: repoUrl,
    deployment_api_key: deploymentApiKey || undefined,
  });
  return {
    pipeline_id: String(data.pipeline_id),
    status: String(data.status),
  };
}

export async function getPipelineStatus(id: string) {
  const { data } = await api.get(`/api/pipeline/${id}/status`);
  return data;
}

export async function getPipeline(id: string) {
  const { data } = await api.get(`/api/pipeline/${id}`);
  return data;
}

export async function analyzeLogs(pipelineId: string, logText: string) {
  const { data } = await api.post(`/api/pipeline/${pipelineId}/logs/analyze`, { log_text: logText });
  return data;
}

export async function getHealth() {
  const { data } = await api.get("/health");
  return data;
}

export async function listPipelines() {
  const { data } = await api.get("/api/pipelines");
  return data;
}

export async function cancelPipeline(id: string) {
  const { data } = await api.post(`/api/pipeline/${id}/cancel`);
  return data;
}

export async function triggerDeploy(pipelineId: string, apiKey: string) {
  const { data } = await api.post(
    `/api/pipeline/${pipelineId}/deploy`,
    {},
    { headers: { "X-Deployment-Key": apiKey } },
  );
  return data;
}

export async function retryPipeline(id: string) {
  const { data } = await api.post(`/api/pipeline/${id}/retry`);
  return data;
}

export async function textAnalyze(text: string, operations: string[] = ["classify_log", "sanitize"]) {
  const { data } = await api.post("/api/tools/text-analyze", { text, operations });
  return data;
}
