import assert from "node:assert/strict";
import test from "node:test";

import { buildSpeakerProfilesWithDefault, isWorkflowResumable } from "../src/composables/useWorkflow.js";
import type { Job } from "../src/types/api.js";

function job(status: string, overrides: Partial<Job> = {}): Job {
  return {
    job_id: "job-1",
    status,
    ...overrides
  };
}

test("isWorkflowResumable rejects missing jobs", () => {
  assert.equal(isWorkflowResumable(null), false);
  assert.equal(isWorkflowResumable(undefined), false);
});

test("isWorkflowResumable accepts explicit LangGraph resumable states", () => {
  assert.equal(isWorkflowResumable(job("langgraph_paused")), true);
  assert.equal(isWorkflowResumable(job("langgraph_failed")), true);
});

test("isWorkflowResumable accepts generic failed jobs with LangGraph evidence", () => {
  assert.equal(
    isWorkflowResumable(job("failed", { extra: { langgraph_workflow_report: { status: "failed" } } })),
    true
  );
  assert.equal(
    isWorkflowResumable(job("failed", { extra: { langgraph_progress: { node: "translate_to_english", status: "done" } } })),
    true
  );
  assert.equal(
    isWorkflowResumable(job("failed", { reports: { langgraph_workflow_report: "reports/langgraph_workflow_report.json" } })),
    true
  );
});

test("isWorkflowResumable rejects non-LangGraph failed jobs", () => {
  assert.equal(isWorkflowResumable(job("failed")), false);
  assert.equal(isWorkflowResumable(job("failed", { extra: { asr_result: { speakers: ["speaker_1"] } } })), false);
});

test("isWorkflowResumable rejects non-resumable workflow states", () => {
  for (const status of ["created", "preprocessed", "asr_completed", "langgraph_running", "langgraph_completed"]) {
    assert.equal(isWorkflowResumable(job(status)), false, status);
  }
});

test("buildSpeakerProfilesWithDefault always includes default voice", () => {
  assert.deepEqual(buildSpeakerProfilesWithDefault(["speaker_1", "speaker_2"], {}), {
    speaker_1: "Wise_Woman",
    speaker_2: "Wise_Woman",
    default: "Wise_Woman"
  });
});

test("buildSpeakerProfilesWithDefault preserves existing speaker and default choices", () => {
  assert.deepEqual(
    buildSpeakerProfilesWithDefault(["speaker_1", "speaker_2"], {
      speaker_1: "Deep_Voice_Man",
      default: "Calm_Woman"
    }),
    {
      speaker_1: "Deep_Voice_Man",
      speaker_2: "Wise_Woman",
      default: "Calm_Woman"
    }
  );
});
