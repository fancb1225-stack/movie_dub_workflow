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
      <div>
        <h1>电影配音媒体控制台</h1>
        <p class="subtitle">上传媒体、预处理音轨、运行配音工作流并下载产物</p>
      </div>
      <div class="api-row">
        <label for="apiBase">API</label>
        <input id="apiBase" :value="props.apiBase" type="text" placeholder="留空使用当前域名" @input="emit('update:apiBase', ($event.target as HTMLInputElement).value)" />
        <button type="button" @click="emit('checkHealth')">检查</button>
        <span class="health">{{ props.health }}</span>
        <button type="button" class="ghost" @click="emit('openJobs')">历史任务</button>
      </div>
    </div>
  </header>
</template>
