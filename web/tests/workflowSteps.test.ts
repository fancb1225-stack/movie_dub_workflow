import assert from "node:assert/strict";
import test from "node:test";

import { applyWorkflowEventToSteps, initialLanggraphSteps, workflowStepsTemplate } from "../src/composables/workflowSteps.js";

test("initialLanggraphSteps starts LangGraph at merge after ASR prerequisites", () => {
  const steps = initialLanggraphSteps(workflowStepsTemplate);

  assert.equal(steps.find((step) => step.key === "asr")?.kind, "done");
  assert.equal(steps.find((step) => step.key === "speakers"), undefined);
  assert.equal(steps.find((step) => step.key === "merge")?.kind, "running");
});

test("applyWorkflowEventToSteps marks TTS node failed with error message", () => {
  const steps = initialLanggraphSteps(workflowStepsTemplate);
  const updated = applyWorkflowEventToSteps(steps, {
    event: "error",
    node: "tts_generate_and_detect",
    status: "error",
    message: "MiniMax TTS task timeout: task_id=task-1"
  });
  const tts = updated.find((step) => step.key === "tts");

  assert.equal(tts?.kind, "error");
  assert.equal(tts?.status, "MiniMax TTS task timeout: task_id=task-1");
});

test("applyWorkflowEventToSteps maps reflection LLM error to TTS instead of running audio", () => {
  let steps = initialLanggraphSteps(workflowStepsTemplate);

  for (const node of [
    "merge_zh_asr_srt",
    "clean_srt",
    "critic_srt",
    "translate_to_english",
    "tts_generate_and_detect"
  ]) {
    steps = applyWorkflowEventToSteps(steps, {
      event: "progress",
      node,
      status: "done"
    });
  }

  assert.equal(steps.find((step) => step.key === "audio")?.kind, "running");

  const updated = applyWorkflowEventToSteps(steps, {
    event: "error",
    node: "reflect_duration_issues",
    status: "error",
    message: "LLM request failed: The read operation timed out"
  });

  const tts = updated.find((step) => step.key === "tts");
  const audio = updated.find((step) => step.key === "audio");

  assert.equal(tts?.kind, "error");
  assert.equal(tts?.status, "LLM request failed: The read operation timed out");
  assert.notEqual(audio?.kind, "error");
});
