from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.config import config_path
from src.llm_client import LLMClient
from src.prompt_registry import prompt_for
from src.state import SrtCue, WorkflowState
from src.tools.cue_tools import copy_timing_and_speaker
from src.tools.file_tools import write_json, write_text
from src.tools.srt_tools import clean_cues, format_srt, parse_srt

logger = logging.getLogger(__name__)


def translate_to_english(state: WorkflowState) -> WorkflowState:
    logger.info("translate_to_english: entering node")
    config = state["config"]
    source_cues = state.get("corrected_cues", [])
    source_srt = state.get("corrected_srt", "")
    client = LLMClient.from_config(config)
    allow_fallback = _allow_mock_fallback(config)
    fallback_srt = format_srt(_fallback_translation(source_cues))
    translate_prompt = prompt_for(config, "translate_to_english_srt")

    if not client.enabled():
        if not allow_fallback:
            raise RuntimeError(
                "LLM translation is not configured. Set LLM_API_KEY, "
                "LLM_BASE_URL, and LLM_MODEL, or set "
                "translation.allow_mock_fallback=true for tests only."
            )
        translated_srt = fallback_srt
        translated_cues = _parse_translation_or_raise(translated_srt, source_cues)
        used_fallback = True
        error = "LLM translation is disabled; mock fallback was explicitly allowed."
        translation_stats = _translation_stats(config, 1)
        failed_chunks: list[int] = []
    else:
        translated_cues, translation_stats, failed_chunks = _translate_with_llm_chunks(
            client, state, source_cues, config, allow_fallback, fallback_srt, translate_prompt
        )
        used_fallback = False
        error = None

    final_srt = format_srt(translated_cues)
    write_text(config_path(config, "paths.translated_srt"), final_srt)
    write_text(config_path(config, "paths.final_srt"), final_srt)
    write_json(config_path(config, "paths.translated_srt").with_suffix(".cues.json"), translated_cues)
    write_json(config_path(config, "paths.final_srt").with_suffix(".cues.json"), translated_cues)
    report_path = config_path(config, "paths.reports_dir") / "translation_report.json"
    write_json(
        report_path,
        {
            "provider": "llm" if client.enabled() else "mock",
            "used_fallback": used_fallback,
            "allow_mock_fallback": allow_fallback,
            "chunked": bool(translation_stats["chunked"]),
            "chunk_size": translation_stats["chunk_size"],
            "chunk_count": translation_stats["chunk_count"],
            "max_parallel_chunks": translation_stats["max_parallel_chunks"],
            "parallel": translation_stats["parallel"],
            "source_subtitle_count": len(source_cues),
            "output_subtitle_count": len(translated_cues),
            "failed_chunks": failed_chunks,
            "error": error,
        },
    )
    state["en_translated_cues"] = translated_cues
    state["en_translated_srt"] = final_srt
    state["final_cues"] = translated_cues
    state["final_srt"] = final_srt
    state.setdefault("reports", {})["translation_report"] = str(report_path)
    return state


def _allow_mock_fallback(config: dict) -> bool:
    return bool(config.get("translation", {}).get("allow_mock_fallback", False))


def _build_translation_input(state: WorkflowState, source_srt: str) -> str:
    summary = state.get("plot_summary", "")
    return f"Plot summary:\n{summary}\n\nChinese SRT:\n{source_srt}"


def _translate_with_llm_chunks(
    client: LLMClient,
    state: WorkflowState,
    source_cues: list[SrtCue],
    config: dict,
    allow_fallback: bool,
    fallback_srt: str,
    translate_prompt: str,
) -> tuple[list[SrtCue], dict[str, object], list[int]]:
    translation_config = config.get("translation", {})
    chunk_size = int(translation_config.get("chunk_size", 0))
    chunks = _split_cues(source_cues, chunk_size)
    max_parallel = max(1, int(translation_config.get("max_parallel_chunks", 1)))
    worker_count = min(max_parallel, max(1, len(chunks)))
    if len(chunks) == 1:
        idx, translated, failed = _translate_chunk(
            client, state, chunks[0], 0, allow_fallback, fallback_srt, config, translate_prompt
        )
        results = [(idx, translated)]
        failed_chunks = [1] if failed else []
    else:
        raw: list[tuple[int, list[SrtCue]]] = []
        failed_chunks: list[int] = []
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    _translate_chunk,
                    client,
                    state,
                    chunk,
                    index,
                    allow_fallback,
                    fallback_srt,
                    config,
                    translate_prompt,
                ): index
                for index, chunk in enumerate(chunks)
            }
            for future in as_completed(futures):
                index, translated, failed = future.result()
                raw.append((index, translated))
                if failed:
                    failed_chunks.append(index + 1)
        raw.sort(key=lambda item: item[0])
        results = raw
    translated = []
    for _, chunk_cues in results:
        translated.extend(chunk_cues)
    return translated, _translation_stats(config, len(chunks)), sorted(failed_chunks)


