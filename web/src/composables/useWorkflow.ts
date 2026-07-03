import { computed, ref, type Ref } from "vue";
import { listJobFiles, listTtsVoices, requestJson, streamEvents } from "../api/client";
import type { AsrRunOptions, AsrSettingsResponse, Job, StepState, VoiceOption, WorkflowEvent, WorkflowOverrides } from "../types/api";
import {
  applyWorkflowEventToSteps,
  cloneSteps,
  initialLanggraphSteps,
  preprocessStepsTemplate,
  workflowStepsTemplate
} from "./workflowSteps";

const DEFAULT_VOICE_OPTIONS: VoiceOption[] = [
  { voice_id: "zh_female_popo_mars_bigtts", label: "婆婆", original_label: "Popo", language: "中文" },
  { voice_id: "multi_female_maomao_conversation_wvae_bigtts", label: "Diana", original_label: "Diana", language: "多语种" },
  { voice_id: "Wise_Woman", label: "智慧女声", original_label: "Wise Woman", language: "英文" },
  { voice_id: "Friendly_Person", label: "友好人物", original_label: "Friendly Person", language: "英文" },
  { voice_id: "Inspirational_girl", label: "励志女孩", original_label: "Inspirational Girl", language: "英文" },
  { voice_id: "Deep_Voice_Man", label: "低沉男声", original_label: "Deep Voice Man", language: "英文" },
  { voice_id: "Calm_Woman", label: "沉稳女声", original_label: "Calm Woman", language: "英文" },
  { voice_id: "default", label: "默认音色", original_label: "Default", language: "默认" }
];

export function isWorkflowResumable(job: Job | null | undefined): boolean {
  if (!job) return false;
  if (job.status === "langgraph_paused" || job.status === "langgraph_failed") return true;
  if (job.status !== "failed") return false;
  return Boolean(
    job.extra?.langgraph_workflow_report ||
      job.extra?.langgraph_progress ||
      job.reports?.langgraph_workflow_report
  );
}

export function buildSpeakerProfilesWithDefault(
  speakers: string[],
  existingProfiles: Record<string, string>,
  defaultVoice = "zh_female_popo_mars_bigtts"
): Record<string, string> {
  const keys = Array.from(new Set([...speakers.filter(Boolean), "default"]));
  return Object.fromEntries(keys.map((speaker) => [speaker, existingProfiles[speaker] || defaultVoice]));
}

export function compactAsrOptions(options: AsrRunOptions): AsrRunOptions {
  const compact: AsrRunOptions = {};
  if (options.language?.trim()) compact.language = options.language.trim();
  for (const key of ["enable_punc", "enable_itn", "enable_ddc", "enable_speaker_info"] as const) {
    if (options[key] !== undefined) compact[key] = options[key];
  }
  if (options.max_query_attempts !== undefined) compact.max_query_attempts = options.max_query_attempts;
  if (options.poll_interval_seconds !== undefined) compact.poll_interval_seconds = options.poll_interval_seconds;
  return compact;
}

