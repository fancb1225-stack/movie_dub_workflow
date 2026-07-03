<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import type { VoiceOption, WorkflowOverrides } from "../types/api";

const props = defineProps<{
  open: boolean;
  mode: "run" | "resume";
  initialOverrides: WorkflowOverrides;
  speakerProfiles: Record<string, string>;
  voiceOptions: VoiceOption[];
}>();

const emit = defineEmits<{
  close: [];
  submit: [value: WorkflowOverrides];
}>();

const form = reactive<WorkflowOverrides>({
  max_reflection_rounds: 2,
  llm_timeout: 600,
  llm_max_retries: 1,
  tts_rate: 1.3,
  tts_provider: "doubao",
  speaker_profiles: {}
});

const speakerKeys = computed(() => Object.keys(form.speaker_profiles).length ? Object.keys(form.speaker_profiles) : ["default"]);

watch(
  () => [props.open, props.initialOverrides, props.speakerProfiles] as const,
  () => {
    Object.assign(form, props.initialOverrides, {
      speaker_profiles: Object.keys(props.speakerProfiles).length ? { ...props.speakerProfiles } : { default: "Wise_Woman" }
    });
  },
  { immediate: true }
);

function submit(): void {
  emit("submit", {
    ...form,
    speaker_profiles: { ...form.speaker_profiles }
  });
}
</script>

<template>
  <div v-if="props.open" class="modal-backdrop" @click.self="emit('close')">
    <section class="modal settings-modal">
      <div class="panel-title">
        <h2>{{ props.mode === "resume" ? "恢复工作流设置" : "工作流设置" }}</h2>
        <button type="button" class="icon-button" title="关闭" @click="emit('close')">×</button>
      </div>

      <div class="form-grid">
        <label>
          反思轮数
          <input v-model.number="form.max_reflection_rounds" type="number" min="0" max="10" />
        </label>
        <label>
          LLM 超时秒数
          <input v-model.number="form.llm_timeout" type="number" min="30" step="30" />
        </label>
        <label>
          LLM 重试次数
          <input v-model.number="form.llm_max_retries" type="number" min="0" max="5" />
        </label>
        <label>
          TTS 语速倍率
          <input v-model.number="form.tts_rate" type="number" min="0.5" max="2" step="0.1" />
        </label>
        <label>
          TTS Provider
          <input v-model="form.tts_provider" type="text" />
        </label>
      </div>

      <h3>说话人音色</h3>
      <div class="speaker-grid">
        <label v-for="speaker in speakerKeys" :key="speaker">
          {{ speaker }}
          <select v-model="form.speaker_profiles[speaker]">
            <option v-for="voice in props.voiceOptions" :key="voice.voice_id" :value="voice.voice_id">
              {{ voice.label }} / {{ voice.original_label }}
            </option>
          </select>
        </label>
      </div>

      <div class="modal-actions">
        <button type="button" class="ghost" @click="emit('close')">取消</button>
        <button type="button" @click="submit">确认并执行</button>
      </div>
    </section>
  </div>
</template>
