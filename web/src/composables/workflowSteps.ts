import type { StepState } from "../types/api.js";

export const preprocessStepsTemplate: StepState[] = [
  { key: "extract_audio", label: "音频提取", status: "等待", kind: "idle" },
  { key: "separate_audio", label: "人声/背景分离", status: "等待", kind: "idle" }
];

export const workflowStepsTemplate: StepState[] = [
  { key: "asr", label: "ASR", status: "等待", kind: "idle" },
  { key: "speakers", label: "说话人识别", status: "等待", kind: "idle" },
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
    if (step.key === "asr" || step.key === "speakers") {
      return { ...step, kind: "done", status: "完成" };
    }
    if (step.key === "merge") {
      return { ...step, kind: "running", status: "执行中" };
    }
    return { ...step, kind: "idle", status: "等待" };
  });
}