export function useWorkflow(
  apiBase: Ref<string>,
  job: Ref<Job | null>,
  setOutput: (value: unknown) => void,
  setMessage: (text: string, kind?: "info" | "ok" | "error") => void,
  refreshJob: () => Promise<void>,
  refreshFiles: () => Promise<void>
) {
  const preprocessSteps = ref<StepState[]>(cloneSteps(preprocessStepsTemplate));
  const workflowSteps = ref<StepState[]>(cloneSteps(workflowStepsTemplate));
  const logLines = ref<string[]>([]);
  const voiceOptions = ref<VoiceOption[]>(DEFAULT_VOICE_OPTIONS);
  const running = ref(false);
  const operationStartedAt = ref<number | null>(null);
  const settingsOpen = ref(false);
  const asrSettingsOpen = ref(false);
  const asrSettings = ref<AsrSettingsResponse | null>(null);
  const settingsMode = ref<"run" | "resume">("run");
  const speakerProfiles = ref<Record<string, string>>({ default: "zh_female_popo_mars_bigtts" });
  const overrides = ref<WorkflowOverrides>({
    max_reflection_rounds: 2,
    llm_timeout: 600,
    llm_max_retries: 1,
    tts_rate: 1.3,
    tts_provider: "doubao",
    speaker_profiles: speakerProfiles.value
  });

  const canResume = computed(() => isWorkflowResumable(job.value));

  function resetSteps(target: Ref<StepState[]>, source: StepState[]): void {
    target.value = cloneSteps(source);
  }

  function appendLog(text: string): void {
    const stamp = new Date().toLocaleTimeString();
    const elapsed = operationStartedAt.value === null ? "" : ` +${formatElapsed(Date.now() - operationStartedAt.value)}`;
    logLines.value = [`[${stamp}${elapsed}] ${text}`, ...logLines.value].slice(0, 160);
  }

  function startTiming(): void {
    operationStartedAt.value = Date.now();
  }

  function formatElapsed(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    const seconds = ms / 1000;
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const minutes = Math.floor(seconds / 60);
    const rest = Math.round(seconds % 60).toString().padStart(2, "0");
    return `${minutes}m${rest}s`;
  }

  function clearLog(): void {
    logLines.value = [];
  }

  function updateStep(target: Ref<StepState[]>, event: WorkflowEvent): void {
    target.value = applyWorkflowEventToSteps(target.value, event);
  }

  function eventErrorMessage(event: WorkflowEvent): string {
    if (event.error) return String(event.error);
    const report = event.report;
    if (typeof report === "object" && report && "error" in report) {
      return String((report as { error?: unknown }).error || "流程执行失败");
    }
    return event.event === "error" ? "流程执行失败" : "";
  }

  function markActiveStepError(target: Ref<StepState[]>, message: string): void {
    const next = [...target.value];
    let index = next.findIndex((step) => step.kind === "running");
    if (index < 0 && /tts|语音|合成|timeout|超时/i.test(message)) {
      index = next.findIndex((step) => step.key === "tts");
    }
    if (index < 0) return;
    next[index] = { ...next[index], kind: "error", status: message || "失败" };
    target.value = next;
  }

  function handleStreamEvent(target: Ref<StepState[]>, event: WorkflowEvent): void {
    if (event.job) {
      job.value = event.job;
    }
    const errorMessage = eventErrorMessage(event);
    if (errorMessage) {
      appendLog(errorMessage);
      setMessage(errorMessage, "error");
      updateStep(target, event);
      markActiveStepError(target, errorMessage);
      setOutput(event);
      throw new Error(errorMessage);
    }
    appendLog(event.message || event.label || event.event || "收到事件");
    updateStep(target, event);
    setOutput(event);
  }

  async function runPreprocess(): Promise<void> {
    if (!job.value) return;
    running.value = true;
    resetSteps(preprocessSteps, preprocessStepsTemplate);
    startTiming();
    preprocessSteps.value[0] = { ...preprocessSteps.value[0], kind: "running", status: "执行中" };
    try {
      await streamEvents(apiBase.value, `/api/jobs/${job.value.job_id}/preprocess/stream`, { method: "POST" }, (event) => {
        handleStreamEvent(preprocessSteps, event);
      });
      preprocessSteps.value = preprocessSteps.value.map((step) => ({ ...step, kind: step.kind === "error" ? "error" : "done", status: step.kind === "error" ? step.status : "完成" }));
      setMessage("预处理完成", "ok");
      await refreshJob();
      await refreshFiles();
    } finally {
      running.value = false;
    }
  }

  async function runAsr(options: AsrRunOptions = {}): Promise<void> {
    if (!job.value) return;
    running.value = true;
    startTiming();
    const index = workflowSteps.value.findIndex((step) => step.key === "asr");
    if (index >= 0) {
      const next = [...workflowSteps.value];
      next[index] = { ...next[index], kind: "running", status: "执行中" };
      workflowSteps.value = next;
    }
    try {
      const data = await requestJson<WorkflowEvent>(apiBase.value, `/api/jobs/${job.value.job_id}/asr`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asr: compactAsrOptions(options) })
      });
      const next = [...workflowSteps.value];
      const asrIndex = next.findIndex((step) => step.key === "asr");
      if (asrIndex >= 0) {
        next[asrIndex] = { ...next[asrIndex], kind: "done", status: "完成" };
        workflowSteps.value = next;
      }
      appendLog("ASR 语音识别完成");
      setMessage("ASR 语音识别完成", "ok");
      setOutput(data);
      await refreshJob();
      await refreshFiles();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const next = [...workflowSteps.value];
      const asrIndex = next.findIndex((step) => step.key === "asr");
      if (asrIndex >= 0) {
        next[asrIndex] = { ...next[asrIndex], kind: "error", status: "失败" };
        workflowSteps.value = next;
      }
      appendLog(message);
      throw error;
    } finally {
      running.value = false;
    }
  }

  function openSettings(mode: "run" | "resume"): void {
    settingsMode.value = mode;
    settingsOpen.value = true;
  }

  function closeSettings(): void {
    settingsOpen.value = false;
  }

  async function loadAsrSettings(): Promise<void> {
    const videoType = job.value?.video_type ? `?video_type=${encodeURIComponent(String(job.value.video_type))}` : "";
    asrSettings.value = await requestJson<AsrSettingsResponse>(apiBase.value, `/api/asr/settings${videoType}`);
  }

  async function openAsrSettings(): Promise<void> {
    await loadAsrSettings();
    asrSettingsOpen.value = true;
  }

  function closeAsrSettings(): void {
    asrSettingsOpen.value = false;
  }

  async function submitAsrSettings(value: AsrRunOptions): Promise<void> {
    closeAsrSettings();
    await runAsr(value);
  }

  async function loadVoiceOptions(): Promise<void> {
    try {
      const data = await listTtsVoices(apiBase.value);
      if (data.voices.length) {
        voiceOptions.value = data.voices;
      }
    } catch (error) {
      appendLog(`音色列表加载失败，使用本地兜底列表：${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function submitSettings(value: WorkflowOverrides): Promise<void> {
    overrides.value = value;
    speakerProfiles.value = value.speaker_profiles;
    closeSettings();
    if (settingsMode.value === "resume") {
      await runLanggraph(true);
    } else {
      await runLanggraph(false);
    }
  }

  async function runLanggraph(isResume: boolean): Promise<void> {
    if (!job.value) return;
    running.value = true;
    workflowSteps.value = initialLanggraphSteps(workflowStepsTemplate);
    const params = new URLSearchParams({
      max_reflection_rounds: String(overrides.value.max_reflection_rounds),
      llm_timeout: String(overrides.value.llm_timeout),
      llm_max_retries: String(overrides.value.llm_max_retries),
      tts_rate: String(overrides.value.tts_rate)
    });
    const body = JSON.stringify({
      tts_provider: overrides.value.tts_provider,
      speaker_profiles: overrides.value.speaker_profiles,
      profiles_confirmed: true
    });
    const path = `/api/jobs/${job.value.job_id}/workflow/langgraph/${isResume ? "resume/" : ""}stream?${params.toString()}`;
    try {
      await streamEvents(
        apiBase.value,
        path,
        { method: "POST", headers: { "Content-Type": "application/json" }, body },
        (event) => handleStreamEvent(workflowSteps, event)
      );
      workflowSteps.value = workflowSteps.value.map((step) => ({ ...step, kind: step.kind === "error" ? "error" : "done", status: step.kind === "error" ? step.status : "完成" }));
      setMessage(isResume ? "工作流恢复完成" : "工作流完成", "ok");
      await refreshJob();
      await refreshFiles();
    } finally {
      running.value = false;
    }
  }

  async function loadSpeakerProfiles(): Promise<void> {
    if (!job.value) {
      speakerProfiles.value = { default: "zh_female_popo_mars_bigtts" };
      return;
    }
    const candidates = [job.value.asr_result?.speakers, job.value.extra?.asr_result?.speakers];
    const found = candidates.find((value): value is string[] => Array.isArray(value) && value.length > 0);
    if (found) {
      speakerProfiles.value = buildSpeakerProfilesWithDefault(found, speakerProfiles.value);
      return;
    }
    try {
      const fileData = await listJobFiles(apiBase.value, job.value.job_id);
      const paths = new Set(fileData.files.map((file) => file.relative_path));
      const candidatePath = ["workflow/asr/zh_raw.words.json", "workflow/asr/zh_raw.cues.json", "workflow/merged/zh_asr_merged.cues.json"].find((path) => paths.has(path));
      if (!candidatePath) throw new Error("No speaker file");
      const rows = await requestJson<Array<{ speaker_id?: string }>>(apiBase.value, `/api/jobs/${job.value.job_id}/files/download?path=${encodeURIComponent(candidatePath)}`);
      const speakers = Array.from(new Set(rows.map((row) => row.speaker_id).filter(Boolean))) as string[];
      speakerProfiles.value = buildSpeakerProfilesWithDefault(speakers.length ? speakers : [], speakerProfiles.value);
    } catch {
      speakerProfiles.value = { default: speakerProfiles.value.default || "zh_female_popo_mars_bigtts" };
    }
  }

  return {
    preprocessSteps,
    workflowSteps,
    logLines,
    running,
    settingsOpen,
    asrSettingsOpen,
    asrSettings,
    settingsMode,
    speakerProfiles,
    overrides,
    canResume,
    voiceOptions,
    runPreprocess,
    runAsr,
    clearLog,
    openSettings,
    closeSettings,
    openAsrSettings,
    closeAsrSettings,
    submitAsrSettings,
    submitSettings,
    loadSpeakerProfiles,
    loadVoiceOptions
  };
}
