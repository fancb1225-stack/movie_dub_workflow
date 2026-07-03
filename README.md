# Movie Dub Workflow

Movie Dub Workflow 是一个面向影视解说、漫剧等视频内容的自动化英文配音工作流项目。它把视频上传、音频提取、人声/背景音分离、ASR 字幕识别、中文字幕清洗与合并、英文翻译、TTS 分段合成、时长检测、音频对齐合并、最终视频封装组织成可复用的本地流水线。

项目目前包含两套并列能力：

1. **LangGraph CLI 配音工作流**：保留原有命令行流程，适合本地批处理和调试。
2. **FastAPI 媒体功能层 + Web 控制台**：围绕 `outputs/jobs/<job_id>/` 隔离每个任务，支持上传、预处理、工作流执行、恢复、文件查看与视频封装。

媒体 API 与 LangGraph 主流程保持解耦：媒体处理能力通过 service/tool 层实现，不直接插入 `src/graph.py` 的节点顺序。

## 核心功能与技术细节

### 1. Job 隔离与文件组织

每个 Web/API 任务都保存在独立目录：

```text
outputs/jobs/<job_id>/
├── input/                     # 原始上传文件
├── media/                     # 媒体预处理产物
│   ├── source_audio.wav        # 从视频/音频提取出的源音频
│   └── separation/             # 人声与背景音分离结果
├── workflow/                  # LangGraph 工作流中间产物
│   ├── asr/                    # ASR 原始字幕与词级时间戳
│   ├── merged/                 # 合并后的中文字幕
│   ├── cleaned/                # 清洗后的中文字幕
│   ├── critic/                 # 校对后的中文字幕
│   ├── translated/             # 英文翻译字幕
│   ├── final/                  # 最终英文字幕
│   ├── tts_segments/           # TTS 分段音频与 manifest
│   └── audio/                  # 合并后的英文旁白音频
└── reports/                   # 各阶段 JSON 报告
```

这种结构保证不同视频任务之间不会互相污染，也方便恢复失败任务时直接读取已有产物。

### 2. 媒体预处理

媒体处理由 FastAPI service 和普通 tool 函数组成，不依赖 LLM。

- 支持 MP4/MP3 上传创建 job。
- 使用 FFmpeg/FFprobe 探测媒体流、时长、音视频轨道信息。
- FFmpeg 查找顺序：`config.yaml` 指定路径 → 项目内 `ffmpeg/bin` → 系统 `PATH`。
- 从 MP4 中提取音频为 `source_audio.wav`，作为后续 ASR 和人声分离输入。
- 视频封装时默认复制原视频流，只替换音频流，避免重编码视频造成质量损失和耗时增加。

### 3. 人声/背景音分离

音频分离阶段使用 Demucs：

- 默认模型：`htdemucs`。
- 输出人声：`media/separation/vocals.wav`。
- 输出背景音：`media/separation/background.wav`。
- 背景音只能来自分离结果，不会把原始中文解说当作背景音。
- 如果分离失败，service 会写入报告，并尽量让其它 API 操作继续可用。

Web/job LangGraph 工作流使用当前 job 的 `vocals.wav` 作为 ASR 输入，最终封装时使用 `background.wav` 与英文旁白合成。

### 4. ASR 与说话人信息

项目支持面向影视解说/漫剧的 ASR 配置：

- 影视解说默认使用豆包语音文件识别，按单说话人处理。
- 漫剧默认使用豆包语音文件识别，并开启多说话人参数。
- ASR 产物包括：
  - `zh_raw.srt`：原始中文字幕。
  - `zh_raw.words.json`：词级时间戳、说话人等结构化结果。
  - `asr_report.json`：ASR provider、字幕数量、词数、说话人列表、对齐状态等。

Web/job 模式默认不静默使用 mock ASR。如果没有安装真实 ASR provider 或没有配置真实 ASR，必须显式设置测试开关：

```yaml
workflow:
  allow_mock_asr_for_jobs: true
```

该开关仅用于测试和本地验证，不建议生产使用。

### 5. 中文字幕合并、清洗与校对

ASR 输出通常会存在切分过细、断句不自然、口语噪声等问题，因此工作流包含多个字幕处理节点：

1. `merge_zh_asr_srt`：把 ASR 细碎字幕合并为更适合翻译和配音的 cue。
2. `restitch_merge_cuts`：对硬切点或异常切分进行重整。
3. `clean_srt`：清洗口癖、重复、无意义噪声。
4. `critic_srt`：对中文字幕进行校对。
5. `summarize_plot`：生成剧情摘要，为后续翻译与时长反思提供上下文。

