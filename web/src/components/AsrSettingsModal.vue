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

const missingTos = computed(() => props.settings?.tos.missing || []);
const isMultiSpeakerDefault = computed(() => props.settings?.defaults.enable_speaker_info || false);
const selectedStrategy = computed(() => (form.enable_speaker_info ? "multi" : "single"));

const fixedSummary = computed(() => {
  if (!props.settings) return [];
  return [
    { label: "音频来源", value: "上传到 TOS 后识别", required: true },
    { label: "格式", value: props.settings.defaults.audio_format, required: true },
    { label: "模型", value: props.settings.defaults.model_name, required: true },
    { label: "分句结果", value: props.settings.defaults.show_utterances ? "开启" : "关闭", required: true }
  ];
});

const qualityToggles = computed(() => {
  if (!props.settings) return [];
  return [
    {
      key: "enable_punc",
      label: "智能标点",
      description: "让字幕更像可读文案，适合直接进入翻译与配音。",
      officialDefault: props.settings.fields.enable_punc.official_default,
      value: form.enable_punc
    },
    {
      key: "enable_itn",
      label: "数字规整 ITN",
      description: "把口语数字、日期、金额等整理成更稳定的文本。",
      officialDefault: props.settings.fields.enable_itn.official_default,
      value: form.enable_itn
    },
    {
      key: "enable_ddc",
      label: "文本顺滑",
      description: "降低口语重复和不自然断句，适合长解说音频。",
      officialDefault: props.settings.fields.enable_ddc.official_default,
      value: form.enable_ddc
    }
  ];
});

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

function setStrategy(value: "single" | "multi"): void {
  form.enable_speaker_info = value === "multi";
}

function toggleQuality(key: string): void {
  if (key === "enable_punc") form.enable_punc = !form.enable_punc;
  if (key === "enable_itn") form.enable_itn = !form.enable_itn;
  if (key === "enable_ddc") form.enable_ddc = !form.enable_ddc;
}

function boolText(value: boolean | undefined): string {
  return value ? "开" : "关";
}
</script>

