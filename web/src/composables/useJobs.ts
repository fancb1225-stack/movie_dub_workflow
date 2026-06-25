import { computed, ref } from "vue";
import {
  artifactsDownloadUrl,
  createJob,
  getJob,
  jobFileDownloadUrl,
  listJobFiles,
  listJobs,
  packageVideo,
  requestJson
} from "../api/client";
import type { Job, JobFile, MessageKind } from "../types/api";

const API_BASE_KEY = "movie-dub-api-base";

export function useJobs() {
  const apiBase = ref(localStorage.getItem(API_BASE_KEY) || "");
  const health = ref("未检查");
  const message = ref("就绪");
  const messageKind = ref<MessageKind>("info");
  const output = ref<unknown>({});
  const job = ref<Job | null>(null);
  const jobs = ref<Job[]>([]);
  const files = ref<JobFile[]>([]);
  const busy = ref(false);

  const hasJob = computed(() => Boolean(job.value?.job_id));
  const hasArtifacts = computed(() => Boolean(job.value?.artifacts && Object.keys(job.value.artifacts).length));

  function setApiBase(value: string): void {
    apiBase.value = value;
    localStorage.setItem(API_BASE_KEY, value);
  }

  function setMessage(text: string, kind: MessageKind = "info"): void {
    message.value = text;
    messageKind.value = kind;
  }

  function setOutput(value: unknown): void {
    output.value = value;
  }

  async function checkHealth(): Promise<void> {
    const data = await requestJson<{ status: string }>(apiBase.value, "/health");
    health.value = data.status;
    setMessage("API 连接正常", "ok");
    setOutput(data);
  }

  async function upload(file: File, videoType: string): Promise<void> {
    busy.value = true;
    try {
      const data = await createJob(apiBase.value, file, videoType);
      job.value = data;
      setMessage("任务已创建", "ok");
      setOutput(data);
      await refreshFiles();
    } finally {
      busy.value = false;
    }
  }

  async function refreshJob(showMessage = false): Promise<void> {
    if (!job.value) return;
    const data = await getJob(apiBase.value, job.value.job_id);
    job.value = data;
    setOutput(data);
    if (showMessage) setMessage("任务状态已刷新", "ok");
  }

  async function refreshFiles(showMessage = false): Promise<void> {
    if (!job.value) return;
    const data = await listJobFiles(apiBase.value, job.value.job_id);
    files.value = data.files || [];
    if (showMessage) setMessage("文件列表已刷新", "ok");
  }

  async function loadJobs(): Promise<void> {
    const data = await listJobs(apiBase.value);
    jobs.value = data.jobs || [];
  }

  async function openJob(jobId: string): Promise<void> {
    const data = await getJob(apiBase.value, jobId);
    job.value = data;
    setOutput(data);
    setMessage("已打开历史任务", "ok");
    await refreshFiles();
  }

  async function runOperation(label: string, path: string, method = "POST"): Promise<void> {
    if (!job.value) return;
    busy.value = true;
    try {
      const data = await requestJson(apiBase.value, `/api/jobs/${job.value.job_id}${path}`, { method });
      setOutput(data);
      setMessage(`${label}完成`, "ok");
      await refreshJob();
      await refreshFiles();
    } finally {
      busy.value = false;
    }
  }

  async function openWorkdir(): Promise<void> {
    if (!job.value) return;
    const data = await requestJson(apiBase.value, `/api/jobs/${job.value.job_id}/open-workdir`, { method: "POST" });
    setOutput(data);
    setMessage("工作目录已打开", "ok");
  }

  async function packageCurrentVideo(outputFilename: string, audioFile?: File | null): Promise<void> {
    if (!job.value) return;
    busy.value = true;
    try {
      const data = await packageVideo(apiBase.value, job.value.job_id, outputFilename, audioFile);
      setOutput(data);
      setMessage("视频封装完成", "ok");
      await refreshJob();
      await refreshFiles();
    } finally {
      busy.value = false;
    }
  }

  function downloadFile(relativePath: string): void {
    if (!job.value) return;
    window.open(jobFileDownloadUrl(apiBase.value, job.value.job_id, relativePath), "_blank");
  }

  function downloadArtifacts(): void {
    if (!job.value) return;
    window.open(artifactsDownloadUrl(apiBase.value, job.value.job_id), "_blank");
  }

  function clearOutput(): void {
    output.value = {};
    setMessage("输出已清空");
  }

  return {
    apiBase,
    health,
    message,
    messageKind,
    output,
    job,
    jobs,
    files,
    busy,
    hasJob,
    hasArtifacts,
    setApiBase,
    setMessage,
    setOutput,
    checkHealth,
    upload,
    refreshJob,
    refreshFiles,
    loadJobs,
    openJob,
    runOperation,
    openWorkdir,
    packageCurrentVideo,
    downloadFile,
    downloadArtifacts,
    clearOutput
  };
}