所有 Prompt 集中在 `src/prompts.py`，媒体处理不新增 Prompt，也不通过 ReAct Agent 执行。

### 6. 英文翻译

翻译节点使用 LLM，把清洗/校对后的中文字幕转换为英文字幕：

- 支持分块翻译，避免长视频一次性 prompt 超限。
- 支持并行 chunk 翻译，提高长视频处理速度。
- 输出 `en_translated.srt` 和结构化 cue JSON。
- 写入 `translation_report.json`，记录 chunk 数、并行度、失败 chunk、fallback 状态等。

翻译节点默认不静默使用模板 fallback。需要配置：

```text
LLM_API_KEY
LLM_BASE_URL
LLM_MODEL
```

如需测试 fallback，必须显式设置：

```yaml
translation:
  allow_mock_fallback: true
```

### 7. TTS 分段合成

TTS 阶段按字幕 cue 逐段生成音频：

- 支持 `mock`、`edge_tts`、`minimax` 等 provider。
- MiniMax TTS 使用异步任务模式：创建任务 → 轮询任务状态 → 下载音频文件。
- 每段输出：`workflow/tts_segments/segment_0001.mp3` 这类文件。
- 每段记录 index、文本、speaker_id、provider、voice_id、speed、duration_ms、success/error 等信息。
- 支持多说话人 voice profile；没有 `speaker_id` 的 cue 会落到 `default` speaker。
- MiniMax 下如果无法从 speaker profile、`minimax.default_voice_id`、`tts.voice` 解析出 voice_id，会使用 `Wise_Woman` 作为兜底 voice。

TTS 完成后会生成：

```text
reports/tts_duration_report.json
```

报告包含：

- 总段数、成功段数、失败段数。
- 每个失败段的 index 和错误原因。
- 超时段列表，包括字幕时长、TTS 时长、overrun、ratio、wpm 等。

### 8. TTS 增量恢复与 Manifest 校验

恢复工作流时，如果恢复节点是 `tts_generate_and_detect`，不会默认删除所有已成功生成的 segment。

恢复模式会开启：

```yaml
workflow:
  reuse_existing_tts_segments: true
```

TTS 目录中会写入：

```text
workflow/tts_segments/segment_manifest.json
```

每段 manifest 记录：

- index、path、text。
- success/error。
- duration_ms、file_size。
- provider、speaker_id、voice_id、speed。
- signature。

signature 使用稳定 JSON + SHA-256 计算，覆盖 cue 文本、provider、speaker、voice、speed、sample_rate、MiniMax model/base_url/create_path 等关键输入。

恢复时复用已有 segment 必须同时满足：

1. manifest 中存在该 index。
2. `success=true`。
3. signature 与当前 cue/config 一致。
4. mp3 文件存在且非 0 字节。
5. 音频时长可读取。
6. 该 index 不在上一次 `tts_duration_report.json` 的 `failed_errors` 中。

否则会重新生成该段。这样可以避免恢复时误复用旧文本、旧音色或损坏音频。

### 9. 时长检测与反思修正

TTS 后会检测英文配音是否超过原字幕时间窗：

- `max_overrun_ms`：允许的最大超时毫秒数。
- `max_ratio`：允许的最大 TTS/字幕时长比例。
- `max_reflection_rounds`：最多反思修正轮数。

如果存在 duration issue 且尚未达到最大轮数，工作流会进入 `reflect_duration_issues`：

1. 把超时段、剧情摘要、原文等信息交给 LLM。
2. 要求 LLM 缩短英文表达，尽量保留剧情信息。
3. 更新 `final_cues` 和 `en_final.srt`。
4. 回到 TTS 节点，只重生成文本变化的 segment。

如果没有超时问题，或已经达到最大轮数，则进入音频合并节点。

### 10. 音频对齐与合并

最终音频合并节点 `align_and_merge_audio` 会把所有 TTS segment 放置到对应时间轴：

- `simple` 模式：顺序放置，必要时顺延，避免前后段重叠。
- `window` 模式：在窗口内尝试更细的顺延策略，并输出 delay 明细。
- `overlap_resolution` 模式：使用重叠消解策略处理冲突。

输出：

```text
workflow/audio/narration_en.wav
workflow/audio/narration_en.mp3
reports/pipeline_report.json
```

