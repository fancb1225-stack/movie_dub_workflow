from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.config import config_path
from src.llm_client import LLMClient
from src.prompts import TRANSLATE_TO_ENGLISH_SRT_PROMPT
from src.state import SrtCue, WorkflowState
from src.tools.file_tools import write_json, write_text
from src.tools.srt_tools import clean_cues, format_srt, make_cue, parse_srt

logger = logging.getLogger(__name__)


def translate_to_english(state: WorkflowState) -> WorkflowState:
    logger.info("translate_to_english: entering node")
    config = state["config"]
    source_cues = state.get("corrected_cues", [])
    source_srt = state.get("corrected_srt", "")
    client = LLMClient.from_config(config)
    allow_fallback = _allow_mock_fallback(config)
    fallback_srt = format_srt(_fallback_translation(source_cues))

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
    else:
        translated_cues, translation_stats = _translate_with_llm_chunks(
            client, state, source_cues, config, allow_fallback, fallback_srt
        )
        used_fallback = False
        error = None

    final_srt = format_srt(translated_cues)
    write_text(config_path(config, "paths.translated_srt"), final_srt)
    write_text(config_path(config, "paths.final_srt"), final_srt)
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
) -> tuple[list[SrtCue], dict[str, object]]:
    translation_config = config.get("translation", {})
    chunk_size = int(translation_config.get("chunk_size", 0))
    chunks = _split_cues(source_cues, chunk_size)
    max_parallel = max(1, int(translation_config.get("max_parallel_chunks", 1)))
    worker_count = min(max_parallel, max(1, len(chunks)))
    if len(chunks) == 1:
        _, translated = _translate_chunk(client, state, chunks[0], 0, allow_fallback, fallback_srt)
    else:
        results: list[tuple[int, list[SrtCue]]] = []
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
                ): index
                for index, chunk in enumerate(chunks)
            }
            for future in as_completed(futures):
                results.append(future.result())
        translated = []
        for _, chunk_cues in sorted(results, key=lambda item: item[0]):
            translated.extend(chunk_cues)
    return translated, _translation_stats(config, len(chunks))


def _translate_chunk(
    client: LLMClient,
    state: WorkflowState,
    chunk_cues: list[SrtCue],
    chunk_index: int,
    allow_fallback: bool,
    fallback_srt: str,
) -> tuple[int, list[SrtCue]]:
    chunk_srt = format_srt(chunk_cues)
    translated_srt = client.complete(
        TRANSLATE_TO_ENGLISH_SRT_PROMPT,
        _build_translation_input(state, chunk_srt),
        fallback_srt if allow_fallback else "",
    )
    try:
        translated_cues = _parse_translation_or_raise(translated_srt, chunk_cues)
    except RuntimeError as exc:
        raise RuntimeError(f"LLM translation chunk {chunk_index + 1} failed: {exc}") from exc
    return chunk_index, translated_cues


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
        translated.append(make_cue(cue["index"], cue["start_ms"], cue["end_ms"], text))
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
        validated.append(
            make_cue(source["index"], source["start_ms"], source["end_ms"], cue["text"])
        )
    return validated
