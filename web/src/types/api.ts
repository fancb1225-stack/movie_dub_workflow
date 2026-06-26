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

export interface StepState {
  key: string;
  label: string;
  status: string;
  kind: "idle" | "running" | "done" | "error";
}

export interface VoiceOption {
  value: string;
  label: string;
}