def _translate_chunk(
    client: LLMClient,
    state: WorkflowState,
    chunk_cues: list[SrtCue],
    chunk_index: int,
    allow_fallback: bool,
    fallback_srt: str,
    config: dict,
    translate_prompt: str,
) -> tuple[int, list[SrtCue], bool]:
    """翻译单个分块，失败时按 chunk_max_retries 重试；耗尽后用源文本占位。

    返回 (chunk_index, translated_cues, failed)。failed=True 表示该块最终用
    源文本占位（条数与源一致，保证整体对齐），而非抛错中断整次翻译。
    """
    max_retries = int(config.get("translation", {}).get("chunk_max_retries", 3))
    chunk_srt = format_srt(chunk_cues)
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        translated_srt = client.complete(
            translate_prompt,
            _build_translation_input(state, chunk_srt),
            fallback_srt if allow_fallback else "",
        )
        try:
            translated_cues = _parse_translation_or_raise(translated_srt, chunk_cues)
            return chunk_index, translated_cues, False
        except RuntimeError as exc:
            last_error = exc
            logger.warning(
                "translate chunk %d attempt %d/%d failed: %s",
                chunk_index + 1, attempt + 1, max_retries + 1, exc,
            )
    # 重试耗尽：用源文本占位，保证条数对齐，不中断整体翻译
    logger.error(
        "translate chunk %d exhausted retries (%s); falling back to source text",
        chunk_index + 1, last_error,
    )
    placeholder = [copy_timing_and_speaker(cue, cue["text"]) for cue in chunk_cues]
    return chunk_index, placeholder, True


def _split_cues(cues: list[SrtCue], chunk_size: int) -> list[list[SrtCue]]:
    if chunk_size <= 0:
        return [cues]
    return [cues[pos : pos + chunk_size] for pos in range(0, len(cues), chunk_size)] or [[]]


def _translation_stats(config: dict, chunk_count: int) -> dict[str, object]:
    translation_config = config.get("translation", {})
    chunk_size = int(translation_config.get("chunk_size", 0))
    max_parallel = max(1, int(translation_config.get("max_parallel_chunks", 1)))
    return {
        "chunked": chunk_size > 0 and chunk_count > 1,
        "chunk_size": chunk_size,
        "chunk_count": chunk_count,
        "max_parallel_chunks": max_parallel,
        "parallel": chunk_count > 1 and max_parallel > 1,
    }


def _fallback_translation(cues: list[SrtCue]) -> list[SrtCue]:
    templates = [
        "The story opens as the main character steps into a decisive moment.",
        "The conflict grows, and the characters' goals become clear.",
        "A difficult choice pushes the plot into a tense turn.",
        "The story closes as the central mystery is answered.",
    ]
    translated: list[SrtCue] = []
    for cue in cues:
        text = templates[(cue["index"] - 1) % len(templates)]
        translated.append(copy_timing_and_speaker(cue, text))
    return translated


def _parse_translation_or_raise(
    srt_text: str, source_cues: list[SrtCue]
) -> list[SrtCue]:
    cues = clean_cues(parse_srt(srt_text))
    if not cues or len(cues) != len(source_cues):
        raise RuntimeError(
            "LLM translation output is invalid: expected "
            f"{len(source_cues)} SRT cues, got {len(cues)}."
        )
    validated: list[SrtCue] = []
    for cue, source in zip(cues, source_cues):
        validated.append(copy_timing_and_speaker(source, cue["text"]))
    return validated
