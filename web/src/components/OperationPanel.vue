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
  packageVideo: [{ outputFilename: string; audioFile: File | null }];
  downloadArtifacts: [];
}>();

const outputFilename = ref("final_en.mp4");
const audioFile = ref<File | null>(null);
</script>

<template>
  <section class="panel numbered-panel">
    <div class="panel-title">
      <h2><span class="panel-number">3.</span>媒体操作</h2>
      <span>确定性工具</span>
    </div>
    <div class="operation-list">
      <button type="button" :disabled="props.disabled" @click="emit('probe')"><span>◉</span><strong>文件信息</strong><small>读取格式与时长</small></button>
      <button type="button" :disabled="props.disabled" @click="emit('extractAudio')"><span>♪</span><strong>提取音频</strong><small>从视频分离音轨</small></button>
      <button type="button" :disabled="props.disabled" @click="emit('separate')"><span>≋</span><strong>分离人声</strong><small>生成 vocals/background</small></button>
      <button type="button" :disabled="props.disabled || !props.hasArtifacts" @click="emit('downloadArtifacts')"><span>⇩</span><strong>下载产物</strong><small>打包所有输出</small></button>
    </div>
    <!-- <div class="divider"></div>
    <label for="audioFile">替换音频</label>
    <input id="audioFile" type="file" accept="audio/*,.mp3,.wav,.m4a" @change="audioFile = ($event.target as HTMLInputElement).files?.[0] || null" />
    <label for="outputFilename">输出 MP4 文件名</label>
    <input id="outputFilename" v-model="outputFilename" type="text" />
    <button type="button" class="primary full-width" :disabled="props.disabled" @click="emit('packageVideo', { outputFilename, audioFile })">封装 MP4</button> -->
  </section>
</template>
