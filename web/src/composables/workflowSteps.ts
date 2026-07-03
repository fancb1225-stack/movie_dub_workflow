import type { StepState, WorkflowEvent } from "../types/api.js";

export const preprocessStepsTemplate: StepState[] = [
  { key: "extract_audio", label: "音频提取", status: "等待", kind: "idle" },
  { key: "separate_audio", label: "人声/背景分离", status: "等待", kind: "idle" }
];

export const workflowStepsTemplate: StepState[] = [
  { key: "asr", label: "ASR", status: "等待", kind: "idle" },
  { key: "merge", label: "合并", status: "等待", kind: "idle" },
  { key: "clean_srt", label: "清洗字幕", status: "等待", kind: "idle" },
  { key: "critic", label: "校对", status: "等待", kind: "idle" },
  { key: "translate", label: "翻译", status: "等待", kind: "idle" },
  { key: "tts", label: "TTS", status: "等待", kind: "idle" },
  { key: "audio", label: "音频合成", status: "等待", kind: "idle" }
];

export function cloneSteps(steps: StepState[]): StepState[] {
  return steps.map((step) => ({ ...step }));
}

export function initialLanggraphSteps(steps: StepState[]): StepState[] {
  return steps.map((step) => {
    if (step.key === "asr") {
      return { ...step, kind: "done", status: "完成" };
    }
    if (step.key === "merge") {
      return { ...step, kind: "running", status: "执行中" };
    }
    return { ...step, kind: "idle", status: "等待" };
  });
}

export function applyWorkflowEventToSteps(steps: StepState[], event: WorkflowEvent): StepState[] {
  const index = resolveStepIndex(steps, event);
  if (index < 0) return steps;

  const next = cloneSteps(steps);
  const kind = event.event === "error" || event.status === "error"
    ? "error"
    : event.event === "done" || event.status === "done"
      ? "done"
      : "running";
  next[index] = {
    ...next[index],
    kind,
    status: stepStatus(kind, event)
  };
  if (kind === "done" && next[index + 1]?.kind === "idle") {
    next[index + 1] = { ...next[index + 1], kind: "running", status: "执行中" };
  }
  return next;
}

function resolveStepIndex(steps: StepState[], event: WorkflowEvent): number {
  const node = String(event.node || event.event || "");
  if (!node) return -1;
  const aliases: Record<string, string> = {
    asr_transcribe: "asr",
    merge_zh_asr_srt: "merge",
    restitch_merge_cuts: "merge",
    critic_srt: "critic",
    summarize_plot: "critic",
    translate_to_english: "translate",
    tts_generate_and_detect: "tts",
    reflect_duration_issues: "tts",
    align_and_merge_audio: "audio"
  };
  const normalized = aliases[node] || node;
  return steps.findIndex((step) => step.key === normalized || normalized.includes(step.key));
}

function stepStatus(kind: StepState["kind"], event: WorkflowEvent): string {
  if (kind === "error") {
    return String(event.message || event.error || "失败");
  }
  if (kind === "done") {
    return "完成";
  }
  return String(event.message || event.label || "执行中");
}
