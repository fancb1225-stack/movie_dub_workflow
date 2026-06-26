<script setup lang="ts">
import type { Job, MessageKind } from "../types/api";

const props = defineProps<{
  job: Job | null;
  message: string;
  messageKind: MessageKind;
}>();

const emit = defineEmits<{
  refresh: [];
  openDir: [];
}>();
</script>

<template>
  <section class="panel numbered-panel">
    <div class="panel-title">
      <h2><span class="panel-number">2.</span>当前 Job</h2>
      <button type="button" class="icon-button" :disabled="!props.job" title="刷新" @click="emit('refresh')">↻</button>
    </div>
    <div :class="['message', props.messageKind]">{{ props.message }}</div>
    <dl class="meta-grid" v-if="props.job">
      <dt>Job ID</dt>
      <dd>{{ props.job.job_id }}</dd>
      <dt>状态</dt>
      <dd><span class="status-chip">{{ props.job.status || "未知" }}</span></dd>
      <dt>源文件</dt>
      <dd>{{ props.job.original_filename || props.job.source_filename || "-" }}</dd>
      <dt>目录</dt>
      <dd>{{ props.job.workdir || "-" }}</dd>
    </dl>
    <p v-else class="empty">还没有打开任务。</p>
    <button type="button" class="ghost full-width" :disabled="!props.job" @click="emit('openDir')">打开工作目录</button>
  </section>
</template>
