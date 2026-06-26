import { computed, ref, type Ref } from "vue";
import { listJobFiles, requestJson, streamEvents } from "../api/client";
import type { Job, StepState, VoiceOption, WorkflowEvent, WorkflowOverrides } from "../types/api";

const PREPROCESS_STEPS: StepState[] = [
  { key: "extract_audio", label: "音频提取", status: "等待", kind: "idle" },
  { key: "separate_audio", label: "人声/背景分离", status: "等待", kind: "idle" },
  { key: "background", label: "背景音提取", status: "等待", kind: "idle" }
];

const WORKFLOW_STEPS: StepState[] = [
  { key: "asr", label: "ASR", status: "等待", kind: "idle" },
  { key: "clean_srt", label: "清洗字幕", status: "等待", kind: "idle" },
  { key: "merge", label: "合并", status: "等待", kind: "idle" },
  { key: "critic", label: "校对", status: "等待", kind: "idle" },
  { key: "translate", label: "翻译", status: "等待", kind: "idle" },
  { key: "tts", label: "TTS", status: "等待", kind: "idle" },
  { key: "audio", label: "音频合成", status: "等待", kind: "idle" }
];

export const voiceOptions: VoiceOption[] = [
  { value: "Wise_Woman", label: "Wise Woman" },
  { value: "Friendly_Person", label: "Friendly Person" },
  { value: "Inspirational_girl", label: "Inspirational Girl" },
  { value: "Deep_Voice_Man", label: "Deep Voice Man" },
  { value: "Calm_Woman", label: "Calm Woman" },
  { value: "default", label: "Default" }
];

function cloneSteps(steps: StepState[]): StepState[] {
  return steps.map((step) => ({ ...step }));
}

export function useWorkflow(
  apiBase: Ref<string>,
  job: Ref<Job | null>,
  setOutput: (value: unknown) => void,
  setMessage: (text: string, kind?: "info" | "ok" | "error") => void,
  refreshJob: () => Promise<void>,
  refreshFiles: () => Promise<void>
) {
  const preprocessSteps = ref<StepState[]>(cloneSteps(PREPROCESS_STEPS));
  const workflowSteps = ref<StepState[]>(cloneSteps(WORKFLOW_STEPS));
  const logLines = ref<string[]>([]);
  const running = ref(false);
  const settingsOpen = ref(false);
  const settingsMode = ref<"run" | "resume">("run");
  const speakerProfiles = ref<Record<string, string>>({ default: "Wise_Woman" });
  const overrides = ref<WorkflowOverrides>({
    max_reflection_rounds: 2,
    llm_timeout: 600,
    llm_max_retries: 1,
    tts_rate: 1.3,
    tts_provider: "minimax",
    speaker_profiles: speakerProfiles.value
  });

  const canResume = computed(() => job.value?.status === "langgraph_paused" || job.value?.status === "langgraph_failed");

  function resetSteps(target: Ref<StepState[]>, source: StepState[]): void {
    target.value = cloneSteps(source);
  }

  function appendLog(text: string): void {
    const stamp = new Date().toLocaleTimeString();
    logLines.value = [`[${stamp}] ${text}`, ...logLines.value].slice(0, 160);
  }

  function updateStep(target: Ref<StepState[]>, event: WorkflowEvent): void {
    const key = String(event.node || event.event || "");
    if (!key) return;
    const index = target.value.findIndex((step) => key.includes(step.key) || step.key.includes(key));
    if (index < 0) return;
    const next = [...target.value];
    const kind = event.event === "error" || event.status === "error" ? "error" : event.event === "done" || event.status === "done" ? "done" : "running";
    next[index] = {
      ...next[index],
      kind,
      status: event.status || event.label || event.message || (kind === "done" ? "完成" : kind === "error" ? "失败" : "执行中")
    };
    if (kind === "done" && next[index + 1]?.kind === "idle") {
      next[index + 1] = { ...next[index + 1], kind: "running", status: "执行中" };
    }
    target.value = next;
  }

  function handleStreamEvent(target: Ref<StepState[]>, event: WorkflowEvent): void {
    if (event.job) {
      job.value = event.job;
    }
    if (event.error) {
      appendLog(event.error);
      setMessage(event.error, "error");
    } else {
      appendLog(event.message || event.label || event.event || "收到事件");
    }
    updateStep(target, event);
    setOutput(event);
  }

  async function runPreprocess(): Promise<void> {
    if (!job.value) return;
    running.value = true;
    resetSteps(preprocessSteps, PREPROCESS_STEPS);
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

  function openSettings(mode: "run" | "resume"): void {
    settingsMode.value = mode;
    settingsOpen.value = true;
  }

  function closeSettings(): void {
    settingsOpen.value = false;
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
    resetSteps(workflowSteps, WORKFLOW_STEPS);
    workflowSteps.value[0] = { ...workflowSteps.value[0], kind: "running", status: "执行中" };
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
      speakerProfiles.value = { default: "Wise_Woman" };
      return;
    }
    const candidates = [job.value.asr_result?.speakers, job.value.extra?.asr_result?.speakers];
    const found = candidates.find((value): value is string[] => Array.isArray(value) && value.length > 0);
    if (found) {
      speakerProfiles.value = Object.fromEntries(found.map((speaker) => [speaker, speakerProfiles.value[speaker] || "Wise_Woman"]));
      return;
    }
    try {
      const fileData = await listJobFiles(apiBase.value, job.value.job_id);
      const paths = new Set(fileData.files.map((file) => file.relative_path));
      const candidatePath = ["workflow/asr/zh_raw.words.json", "workflow/asr/zh_raw.cues.json", "workflow/merged/zh_asr_merged.cues.json"].find((path) => paths.has(path));
      if (!candidatePath) throw new Error("No speaker file");
      const rows = await requestJson<Array<{ speaker_id?: string }>>(apiBase.value, `/api/jobs/${job.value.job_id}/files/download?path=${encodeURIComponent(candidatePath)}`);
      const speakers = Array.from(new Set(rows.map((row) => row.speaker_id).filter(Boolean))) as string[];
      speakerProfiles.value = Object.fromEntries((speakers.length ? speakers : ["default"]).map((speaker) => [speaker, speakerProfiles.value[speaker] || "Wise_Woman"]));
    } catch {
      speakerProfiles.value = { default: speakerProfiles.value.default || "Wise_Woman" };
    }
  }

  return {
    preprocessSteps,
    workflowSteps,
    logLines,
    running,
    settingsOpen,
    settingsMode,
    speakerProfiles,
    overrides,
    canResume,
    voiceOptions,
    runPreprocess,
    openSettings,
    closeSettings,
    submitSettings,
    loadSpeakerProfiles
  };
}
