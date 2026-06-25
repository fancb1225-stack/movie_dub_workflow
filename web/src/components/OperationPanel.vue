<script setup lang="ts">
import { ref } from "vue";

const props = defineProps<{
  disabled: boolean;
  hasArtifacts: boolean;
}>();

const emit = defineEmits<{
  probe: [];
  extractAudio: [];
  separate: [];
  background: [];
  speakers: [];
  packageVideo: [{ outputFilename: string; audioFile: File | null }];
  downloadArtifacts: [];
}>();

const outputFilename = ref("final_en.mp4");
const audioFile = ref<File | null>(null);
</script>

<template>
  <section class="panel">
    <div class="panel-title">
      <h2>媒体操作</h2>
      <span>确定性工具</span>
    </div>
    <div class="button-grid">
      <button type="button" :disabled="props.disabled" @click="emit('probe')">探测</button>
      <button type="button" :disabled="props.disabled" @click="emit('extractAudio')">提取音频</button>
      <button type="button" :disabled="props.disabled" @click="emit('separate')">分离人声</button>
      <button type="button" :disabled="props.disabled" @click="emit('background')">背景音</button>
      <button type="button" :disabled="props.disabled" @click="emit('speakers')">说话人</button>
      <button type="button" :disabled="props.disabled || !props.hasArtifacts" @click="emit('downloadArtifacts')">下载产物</button>
    </div>
    <div class="divider"></div>
    <label for="audioFile">替换音频</label>
    <input id="audioFile" type="file" accept="audio/*,.mp3,.wav,.m4a" @change="audioFile = ($event.target as HTMLInputElement).files?.[0] || null" />
    <label for="outputFilename">输出 MP4 文件名</label>
    <input id="outputFilename" v-model="outputFilename" type="text" />
    <button type="button" :disabled="props.disabled" @click="emit('packageVideo', { outputFilename, audioFile })">封装 MP4</button>
  </section>
</template>
