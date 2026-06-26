<script setup lang="ts">
import AppHeader from "./components/AppHeader.vue";
import JobPickerModal from "./components/JobPickerModal.vue";
import JobSummary from "./components/JobSummary.vue";
import OperationPanel from "./components/OperationPanel.vue";
import OutputPanel from "./components/OutputPanel.vue";
import UploadPanel from "./components/UploadPanel.vue";
import WorkflowPanel from "./components/WorkflowPanel.vue";
import WorkflowSettingsModal from "./components/WorkflowSettingsModal.vue";
import { useJobs } from "./composables/useJobs";
import { useWorkflow } from "./composables/useWorkflow";
import type { WorkflowOverrides } from "./types/api";
import { ref } from "vue";

const jobs = useJobs();
const workflow = useWorkflow(
  jobs.apiBase,
  jobs.job,
  jobs.setOutput,
  jobs.setMessage,
  () => jobs.refreshJob(false),
  () => jobs.refreshFiles(false)
);

const jobPickerOpen = ref(false);

async function runSafely(action: () => Promise<void>): Promise<void> {
  try {
    await action();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    jobs.setMessage(message, "error");
    jobs.setOutput({ error: message });
  }
}

async function openJobPicker(): Promise<void> {
  await runSafely(async () => {
    await jobs.loadJobs();
    jobPickerOpen.value = true;
  });
}

async function openWorkflowSettings(mode: "run" | "resume"): Promise<void> {
  await runSafely(async () => {
    await workflow.loadSpeakerProfiles();
    workflow.openSettings(mode);
  });
}

async function submitWorkflowSettings(value: WorkflowOverrides): Promise<void> {
  await runSafely(() => workflow.submitSettings(value));
}
</script>

<template>
  <div class="shell">
    <AppHeader
      :api-base="jobs.apiBase.value"
      :health="jobs.health.value"
      @update:api-base="jobs.setApiBase"
      @check-health="runSafely(jobs.checkHealth)"
      @open-jobs="openJobPicker"
    />

    <main>
      <section class="stack">
        <UploadPanel :busy="jobs.busy.value" @upload="(payload) => runSafely(() => jobs.upload(payload.file, payload.videoType))" />
        <JobSummary
          :job="jobs.job.value"
          :message="jobs.message.value"
          :message-kind="jobs.messageKind.value"
          @refresh="runSafely(() => jobs.refreshJob(true))"
          @open-dir="runSafely(jobs.openWorkdir)"
        />
        <OperationPanel
          :disabled="!jobs.hasJob.value || jobs.busy.value || workflow.running.value"
          :has-artifacts="jobs.hasArtifacts.value"
          @probe="runSafely(() => jobs.runOperation('媒体探测', '/media/probe', 'GET'))"
          @extract-audio="runSafely(() => jobs.runOperation('音频提取', '/media/extract-audio'))"
          @separate="runSafely(() => jobs.runOperation('人声/背景分离', '/audio/separate'))"
          @background="runSafely(() => jobs.runOperation('背景音提取', '/audio/background'))"
          @speakers="runSafely(() => jobs.runOperation('说话人识别', '/speakers/identify'))"
          @package-video="(payload) => runSafely(() => jobs.packageCurrentVideo(payload.outputFilename, payload.audioFile))"
          @download-artifacts="jobs.downloadArtifacts"
        />
      </section>

      <section class="right-stack">
        <WorkflowPanel
          :disabled="!jobs.hasJob.value || workflow.running.value"
          :can-resume="workflow.canResume.value"
          :preprocess-steps="workflow.preprocessSteps.value"
          :workflow-steps="workflow.workflowSteps.value"
          :log-lines="workflow.logLines.value"
          @preprocess="runSafely(workflow.runPreprocess)"
          @run="openWorkflowSettings('run')"
          @resume="openWorkflowSettings('resume')"
        />
        <OutputPanel :output="jobs.output.value" @clear="jobs.clearOutput" />
      </section>
    </main>

    <JobPickerModal
      :open="jobPickerOpen"
      :jobs="jobs.jobs.value"
      @close="jobPickerOpen = false"
      @select="(jobId) => runSafely(async () => { await jobs.openJob(jobId); jobPickerOpen = false; })"
    />

    <WorkflowSettingsModal
      :open="workflow.settingsOpen.value"
      :mode="workflow.settingsMode.value"
      :initial-overrides="workflow.overrides.value"
      :speaker-profiles="workflow.speakerProfiles.value"
      @close="workflow.closeSettings"
      @submit="submitWorkflowSettings"
    />
  </div>
</template>