`pipeline_report.json` 会记录字幕数量、TTS 段数、剩余时长问题、音频总时长、placements、warnings 等。

### 11. 工作流恢复

工作流每完成一个节点会保存：

```text
workflow/state_snapshot.json
```

恢复逻辑：

1. 优先读取 state snapshot，得到 `last_completed_node`。
2. 从 `NODE_ORDER` 中选择下一个节点作为恢复入口。
3. 如果没有 snapshot，则根据磁盘 artifacts 反推最后完成节点。
4. 成功完成后清除 snapshot。

节点顺序：

```text
merge_zh_asr_srt
→ restitch_merge_cuts
→ clean_srt
→ critic_srt
→ summarize_plot
→ translate_to_english
→ tts_generate_and_detect
→ reflect_duration_issues
→ align_and_merge_audio
```

### 12. 视频封装

视频封装阶段把原视频流与新生成的英文音频合成为最终视频：

- 默认复制原视频流，不烧录硬字幕。
- 当前阶段不封装软字幕轨。
- 音频轨替换为英文旁白/混音结果。
- 适合先快速验证配音效果，再进入后续字幕包装或发布流程。

## Python 环境

使用项目本地 venv：

```powershell
.\.venv\Scripts\Activate.ps1
```

安装依赖优先使用 `uv`：

```powershell
uv pip install -r requirements.txt
```

如果没有安装 `uv`，使用 pip：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 环境变量

典型 `.env` 配置包括：

```text
LLM_API_KEY=...
LLM_BASE_URL=...
LLM_MODEL=...
TTS_MODEL=...
MINIMAX_GROUP_ID=...
```

具体字段以 `config.yaml` 中的 provider 配置为准。不要把 API Key 写入代码。

## 启动 FastAPI 与 Web 控制台

启动 API：

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.api.app:app --reload
```

打开控制台：

```text
http://127.0.0.1:8000/
```

健康检查：

```text
GET /health
```

## 主要 API

```text
POST /api/jobs
GET  /api/jobs/{job_id}
GET  /api/jobs/{job_id}/files
GET  /api/jobs/{job_id}/files/download?path=<relative_path>
POST /api/jobs/{job_id}/open-workdir
GET  /api/jobs/{job_id}/media/probe
POST /api/jobs/{job_id}/media/extract-audio
POST /api/jobs/{job_id}/audio/separate
POST /api/jobs/{job_id}/audio/background
GET  /api/asr/settings
POST /api/jobs/{job_id}/asr
POST /api/jobs/{job_id}/workflow/langgraph
POST /api/jobs/{job_id}/workflow/langgraph/resume
POST /api/jobs/{job_id}/video/package
```

## 运行原有 CLI 工作流

```powershell
.\.venv\Scripts\python.exe -m src.main
```

主要输出：

```text
outputs/asr/zh_raw.srt
outputs/cleaned/zh_cleaned.srt
outputs/merged/zh_merged_before_critic.srt
outputs/critic/zh_corrected.srt
outputs/merged/zh_merged_after_critic.srt
outputs/translated/en_translated.srt
outputs/final/en_final.srt
outputs/tts_segments/*.mp3
outputs/audio/narration_en.wav
outputs/audio/narration_en.mp3
outputs/reports/pipeline_report.json
```

## Docker

启动 FastAPI 媒体控制台：

```powershell
docker compose up --build
```

构建镜像：

```powershell
docker build -t movie-dub-workflow .
```

运行容器：

```powershell
docker run --rm -p 8000:8000 --env-file .env -v ${PWD}/outputs:/app/outputs movie-dub-workflow
```

ASR 使用豆包语音文件识别和 TOS/公网 URL，不需要本地 ASR 或 CUDA 运行时。

## 开发与验证

单元测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_unit_*.py"
```

语法编译检查：

```powershell
.\.venv\Scripts\python.exe -m compileall src tests
```

如果已安装 pytest 依赖：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 媒体处理策略

- MP4 和 MP3 上传由 API 支持。
- 背景音只来自 Demucs 等分离结果中的 no-vocals/background stem。
- 原始中文解说音频不会被当作背景音。
- Web/job LangGraph 工作流使用当前 job 分离得到的 `vocals.wav`。
- Web/job LangGraph 工作流默认不静默使用 mock ASR。
- 翻译节点默认不静默使用模板 fallback。
- 视频封装默认复制原视频流，只替换音频流。
- 当前阶段不烧录硬字幕，不封装软字幕轨。
