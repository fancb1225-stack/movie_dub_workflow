import assert from "node:assert/strict";
import test from "node:test";

import { initialLanggraphSteps, workflowStepsTemplate } from "../src/composables/workflowSteps.js";

test("initialLanggraphSteps starts LangGraph at merge after ASR prerequisites", () => {
  const steps = initialLanggraphSteps(workflowStepsTemplate);

  assert.equal(steps.find((step) => step.key === "asr")?.kind, "done");
  assert.equal(steps.find((step) => step.key === "speakers")?.kind, "done");
  assert.equal(steps.find((step) => step.key === "merge")?.kind, "running");
});
