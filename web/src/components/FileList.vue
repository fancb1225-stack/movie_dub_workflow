<script setup lang="ts">
import type { JobFile } from "../types/api";

const props = defineProps<{
  disabled: boolean;
  files: JobFile[];
}>();

const emit = defineEmits<{
  refresh: [];
  download: [relativePath: string];
}>();

function formatBytes(value?: number): string {
  if (!value) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}
</script>

<template>
  <section class="panel wide-panel">
    <div class="panel-title">
      <h2><span class="panel-number">5.</span>文件与产物</h2>
      <button type="button" class="icon-button" :disabled="props.disabled" title="刷新文件" @click="emit('refresh')">↻</button>
    </div>
    <div class="file-table" v-if="props.files.length">
      <div class="file-table-head">
        <span>Name</span>
        <span>Size</span>
        <span>Action</span>
      </div>
      <button v-for="file in props.files" :key="file.relative_path" type="button" class="file-row" @click="emit('download', file.relative_path)">
        <span class="file-name"><i aria-hidden="true">{{ file.relative_path.endsWith('.mp4') ? '▥' : file.relative_path.endsWith('.json') ? '{}' : '♪' }}</i>{{ file.relative_path }}</span>
        <strong>{{ formatBytes(file.size_bytes) }}</strong>
        <em>⇩</em>
      </button>
    </div>
    <p v-else class="empty">暂无文件。</p>
  </section>
</template>