<template>
  <div v-if="props.open" class="modal-backdrop" role="dialog" aria-modal="true" aria-label="ASR 参数设置">
    <form class="modal settings-modal asr-modal" @submit.prevent="submit">
      <div class="asr-header">
        <div>
          <p class="eyebrow">豆包语音文件识别</p>
          <h2>ASR 参数设置</h2>
          <p class="header-copy">按内容类型预设好关键参数，只调整会影响识别结果的选项。</p>
        </div>
        <span class="type-chip">{{ props.settings?.video_type || "job" }}</span>
      </div>

      <p v-if="!props.settings" class="message">正在加载 ASR 配置...</p>

      <template v-else>
        <section class="summary-strip" aria-label="必填固定参数">
          <div v-for="item in fixedSummary" :key="item.label" class="summary-item">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <small>必填 · 系统固定</small>
          </div>
        </section>

        <section class="section-block">
          <div class="section-heading">
            <div>
              <h3>1. 识别策略</h3>
              <p>先决定是否需要说话人区分。影视解说通常是单人旁白，漫剧通常是多人对白。</p>
            </div>
            <span class="default-note">当前预设：{{ isMultiSpeakerDefault ? "多人对白" : "单人旁白" }}</span>
          </div>

          <div class="strategy-grid">
            <button
              type="button"
              :class="['strategy-card', selectedStrategy === 'single' ? 'selected' : '']"
              @click="setStrategy('single')"
            >
              <span class="strategy-icon">1</span>
              <strong>单人旁白</strong>
              <small>输出统一 speaker_0，适合影视解说、纪录片旁白。</small>
            </button>
            <button
              type="button"
              :class="['strategy-card', selectedStrategy === 'multi' ? 'selected' : '']"
              @click="setStrategy('multi')"
            >
              <span class="strategy-icon">N</span>
              <strong>多人对白</strong>
              <small>请求豆包聚类说话人，适合漫剧、访谈和多人场景。</small>
            </button>
          </div>
        </section>

        <section class="section-block">
          <div class="section-heading">
            <div>
              <h3>2. 文本质量</h3>
              <p>这些开关会影响字幕文本形态；官方默认值保留在每项右侧。</p>
            </div>
          </div>

          <div class="quality-grid">
            <button
              v-for="item in qualityToggles"
              :key="item.key"
              type="button"
              :class="['quality-card', item.value ? 'selected' : '']"
              @click="toggleQuality(item.key)"
            >
              <span class="switch-dot" aria-hidden="true"></span>
              <span>
                <strong>{{ item.label }}</strong>
                <small>{{ item.description }}</small>
              </span>
              <em>官方默认 {{ boolText(item.officialDefault) }}</em>
            </button>
          </div>
        </section>

        <section class="section-block">
          <div class="section-heading">
            <div>
              <h3>3. 语言与轮询</h3>
              <p>语言可留空使用官方中英文及方言能力；轮询参数只影响等待策略。</p>
            </div>
          </div>

          <div class="form-grid compact-grid">
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
        </section>

        <section class="section-block tos-block">
          <div class="section-heading">
            <div>
              <h3>4. 上传通道</h3>
              <p>豆包文件识别需要可访问的音频 URL，本项目会先上传到 TOS。</p>
            </div>
            <span :class="['readiness-pill', props.settings.tos.ready ? 'ready' : 'blocked']">
              {{ props.settings.tos.ready ? "可开始" : "需配置" }}
            </span>
          </div>

          <div :class="['tos-alert', props.settings.tos.ready ? 'ready' : 'blocked']">
            <strong>{{ props.settings.tos.ready ? "TOS 上传通道已就绪" : "开始前需要补齐 TOS 配置" }}</strong>
            <span v-if="!props.settings.tos.ready">缺少：{{ missingTos.join(", ") }}</span>
            <span v-else>将使用 {{ props.settings.tos.bucket }}/{{ props.settings.tos.object_prefix }} 生成公网 URL。</span>
          </div>

          <dl class="tos-grid">
            <div>
              <dt>Bucket</dt>
              <dd>{{ props.settings.tos.bucket || "-" }}</dd>
            </div>
            <div>
              <dt>Region</dt>
              <dd>{{ props.settings.tos.region || "-" }}</dd>
            </div>
            <div>
              <dt>Endpoint</dt>
              <dd>{{ props.settings.tos.endpoint || "-" }}</dd>
            </div>
            <div>
              <dt>Prefix</dt>
              <dd>{{ props.settings.tos.object_prefix }}</dd>
            </div>
            <div class="wide">
              <dt>AK/SK 环境变量</dt>
              <dd>{{ props.settings.tos.access_key_id_env }} / {{ props.settings.tos.secret_access_key_env }}</dd>
            </div>
          </dl>
        </section>
      </template>

      <div class="modal-actions asr-actions">
        <span v-if="props.settings && !props.settings.tos.ready" class="disabled-reason">补齐 TOS 后才能开始识别</span>
        <button type="button" class="ghost" @click="emit('close')">取消</button>
        <button type="submit" class="primary" :disabled="!props.settings || !props.settings.tos.ready">开始 ASR</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.asr-modal {
  gap: 18px;
  max-width: 880px;
  padding: 22px;
}

.asr-header {
  align-items: flex-start;
  border-bottom: 1px solid var(--line);
  display: flex;
  gap: 16px;
  justify-content: space-between;
  padding-bottom: 14px;
}

.asr-header h2 {
  display: block;
  font-size: 20px;
}

.eyebrow,
.header-copy,
.section-heading p,
.summary-item small,
.quality-card small,
label small,
.disabled-reason {
  color: var(--muted);
  font-size: 12px;
}

.eyebrow {
  color: var(--accent);
  font-weight: 820;
  margin-bottom: 4px;
}

.header-copy {
  margin-top: 5px;
}

.type-chip,
.default-note,
.readiness-pill {
  border: 1px solid rgba(0, 127, 134, 0.18);
  border-radius: var(--radius-pill);
  background: var(--accent-soft);
  color: var(--accent);
  flex: 0 0 auto;
  font-size: 11px;
  font-weight: 840;
  padding: 7px 10px;
  white-space: nowrap;
}

