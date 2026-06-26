<script setup lang="ts">
const props = defineProps<{
  apiBase: string;
  health: string;
}>();

const emit = defineEmits<{
  "update:apiBase": [value: string];
  checkHealth: [];
  openJobs: [];
}>();
</script>

<template>
  <header>
    <div class="topbar">
      <div class="brand-block">
        <div class="brand-mark" aria-hidden="true">
          <span></span><span></span><span></span><span></span>
        </div>
        <div>
          <div class="brand-title-row">
            <h1>电影配音控制台</h1>
            <span class="version-pill">Vue 3 · TypeScript</span>
          </div>
          <p class="subtitle">媒体预处理、LangGraph 配音、产物下载与视频封装</p>
        </div>
      </div>
      <div class="api-row">
        <span class="status-dot" aria-hidden="true"></span>
        <span class="health-label">接口状态</span>
        <span class="health-pill">{{ props.health }}</span>
        <input id="apiBase" :value="props.apiBase" type="text" placeholder="留空使用当前域名" @input="emit('update:apiBase', ($event.target as HTMLInputElement).value)" />
        <button type="button" class="ghost icon-text" @click="emit('checkHealth')"><span>↻</span>检查</button>
        <button type="button" class="primary icon-text" @click="emit('openJobs')"><span>▤</span>历史任务</button>
      </div>
    </div>
  </header>
</template>
