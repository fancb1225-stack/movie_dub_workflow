<script setup lang="ts">
import type { Job } from "../types/api";

const props = defineProps<{
  open: boolean;
  jobs: Job[];
}>();

const emit = defineEmits<{
  close: [];
  select: [jobId: string];
}>();
</script>

<template>
  <div v-if="props.open" class="modal-backdrop" @click.self="emit('close')">
    <section class="modal">
      <div class="panel-title">
        <h2>历史任务</h2>
        <button type="button" class="icon-button" title="关闭" @click="emit('close')">×</button>
      </div>
      <div class="job-list" v-if="props.jobs.length">
        <button v-for="item in props.jobs" :key="item.job_id" type="button" class="job-row" @click="emit('select', item.job_id)">
          <span>{{ item.job_id }}</span>
          <strong>{{ item.status || "未知" }}</strong>
        </button>
      </div>
      <p v-else class="empty">没有找到历史任务。</p>
    </section>
  </div>
</template>
