# AGENTS.md

# Codex Agent Instructions

## 1. 角色

你是本项目的代码实现 Agent。你的任务是根据 `PROJECT_PLAN.md` 实现一个基于 LangGraph 的电影解说英文配音工作流。

你需要优先保证项目可以运行，而不是追求一次性实现复杂功能。

包管理优先uv, 备选pip.
---

## 2. 当前核心目标

当前版本的输入是：

```text
input/input.mp3
```

当前版本的输出是：

```text
outputs/audio/narration_en.wav
outputs/audio/narration_en.mp3
outputs/final/en_final.srt
outputs/reports/pipeline_report.json
```

不要把输入设计成 MP4。

不要假设用户已经有 SRT。

LangGraph 必须先从 MP3 进入 ASR 节点，生成中文字幕 SRT，再进入后续字幕处理流程。

---

## 3. 固定 LangGraph 流程

必须实现以下固定流程：

```text
MP3 输入
→ ASR 生成中文字幕 SRT
→ SRT 清洗
→ 字幕合并 + 中文字幕审校
→ 字幕合并
→ 剧情总结
→ 英文翻译
→ TTS 真实时长生成与检测
→ 局部反思修正
→ 音频对齐与合并
```

流程节点名称建议使用：

```text
asr_mp3_to_srt
clean_srt
merge_and_critic
post_merge
summarize_plot
translate_to_english
tts_generate_and_detect
reflect_duration_issues
align_and_merge_audio
```

---

## 4. 工具调用原则

以下模块必须放在 `src/tools/` 下：

```text
asr_tools.py
srt_tools.py
merge_tools.py
tts_tools.py
duration_tools.py
audio_tools.py
file_tools.py
```

这些工具是固定流程节点调用的工具，不是 LLM 自主选择的工具。

禁止实现成 ReAct Agent。

禁止让 LLM 判断是否调用工具。

禁止让 LLM 选择调用哪个工具。

LangGraph 是流程编排器，tools 是普通函数模块。

---

## 5. LLM 使用边界

LLM 只能用于以下节点：

```text
merge_and_critic 中的中文字幕审校
summarize_plot 中的剧情总结
translate_to_english 中的英文翻译
reflect_duration_issues 中的局部反思修正
```

LLM 不能用于：

```text
ASR
SRT 解析
SRT 清洗
字幕合并规则判断
TTS 生成
真实音频时长检测
音频对齐
音频合并
文件写入
```

---

## 6. State 要求

所有节点必须通过 LangGraph State 传递数据。

不要使用全局变量保存流程状态。

State 至少要保存：

```text
config
asr_result
raw_srt
raw_cues
cleaned_srt
cleaned_cues
merged_before_critic_srt
merged_before_critic_cues
corrected_srt
corrected_cues
merged_after_critic_srt
merged_after_critic_cues
plot_summary
en_translated_srt
en_translated_cues
final_srt
final_cues
tts_segments
duration_issues
reflection_rounds
narration_wav_path
narration_mp3_path
reports
errors
```

所有工具调用结果必须写入 State。

所有重要中间结果必须写入 `outputs/`。

---

## 7. 目录结构要求

必须按照以下结构实现：

```text
movie_dub_workflow/
├── README.md
├── AGENTS.md
├── PROJECT_PLAN.md
├── requirements.txt
├── .env.example
├── config.yaml
├── input/
│   ├── input.mp3
│   └── background.mp3
├── outputs/
└── src/
    ├── __init__.py
    ├── main.py
    ├── config.py
    ├── state.py
    ├── prompts.py
    ├── llm_client.py
    ├── graph.py
    ├── nodes/
    └── tools/
```

不要把所有代码写到一个大脚本里。

每个节点单独一个文件。

每类工具单独一个文件。

---

## 8. 实现顺序

请严格按以下顺序实现。

### Step 1：项目骨架

创建：

```text
requirements.txt
.env.example
config.yaml
README.md
PROJECT_PLAN.md
AGENTS.md
src/__init__.py
src/main.py
src/config.py
src/state.py
src/prompts.py
src/llm_client.py
src/graph.py
src/nodes/
src/tools/
```

### Step 2：基础工具

先实现：

```text
src/tools/file_tools.py
src/tools/srt_tools.py
src/tools/merge_tools.py
```

并确保 SRT 解析、清洗、格式化和规则合并可单独运行。

### Step 3：ASR

实现：

```text
src/tools/asr_tools.py
src/nodes/asr_node.py
```

确保：

```text
input/input.mp3 → outputs/asr/zh_raw.srt
```

### Step 4：LLM 基础能力

实现：

```text
src/llm_client.py
src/prompts.py
```

LLM 调用必须支持：

```text
api_key
base_url
model
timeout
max_retries
```

### Step 5：字幕处理与翻译节点

实现：

```text
src/nodes/clean_srt_node.py
src/nodes/merge_and_critic_node.py
src/nodes/post_merge_node.py
src/nodes/summarize_node.py
src/nodes/translate_node.py
```

