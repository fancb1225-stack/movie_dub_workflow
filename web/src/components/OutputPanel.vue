<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ output: unknown }>();
const emit = defineEmits<{ clear: [] }>();

const formatted = computed(() => JSON.stringify(props.output ?? {}, null, 2));
</script>

<template>
  <section class="panel wide-panel">
    <div class="panel-title">
      <h2><span class="panel-number">6.</span>JSON 输出</h2>
      <button type="button" class="ghost" @click="emit('clear')">清空</button>
    </div>
    <pre class="output">{{ formatted }}</pre>
  </section>
</template>
