from __future__ import annotations

import logging
from typing import Any, Iterator, Protocol

from src.nodes.audio_node import align_and_merge_audio
from src.nodes.clean_srt_node import clean_srt
from src.nodes.merge_zh_asr_node import merge_zh_asr_srt
from src.nodes.merge_and_critic_node import critic_srt
from src.nodes.restitch_merge_cuts_node import restitch_merge_cuts
from src.nodes.reflection_node import reflect_duration_issues
from src.nodes.summarize_node import summarize_plot
from src.nodes.translate_node import translate_to_english
from src.nodes.tts_duration_node import tts_generate_and_detect
from src.state import WorkflowState

logger = logging.getLogger(__name__)


class RunnableWorkflow(Protocol):
    def invoke(self, state: WorkflowState) -> WorkflowState:
        ...

    def stream(self, state: WorkflowState) -> Iterator[dict[str, WorkflowState]]:
        ...


def build_workflow(config: dict[str, Any], resume_from: str | None = None) -> RunnableWorkflow:
    try:
        return _build_langgraph_workflow(config, resume_from=resume_from)
    except ImportError:
        return SequentialWorkflow(config, resume_from=resume_from)


def should_reflect_or_finish(state: WorkflowState) -> str:
    config = state["config"]
    max_rounds = int(config.get("duration", {}).get("max_reflection_rounds", 1))
    issues = state.get("duration_issues")
    rounds = int(state.get("reflection_rounds", 0))
    logger.info(
        "should_reflect_or_finish: issues=%d, rounds=%d, max_rounds=%d -> %s",
        len(issues) if issues else 0, rounds, max_rounds,
        "reflect" if (issues and rounds < max_rounds) else "finish",
    )
    if issues and rounds < max_rounds:
        return "reflect"
    return "finish"


NODE_ORDER = [
    "merge_zh_asr_srt",
    "restitch_merge_cuts",
    "clean_srt",
    "critic_srt",
    "summarize_plot",
    "translate_to_english",
    "tts_generate_and_detect",
    "reflect_duration_issues",
    "align_and_merge_audio",
]


class SequentialWorkflow:
    def __init__(self, config: dict[str, Any], resume_from: str | None = None):
        self.config = config
        self.resume_from = resume_from

    def invoke(self, state: WorkflowState) -> WorkflowState:
        for chunk in self.stream(state):
            state = next(iter(chunk.values()))
        return state

    def stream(self, state: WorkflowState) -> Iterator[dict[str, WorkflowState]]:
        start_index = 0
        if self.resume_from:
            try:
                start_index = NODE_ORDER.index(self.resume_from)
            except ValueError:
                start_index = 0

        nodes = [
            ("merge_zh_asr_srt", merge_zh_asr_srt),
            ("restitch_merge_cuts", restitch_merge_cuts),
            ("clean_srt", clean_srt),
            ("critic_srt", critic_srt),
            ("summarize_plot", summarize_plot),
            ("translate_to_english", translate_to_english),
            ("tts_generate_and_detect", tts_generate_and_detect),
        ]
        for i, (name, fn) in enumerate(nodes):
            if i < start_index:
                continue
            logger.info("SequentialWorkflow: running node '%s'", name)
            state = fn(state)
            logger.info("SequentialWorkflow: node '%s' completed", name)
            yield {name: state}

        while should_reflect_or_finish(state) == "reflect":
            state = reflect_duration_issues(state)
            yield {"reflect_duration_issues": state}
            state = tts_generate_and_detect(state)
            yield {"tts_generate_and_detect": state}

        state = align_and_merge_audio(state)
        yield {"align_and_merge_audio": state}
        return


def _build_langgraph_workflow(
    config: dict[str, Any], resume_from: str | None = None
) -> RunnableWorkflow:
    from langgraph.graph import END, StateGraph

    graph = StateGraph(WorkflowState)
    graph.add_node("merge_zh_asr_srt", merge_zh_asr_srt)
    graph.add_node("restitch_merge_cuts", restitch_merge_cuts)
    graph.add_node("clean_srt", clean_srt)
    graph.add_node("critic_srt", critic_srt)
    graph.add_node("summarize_plot", summarize_plot)
    graph.add_node("translate_to_english", translate_to_english)
    graph.add_node("tts_generate_and_detect", tts_generate_and_detect)
    graph.add_node("reflect_duration_issues", reflect_duration_issues)
    graph.add_node("align_and_merge_audio", align_and_merge_audio)

    entry_point = resume_from if resume_from in NODE_ORDER else "merge_zh_asr_srt"
    graph.set_entry_point(entry_point)
    graph.add_edge("merge_zh_asr_srt", "restitch_merge_cuts")
    graph.add_edge("restitch_merge_cuts", "clean_srt")
    graph.add_edge("clean_srt", "critic_srt")
    graph.add_edge("critic_srt", "summarize_plot")
    graph.add_edge("summarize_plot", "translate_to_english")
    graph.add_edge("translate_to_english", "tts_generate_and_detect")
    graph.add_conditional_edges(
        "tts_generate_and_detect",
        should_reflect_or_finish,
        {
            "reflect": "reflect_duration_issues",
            "finish": "align_and_merge_audio",
        },
    )
    graph.add_edge("reflect_duration_issues", "tts_generate_and_detect")
    graph.add_edge("align_and_merge_audio", END)
    return graph.compile()