确保可以输出：

```text
outputs/translated/en_translated.srt
```

### Step 6：TTS 与真实时长检测

实现：

```text
src/tools/tts_tools.py
src/tools/duration_tools.py
src/nodes/tts_duration_node.py
```

确保可以输出：

```text
outputs/tts_segments/*.mp3
outputs/reports/tts_duration_report.json
```

### Step 7：局部反思修正

实现：

```text
src/nodes/reflection_node.py
```

要求：

1. 只修改有问题的字幕条目。
2. 不修改时间轴。
3. 不修改序号。
4. 修正后重新进入 TTS 生成与检测节点。

### Step 8：音频对齐与合并

实现：

```text
src/tools/audio_tools.py
src/nodes/audio_node.py
```

确保可以输出：

```text
outputs/audio/narration_en.wav
outputs/audio/narration_en.mp3
outputs/final/en_final.srt
outputs/reports/pipeline_report.json
```

### Step 9：主流程

实现：

```text
src/main.py
src/graph.py
```

运行方式必须是：

```bash
.venv\Scripts\python.exe -m main
```
或
```bash
.venv\Scripts\python.exe -m src\main
```

---

## 9. 代码风格要求

1. 使用 venv 环境 python解释器。
2. 使用类型标注。
3. 每个函数只做一件事。
4. 节点函数只负责组织流程，不写复杂工具逻辑。
5. 工具函数不依赖 LangGraph。
6. LLM 输出必须经过 SRT 清洗和解析。
7. 文件路径统一从 `config.yaml` 读取。
8. 不要在代码中硬编码 API Key。
9. 出错时给出明确错误信息。
10. 能继续处理的单条 TTS 错误不要让整个流程崩溃。

---

## 10. 禁止事项

禁止：

```text
把 MP4 当作当前版本输入
把 SRT 当作当前版本唯一输入
让 LLM 自主决定调用工具
实现 ReAct Agent
把 tools 暴露给 LLM
用 LLM 做字幕合并
用 LLM 做 TTS
用 LLM 做音频时长检测
让局部反思节点重写完整 SRT
让局部反思节点修改时间轴
把原始 input.mp3 当作背景音默认混入最终音频
把所有代码写进 main.py
```

特别注意：

原始 `input.mp3` 通常包含中文解说，因此默认不能作为背景音混入英文配音。只有当用户提供 `input/background.mp3` 且 `config.audio.mix_background=true` 时，才可以混背景。

---

## 11. Prompt 使用要求

所有 Prompt 放在：

```text
src/prompts.py
```

不要把 Prompt 散落在节点文件中。

必须包含：

```text
CRITIC_ZH_SRT_PROMPT
SUMMARIZE_PLOT_PROMPT
TRANSLATE_TO_ENGLISH_SRT_PROMPT
REFLECT_DURATION_ISSUES_PROMPT
```

节点中只引用 Prompt，不直接写长字符串。

---

## 12. 输出文件要求

每次运行后至少生成：

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
outputs/reports/asr_report.json
outputs/reports/tts_duration_report.json
outputs/reports/pipeline_report.json
```

---

## 13. 报告要求

`pipeline_report.json` 至少包含：

```json
{
  "input_mp3": "input/input.mp3",
  "asr_srt": "outputs/asr/zh_raw.srt",
  "raw_subtitle_count": 0,
  "cleaned_subtitle_count": 0,
  "merged_before_critic_count": 0,
  "corrected_count": 0,
  "merged_after_critic_count": 0,
  "translated_count": 0,
  "reflection_rounds": 0,
  "remaining_duration_issues": 0,
  "tts_segments": 0,
  "narration_wav": "outputs/audio/narration_en.wav",
  "narration_mp3": "outputs/audio/narration_en.mp3"
}
```

`tts_duration_report.json` 至少包含：

```json
{
  "total_segments": 0,
  "success_segments": 0,
  "failed_segments": 0,
  "duration_issue_count": 0,
  "issues": []
}
```

---

## 14. 验收标准

运行：

```bash
python -m src.main
```

必须满足：

1. 可以从 `input/input.mp3` 自动生成中文字幕 SRT。
2. 可以清洗并合并中文字幕。
3. 可以调用 LLM 审校中文字幕。
4. 可以生成剧情总结。
5. 可以翻译成英文 SRT。
6. 可以逐条生成英文 TTS。
7. 可以读取真实 TTS 时长。
8. 可以检测 TTS 与字幕时间轴的偏差。
9. 可以局部反思修正问题字幕。
10. 可以将所有 TTS 片段按时间轴合成完整英文配音。
11. 可以输出 `narration_en.mp3`。
12. 可以输出完整报告。
13. 所有中间文件都能在 `outputs/` 中找到。

---

## 15. 当前版本不做的事情

当前版本暂不实现：

```text
MP4 输入
视频封装
人声分离
背景音自动提取
多说话人识别
多音色配音
Web UI
批量处理
```

这些功能以后扩展，不要在第一版中实现。
