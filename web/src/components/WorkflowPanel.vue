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
  run: [];
  resume: [];
}>();
</script>

<template>
  <section class="panel wide-panel">
    <div class="panel-title">
      <h2>工作流</h2>
      <span>预处理与 LangGraph</span>
    </div>
    <div class="workflow-actions">
      <button type="button" :disabled="props.disabled" @click="emit('preprocess')">预处理</button>
      <button type="button" :disabled="props.disabled" @click="emit('run')">运行配音工作流</button>
      <button type="button" :disabled="props.disabled || !props.canResume" @click="emit('resume')">恢复工作流</button>
    </div>
    <div class="workflow-grid">
      <div>
        <h3>预处理步骤</h3>
        <div class="substeps">
          <div v-for="step in props.preprocessSteps" :key="step.key" :class="['substep', step.kind]">
            <span>{{ step.label }}</span>
            <strong>{{ step.status }}</strong>
          </div>
        </div>
      </div>
      <div>
        <h3>配音步骤</h3>
        <div class="substeps">
          <div v-for="step in props.workflowSteps" :key="step.key" :class="['substep', step.kind]">
            <span>{{ step.label }}</span>
            <strong>{{ step.status }}</strong>
          </div>
        </div>
      </div>
    </div>
    <div class="log-box">
      <p v-if="!props.logLines.length" class="empty">暂无事件。</p>
      <div v-for="line in props.logLines" :key="line">{{ line }}</div>
    </div>
  </section>
</template>
