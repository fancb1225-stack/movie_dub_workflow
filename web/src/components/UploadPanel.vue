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
  <section class="panel">
    <div class="panel-title">
      <h2>创建任务</h2>
      <span>MP4 / MP3</span>
    </div>
    <label for="uploadFile">媒体文件</label>
    <input id="uploadFile" type="file" accept=".mp4,.mp3,audio/*,video/mp4" @change="selectedFile = ($event.target as HTMLInputElement).files?.[0] || null" />
    <label for="videoType">内容类型</label>
    <select id="videoType" v-model="videoType">
      <option value="movie">电影/短片</option>
      <option value="commentary">解说</option>
      <option value="general">通用</option>
    </select>
    <button type="button" :disabled="busy || !selectedFile" @click="submit">上传并创建</button>
  </section>
</template>
