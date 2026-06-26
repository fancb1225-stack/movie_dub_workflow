<script setup lang="ts">
import { ref } from "vue";

defineProps<{ busy: boolean }>();

const emit = defineEmits<{
  upload: [{ file: File; videoType: string }];
}>();

const selectedFile = ref<File | null>(null);
const videoType = ref("movie");

function submit(): void {
  if (!selectedFile.value) return;
  emit("upload", { file: selectedFile.value, videoType: videoType.value });
}
</script>

<template>
  <section class="panel numbered-panel">
    <div class="panel-title">
      <h2><span class="panel-number">1.</span>上传媒体</h2>
      <span>MP4 / MP3</span>
    </div>
    <label class="dropzone" for="uploadFile">
      <span class="drop-icon">⇧</span>
      <strong>{{ selectedFile ? selectedFile.name : "选择或拖入 MP4 / MP3 文件" }}</strong>
      <small>任务文件会隔离到 outputs/jobs/&lt;job_id&gt;/</small>
      <input id="uploadFile" type="file" accept=".mp4,.mp3,audio/*,video/mp4" @change="selectedFile = ($event.target as HTMLInputElement).files?.[0] || null" />
    </label>
    <div class="inline-form">
      <label for="videoType">内容类型</label>
      <select id="videoType" v-model="videoType">
        <option value="movie">电影/短片</option>
        <option value="commentary">解说</option>
        <option value="general">通用</option>
      </select>
    </div>
    <button type="button" class="primary full-width" :disabled="busy || !selectedFile" @click="submit">创建 Job</button>
  </section>
</template>
