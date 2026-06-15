from __future__ import annotations

from typing import Any, Protocol

from src.nodes.asr_node import asr_mp3_to_srt
from src.nodes.audio_node import align_and_merge_audio
from src.nodes.clean_srt_node import clean_srt
from src.nodes.merge_and_critic_node import merge_and_critic
from src.nodes.post_merge_node import post_merge
from src.nodes.reflection_node import reflect_duration_issues
from src.nodes.summarize_node import summarize_plot
from src.nodes.translate_node import translate_to_english
from src.nodes.tts_duration_node import tts_generate_and_detect
from src.state import WorkflowState


class RunnableWorkflow(Protocol):
    def invoke(self, state: WorkflowState) -> WorkflowState:
        ...


def build_workflow(config: dict[str, Any]) -> RunnableWorkflow:
    try:
        return _build_langgraph_workflow(config)
    except ImportError:
        return SequentialWorkflow(config)


def should_reflect_or_finish(state: WorkflowState) -> str:
    config = state["config"]
    max_rounds = int(config.get("duration", {}).get("max_reflection_rounds", 1))
    if state.get("duration_issues") and int(state.get("reflection_rounds", 0)) < max_rounds:
        return "reflect"
    return "finish"


class SequentialWorkflow:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def invoke(self, state: WorkflowState) -> WorkflowState:
        state = asr_mp3_to_srt(state)
        state = clean_srt(state)
        state = merge_and_critic(state)
        state = post_merge(state)
        state = summarize_plot(state)
        state = translate_to_english(state)
        while True:
            state = tts_generate_and_detect(state)
            if should_reflect_or_finish(state) != "reflect":
                break
            state = reflect_duration_issues(state)
        state = align_and_merge_audio(state)
        return state


def _build_langgraph_workflow(config: dict[str, Any]) -> RunnableWorkflow:
    from langgraph.graph import END, StateGraph

    graph = StateGraph(WorkflowState)
    graph.add_node("asr_mp3_to_srt", asr_mp3_to_srt)
    graph.add_node("clean_srt", clean_srt)
    graph.add_node("merge_and_critic", merge_and_critic)
    graph.add_node("post_merge", post_merge)
    graph.add_node("summarize_plot", summarize_plot)
    graph.add_node("translate_to_english", translate_to_english)
    graph.add_node("tts_generate_and_detect", tts_generate_and_detect)
    graph.add_node("reflect_duration_issues", reflect_duration_issues)
    graph.add_node("align_and_merge_audio", align_and_merge_audio)

    graph.set_entry_point("asr_mp3_to_srt")
    graph.add_edge("asr_mp3_to_srt", "clean_srt")
    graph.add_edge("clean_srt", "merge_and_critic")
    graph.add_edge("merge_and_critic", "post_merge")
    graph.add_edge("post_merge", "summarize_plot")
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

