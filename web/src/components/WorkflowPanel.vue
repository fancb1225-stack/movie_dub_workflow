<script setup lang="ts">
import type { StepState } from "../types/api";

const props = defineProps<{
  disabled: boolean;
  canResume: boolean;
  preprocessSteps: StepState[];
  workflowSteps: StepState[];
  logLines: string[];
}>();

const emit = defineEmits<{
  preprocess: [];
  asr: [];
  speakers: [];
  run: [];
  resume: [];
  clearLog: [];
}>();
</script>

<template>
  <section class="panel wide-panel workflow-card">
    <div class="panel-title">
      <h2><span class="panel-number">4.</span>工作流进度</h2>
      <span>预处理与 LangGraph</span>
    </div>
    <div class="workflow-actions">
      <button type="button" class="ghost icon-text" :disabled="props.disabled" @click="emit('preprocess')"><span>▶</span>预处理</button>
      <button type="button" class="ghost icon-text" :disabled="props.disabled" @click="emit('asr')"><span>◎</span>ASR</button>
      <button type="button" class="ghost icon-text" :disabled="props.disabled" @click="emit('speakers')"><span>☷</span>说话人识别</button>
      <button type="button" class="primary icon-text" :disabled="props.disabled" @click="emit('run')"><span>▶</span>运行配音工作流</button>
      <button type="button" class="ghost icon-text" :disabled="props.disabled || !props.canResume" @click="emit('resume')"><span>↻</span>恢复工作流</button>
    </div>
    <div class="timeline" aria-label="工作流时间线">
      <div v-for="step in [...props.preprocessSteps, ...props.workflowSteps]" :key="`timeline-${step.key}`" :class="['timeline-node', step.kind]">
        <span>{{ step.kind === "done" ? "✓" : step.kind === "running" ? "·" : step.kind === "error" ? "!" : "" }}</span>
        <strong>{{ step.label }}</strong>
      </div>
    </div>
    <div class="log-box">
      <div class="log-toolbar">
        <span>事件日志</span>
        <button type="button" class="ghost" :disabled="!props.logLines.length" @click="emit('clearLog')">清空</button>
      </div>
      <p v-if="!props.logLines.length" class="empty">暂无事件。</p>
      <div v-for="line in props.logLines" :key="line">{{ line }}</div>
    </div>
  </section>
</template>
