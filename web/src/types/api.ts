export type MessageKind = "info" | "ok" | "error";

export interface Job {
  job_id: string;
  status?: string;
  workdir?: string;
  source_filename?: string;
  original_filename?: string;
  video_type?: string;
  created_at?: string;
  updated_at?: string;
  artifacts?: Record<string, string>;
  reports?: Record<string, unknown>;
  asr_result?: {
    speakers?: string[];
  };
  extra?: {
    asr_result?: {
      speakers?: string[];
    };
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface JobFile {
  name: string;
  relative_path: string;
  size_bytes?: number;
  modified_at?: string;
  download_url?: string;
}

export interface JobListResponse {
  jobs: Job[];
}

export interface JobFilesResponse {
  job_id: string;
  files: JobFile[];
}

export interface WorkflowEvent {
  event?: string;
  node?: string;
  label?: string;
  status?: string;
  message?: string;
  error?: string;
  hint?: string;
  index?: number;
  total?: number;
  job?: Job;
  result?: unknown;
  [key: string]: unknown;
}

export interface WorkflowOverrides {
  max_reflection_rounds: number;
  llm_timeout: number;
  llm_max_retries: number;
  tts_rate: number;
  tts_provider: string;
  speaker_profiles: Record<string, string>;
}

export interface AsrRunOptions {
  language?: string;
  enable_punc?: boolean;
  enable_itn?: boolean;
  enable_ddc?: boolean;
  enable_speaker_info?: boolean;
  max_query_attempts?: number;
  poll_interval_seconds?: number;
}

export interface AsrFieldMeta {
  label: string;
  required: boolean;
  fixed?: boolean;
  allow_empty?: boolean;
  official_default?: boolean;
  app_default?: number;
  empty_behavior?: string;
  source?: string;
  app_reason?: string;
  official_values?: string[];
}

export interface AsrSettingsResponse {
  provider: string;
  video_type: string;
  defaults: Required<AsrRunOptions> & {
    audio_format: string;
    model_name: string;
    show_utterances: boolean;
  };
  fields: Record<string, AsrFieldMeta>;
  language_options: Array<{ value: string; label: string }>;
  tos: {
    ready: boolean;
    endpoint: string;
    region: string;
    bucket: string;
    object_prefix: string;
    access_key_id_env: string;
    secret_access_key_env: string;
    configured: Record<string, boolean>;
    missing: string[];
  };
  official: Record<string, string>;
}

export interface StepState {
  key: string;
  label: string;
  status: string;
  kind: "idle" | "running" | "done" | "error";
}

export interface VoiceOption {
  voice_id: string;
  label: string;
  original_label: string;
  language: string;
}

export interface VoiceOptionsResponse {
  voices: VoiceOption[];
}