.summary-strip {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.summary-item {
  background: rgba(255, 255, 255, 0.62);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 11px 12px;
}

.summary-item span,
.tos-grid dt {
  color: var(--muted);
  font-size: 11px;
  font-weight: 820;
}

.summary-item strong {
  color: var(--ink);
  font-size: 14px;
  overflow-wrap: anywhere;
}

.section-block {
  display: grid;
  gap: 12px;
}

.section-heading {
  align-items: flex-start;
  display: flex;
  gap: 14px;
  justify-content: space-between;
}

.section-heading h3 {
  margin-bottom: 3px;
}

.strategy-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.strategy-card,
.quality-card {
  background: rgba(255, 255, 255, 0.74);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  box-shadow: none;
  color: var(--ink);
  justify-content: start;
  min-height: 0;
  text-align: left;
}

.strategy-card {
  align-items: start;
  display: grid;
  gap: 7px;
  grid-template-columns: 38px minmax(0, 1fr);
  padding: 13px;
}

.strategy-card small {
  color: var(--muted);
  font-size: 12px;
  font-weight: 650;
  grid-column: 2;
}

.strategy-icon {
  align-items: center;
  background: rgba(0, 127, 134, 0.1);
  border-radius: 12px;
  color: var(--accent);
  display: inline-grid;
  font-size: 13px;
  font-weight: 900;
  height: 32px;
  justify-content: center;
  width: 32px;
}

.strategy-card.selected,
.quality-card.selected {
  background: linear-gradient(180deg, rgba(235, 253, 251, 0.94), rgba(255, 255, 255, 0.9));
  border-color: rgba(0, 127, 134, 0.44);
  box-shadow: 0 10px 24px rgba(0, 127, 134, 0.1);
}

.quality-grid {
  display: grid;
  gap: 9px;
}

.quality-card {
  align-items: center;
  display: grid;
  gap: 12px;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  padding: 12px 13px;
}

.quality-card > span:not(.switch-dot) {
  display: grid;
  gap: 3px;
}

.quality-card em {
  color: var(--muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 760;
  white-space: nowrap;
}

.switch-dot {
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  height: 20px;
  position: relative;
  width: 20px;
}

.quality-card.selected .switch-dot {
  background: var(--accent);
  border-color: var(--accent);
}

.quality-card.selected .switch-dot::after {
  color: #fff;
  content: "✓";
  font-size: 13px;
  font-weight: 900;
  left: 4px;
  position: absolute;
  top: 0;
}

.compact-grid {
  grid-template-columns: 1.4fr 1fr 1fr;
}

.tos-alert {
  border-radius: var(--radius-md);
  display: grid;
  gap: 4px;
  padding: 12px 13px;
}

.tos-alert.blocked {
  background: var(--danger-soft);
  border: 1px solid rgba(217, 45, 32, 0.24);
  color: var(--danger);
}

.tos-alert.ready {
  background: var(--ok-soft);
  border: 1px solid rgba(21, 128, 61, 0.22);
  color: var(--ok);
}

.readiness-pill.ready {
  background: var(--ok-soft);
  border-color: rgba(21, 128, 61, 0.2);
  color: var(--ok);
}

.readiness-pill.blocked {
  background: var(--danger-soft);
  border-color: rgba(217, 45, 32, 0.22);
  color: var(--danger);
}

.tos-grid {
  display: grid;
  gap: 8px 12px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 0;
}

.tos-grid div {
  min-width: 0;
}

.tos-grid .wide {
  grid-column: span 2;
}

.tos-grid dd {
  color: var(--ink);
  font-size: 12px;
  font-weight: 720;
  margin: 2px 0 0;
  overflow-wrap: anywhere;
}

.asr-actions {
  align-items: center;
  border-top: 1px solid var(--line);
  padding-top: 14px;
}

.disabled-reason {
  margin-right: auto;
}

@media (max-width: 860px) {
  .summary-strip,
  .compact-grid,
  .tos-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .asr-header,
  .section-heading,
  .asr-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .summary-strip,
  .strategy-grid,
  .compact-grid,
  .tos-grid,
  .tos-grid .wide {
    grid-template-columns: 1fr;
  }

  .quality-card {
    grid-template-columns: 24px minmax(0, 1fr);
  }

  .quality-card em {
    grid-column: 2;
  }

  .disabled-reason {
    margin-right: 0;
  }
}
</style>
