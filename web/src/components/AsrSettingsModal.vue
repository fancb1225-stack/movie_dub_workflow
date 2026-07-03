<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import type { AsrRunOptions, AsrSettingsResponse } from "../types/api";

const props = defineProps<{
  open: boolean;
  settings: AsrSettingsResponse | null;
}>();

const emit = defineEmits<{
  close: [];
  submit: [AsrRunOptions];
}>();

const form = reactive<Required<AsrRunOptions>>({
  language: "",
  enable_punc: false,
  enable_itn: true,
  enable_ddc: false,
  enable_speaker_info: false,
  max_query_attempts: 300,
  poll_interval_seconds: 2
});

const requiredRows = computed(() => {
  if (!props.settings) return [];
  return [
    { key: "audio_url", value: "TOS/公网 URL", meta: props.settings.fields.audio_url },
    { key: "audio_format", value: props.settings.defaults.audio_format, meta: props.settings.fields.audio_format },
    { key: "model_name", value: props.settings.defaults.model_name, meta: props.settings.fields.model_name },
    { key: "show_utterances", value: props.settings.defaults.show_utterances ? "开启" : "关闭", meta: props.settings.fields.show_utterances }
  ];
});

const missingTos = computed(() => props.settings?.tos.missing || []);

watch(
  () => [props.open, props.settings] as const,
  ([open, settings]) => {
    if (!open || !settings) return;
    form.language = settings.defaults.language || "";
    form.enable_punc = settings.defaults.enable_punc;
    form.enable_itn = settings.defaults.enable_itn;
    form.enable_ddc = settings.defaults.enable_ddc;
    form.enable_speaker_info = settings.defaults.enable_speaker_info;
    form.max_query_attempts = settings.defaults.max_query_attempts;
    form.poll_interval_seconds = settings.defaults.poll_interval_seconds;
  },
  { immediate: true }
);

function submit(): void {
  emit("submit", {
    language: form.language,
    enable_punc: form.enable_punc,
    enable_itn: form.enable_itn,
    enable_ddc: form.enable_ddc,
    enable_speaker_info: form.enable_speaker_info,
    max_query_attempts: Number(form.max_query_attempts),
    poll_interval_seconds: Number(form.poll_interval_seconds)
  });
}

function boolText(value: boolean | undefined): string {
  return value ? "true" : "false";
}
</script>

<template>
  <div v-if="props.open" class="modal-backdrop" role="dialog" aria-modal="true" aria-label="ASR 参数设置">
    <form class="modal settings-modal asr-modal" @submit.prevent="submit">
      <div class="panel-title">
        <h2>豆包 ASR 参数</h2>
        <span>{{ props.settings?.video_type || "job" }}</span>
      </div>

      <p v-if="!props.settings" class="message">正在加载 ASR 配置...</p>

      <template v-else>
        <section>
          <h3>必填 / 固定</h3>
          <div class="asr-field-list">
            <div v-for="row in requiredRows" :key="row.key" class="asr-row">
              <strong>{{ row.meta.label }}</strong>
              <span>{{ row.value }}</span>
              <small>必填{{ row.meta.fixed ? "，固定" : "" }}{{ row.meta.app_reason ? `：${row.meta.app_reason}` : "" }}</small>
            </div>
          </div>
        </section>

        <section>
          <h3>选填参数</h3>
          <div class="form-grid">
            <label>
              语言
              <select v-model="form.language">
                <option v-for="option in props.settings.language_options" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
              <small>{{ props.settings.fields.language.empty_behavior }}</small>
            </label>

            <label>
              轮询次数
              <input v-model.number="form.max_query_attempts" type="number" min="1" step="1" />
              <small>应用参数，当前默认 {{ props.settings.defaults.max_query_attempts }}</small>
            </label>

            <label>
              轮询间隔（秒）
              <input v-model.number="form.poll_interval_seconds" type="number" min="0" step="0.1" />
              <small>应用参数，当前默认 {{ props.settings.defaults.poll_interval_seconds }}</small>
            </label>
          </div>

          <div class="toggle-grid">
            <label class="toggle-row">
              <input v-model="form.enable_punc" type="checkbox" />
              <span>标点</span>
              <small>官方默认 {{ boolText(props.settings.fields.enable_punc.official_default) }}，当前 {{ boolText(props.settings.defaults.enable_punc) }}</small>
            </label>
            <label class="toggle-row">
              <input v-model="form.enable_itn" type="checkbox" />
              <span>ITN</span>
              <small>官方默认 {{ boolText(props.settings.fields.enable_itn.official_default) }}，当前 {{ boolText(props.settings.defaults.enable_itn) }}</small>
            </label>
            <label class="toggle-row">
              <input v-model="form.enable_ddc" type="checkbox" />
              <span>顺滑</span>
              <small>官方默认 {{ boolText(props.settings.fields.enable_ddc.official_default) }}，当前 {{ boolText(props.settings.defaults.enable_ddc) }}</small>
            </label>
            <label class="toggle-row">
              <input v-model="form.enable_speaker_info" type="checkbox" />
              <span>多说话人</span>
              <small>影视解说默认关，漫剧默认开；官方默认 {{ boolText(props.settings.fields.enable_speaker_info.official_default) }}</small>
            </label>
          </div>
        </section>

        <section>
          <h3>TOS 配置</h3>
          <div :class="['message', props.settings.tos.ready ? 'ok' : 'error']">
            <strong>{{ props.settings.tos.ready ? "TOS 可用" : "TOS 配置不完整" }}</strong>
            <span v-if="!props.settings.tos.ready">缺少：{{ missingTos.join(", ") }}</span>
          </div>
          <dl class="meta-grid">
            <dt>Bucket</dt>
            <dd>{{ props.settings.tos.bucket || "-" }}</dd>
            <dt>Region</dt>
            <dd>{{ props.settings.tos.region || "-" }}</dd>
            <dt>Endpoint</dt>
            <dd>{{ props.settings.tos.endpoint || "-" }}</dd>
            <dt>Prefix</dt>
            <dd>{{ props.settings.tos.object_prefix }}</dd>
            <dt>AK/SK</dt>
            <dd>{{ props.settings.tos.access_key_id_env }} / {{ props.settings.tos.secret_access_key_env }}</dd>
          </dl>
        </section>
      </template>

      <div class="modal-actions">
        <button type="button" class="ghost" @click="emit('close')">取消</button>
        <button type="submit" class="primary" :disabled="!props.settings || !props.settings.tos.ready">开始 ASR</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.asr-modal {
  max-width: 920px;
}

.asr-field-list,
.toggle-grid {
  display: grid;
  gap: 10px;
}

.asr-field-list {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.asr-row,
.toggle-row {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.72);
  display: grid;
  gap: 5px;
  padding: 10px 12px;
}

.asr-row strong,
.toggle-row span {
  color: var(--ink);
  font-size: 12px;
  font-weight: 820;
}

.asr-row small,
.toggle-row small,
label small {
  color: var(--muted);
  font-size: 11px;
  font-weight: 650;
}

.toggle-row {
  align-items: center;
  grid-template-columns: auto minmax(110px, 0.35fr) minmax(0, 1fr);
}

.toggle-row input {
  height: 18px;
  width: 18px;
}

.message {
  display: grid;
  gap: 4px;
}

@media (max-width: 760px) {
  .asr-field-list,
  .toggle-row {
    grid-template-columns: 1fr;
  }
}
</style>
