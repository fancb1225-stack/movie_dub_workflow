from __future__ import annotations

import sys
import types
import unittest

from src.graph import build_workflow


class GraphResumeTests(unittest.TestCase):
    def test_langgraph_workflow_uses_resume_from_as_entry_point(self) -> None:
        fake_module, fake_graphs = _fake_langgraph_module()
        original_langgraph = sys.modules.get("langgraph")
        original_langgraph_graph = sys.modules.get("langgraph.graph")
        sys.modules["langgraph"] = types.ModuleType("langgraph")
        sys.modules["langgraph.graph"] = fake_module
        try:
            build_workflow({}, resume_from="translate_to_english")
        finally:
            _restore_module("langgraph", original_langgraph)
            _restore_module("langgraph.graph", original_langgraph_graph)

        self.assertEqual(fake_graphs[0].entry_point, "translate_to_english")

    def test_langgraph_workflow_defaults_to_first_node_entry_point(self) -> None:
        fake_module, fake_graphs = _fake_langgraph_module()
        original_langgraph = sys.modules.get("langgraph")
        original_langgraph_graph = sys.modules.get("langgraph.graph")
        sys.modules["langgraph"] = types.ModuleType("langgraph")
        sys.modules["langgraph.graph"] = fake_module
        try:
            build_workflow({})
        finally:
            _restore_module("langgraph", original_langgraph)
            _restore_module("langgraph.graph", original_langgraph_graph)

        self.assertEqual(fake_graphs[0].entry_point, "merge_zh_asr_srt")


def _fake_langgraph_module() -> tuple[types.ModuleType, list["FakeStateGraph"]]:
    fake_graphs: list[FakeStateGraph] = []
    module = types.ModuleType("langgraph.graph")
    module.END = "__end__"

    class StateGraphFactory:
        def __new__(cls, state_type: object) -> "FakeStateGraph":
            graph = FakeStateGraph(state_type)
            fake_graphs.append(graph)
            return graph

    module.StateGraph = StateGraphFactory
    return module, fake_graphs


class FakeStateGraph:
    def __init__(self, state_type: object):
        self.state_type = state_type
        self.entry_point: str | None = None

    def add_node(self, name: str, fn: object) -> None:
        return None

    def set_entry_point(self, name: str) -> None:
        self.entry_point = name

    def add_edge(self, source: str, target: str) -> None:
        return None

    def add_conditional_edges(
        self,
        source: str,
        condition: object,
        edges: dict[str, str],
    ) -> None:
        return None

    def compile(self) -> "FakeStateGraph":
        return self


def _restore_module(name: str, original: types.ModuleType | None) -> None:
    if original is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


if __name__ == "__main__":
    unittest.main()
