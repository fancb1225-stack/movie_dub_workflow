import assert from "node:assert/strict";
import test from "node:test";

import { applyWorkflowEventToSteps, initialLanggraphSteps, workflowStepsTemplate } from "../src/composables/workflowSteps.js";

test("initialLanggraphSteps starts LangGraph at merge after ASR prerequisites", () => {
  const steps = initialLanggraphSteps(workflowStepsTemplate);

  assert.equal(steps.find((step) => step.key === "asr")?.kind, "done");
  assert.equal(steps.find((step) => step.key === "speakers")?.kind, "done");
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
