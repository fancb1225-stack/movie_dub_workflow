# Claude Code Agent Instructions

## 项目边界

本项目现在包含两套并列能力：

1. 现有 LangGraph CLI 英文配音工作流。
2. 新增 FastAPI 媒体功能层，供后续 Web 页面调用。

新增媒体功能层不得插入当前 LangGraph 主流程。不要把 MP4、人声分离、视频封装等功能硬塞进 `src/graph.py`。

## Python 与依赖管理


- 使用项目 venv：`.venv\Scripts\python.exe`。
- 包管理优先使用 `uv`，备选 `pip`。
- 文件路径统一从 `config.yaml` 读取。

## 现有 CLI 工作流

当前 CLI 入口保持不变：

```bash
.venv\Scripts\python.exe -m src.main
```

除非用户明确要求，不要修改现有 LangGraph 节点顺序。

## 新增 FastAPI 媒体功能层

API 启动方式：

```bash
.venv\Scripts\python.exe -m uvicorn src.api.app:app --reload
```

新增功能包括：

- MP4/MP3 上传与 job 创建。
- MP4 音频提取。
- 本地人声/背景分离。
- 背景音自动提取。
- 占位式多说话人识别。
- 使用替换音频封装 MP4。

所有 job 必须隔离在：

```text
outputs/jobs/<job_id>/
```

## 实现规则

1. 使用类型标注。
2. API 路由只负责参数校验、调用 service、返回响应。
3. service 负责组织业务流程和写 job 报告。
4. tools 是普通函数模块，不依赖 FastAPI 或 LangGraph。
5. 不要在代码中硬编码 API Key。
6. 不要用 LLM 做媒体处理。
7. 不要把 tools 暴露给 LLM。
8. 不要实现 ReAct Agent。

## TDD 开发规范

后续开发按 TDD 执行：

1. 先写或更新失败的测试，明确目标行为。
2. 再实现最小代码让测试通过。
3. 最后做必要重构，保持测试通过。
4. 新增 tool/service/API 行为必须配套单元测试。
5. 能用纯函数测试覆盖的逻辑，不要只依赖端到端测试。
6. FastAPI 路由测试属于集成 smoke test；service 和 tools 必须有不依赖 Web 框架的单元测试。
7. 每次完成开发至少运行：

```bash
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_unit_*.py"
.venv\Scripts\python.exe -m compileall src tests
```

如果已安装测试依赖，还需要运行：

```bash
.venv\Scripts\python.exe -m pytest
```

## 本阶段禁止事项

- 不实现真实多音色配音。
- 不实现 pyannote 或声纹聚类式真实说话人识别。
- 不烧录硬字幕。
- 不封装软字幕轨。
- 不把原始中文解说音频当作背景音。
- 不修改 `src/graph.py` 来接入新增媒体功能。

## 媒体处理策略

- 背景音只能来自 Demucs 等分离结果中的 no-vocals/background stem。
- 如果人声分离失败，写入报告并尽可能继续其它 API 操作。
- 视频封装默认复制原视频流，只替换音频流。
- FFmpeg 查找顺序：`config.yaml` 配置路径 -> 项目内 `ffmpeg/bin` -> 系统 `PATH`。

## Prompt 规则

所有 Prompt 仍集中在：

```text
src/prompts.py
```

不要新增媒体处理 Prompt。媒体任务必须通过确定性的 tool/service 实现。
