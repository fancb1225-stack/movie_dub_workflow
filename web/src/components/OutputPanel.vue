<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ output: unknown }>();
const emit = defineEmits<{ clear: [] }>();

const formatted = computed(() => JSON.stringify(props.output ?? {}, null, 2));
const outputLines = computed(() => formatted.value.split("\n"));
</script>

<template>
  <section class="panel wide-panel">
    <div class="panel-title">
      <h2><span class="panel-number">6.</span>JSON 输出</h2>
      <button type="button" class="ghost" @click="emit('clear')">清空</button>
    </div>
    <pre class="output"><span v-for="(line, index) in outputLines" :key="index" class="output-line"><span class="output-line-number">{{ index + 1 }}</span><span class="output-line-code">{{ line || " " }}</span></span></pre>
  </section>
</template>
