"""The architecture document's agent-graph diagram is the graph `build_graph` compiles (ADR 0088).

The diagram in `docs/architecture.md` is hand-written, so its edges carry the reasons a route is
taken; this test keeps its edges the compiled graph's, so it cannot drift from the code.
"""

import re
from pathlib import Path
from typing import Any, cast

from langgraph.checkpoint.memory import InMemorySaver

from promopilot.agents import GraphTools, build_graph, checkpoint_serializer
from promopilot.domain import CompanyPolicy
from promopilot.llm import FakeProvider

REPO = Path(__file__).resolve().parents[3]
ARCHITECTURE = REPO / "docs" / "architecture.md"
STATE_DIAGRAM = re.compile(r"```mermaid\n(stateDiagram-v2\n.*?)```", re.DOTALL)
EDGE = re.compile(r"^\s*(\[\*\]|\w+)\s*-->\s*(\[\*\]|\w+)\s*(?::.*)?$")


def diagram_edges(markdown: str) -> set[tuple[str, str]]:
    """The edges of the document's one state diagram, with its states in the code's names."""
    diagrams = STATE_DIAGRAM.findall(markdown)
    assert len(diagrams) == 1, "docs/architecture.md must hold exactly one stateDiagram-v2"
    edges: set[tuple[str, str]] = set()
    for line in diagrams[0].splitlines():
        found = EDGE.match(line)
        if found:
            source, target = found.groups()
            edges.add(
                (
                    "__start__" if source == "[*]" else source.lower(),
                    "__end__" if target == "[*]" else target.lower(),
                )
            )
    return edges


def compiled_edges() -> set[tuple[str, str]]:
    """The edges of the graph the API runs; its tools are never called while compiling."""
    unused = cast(Any, None)
    graph = build_graph(
        GraphTools(brief_data=unused, planner=unused, sessions=unused, policy=CompanyPolicy()),
        FakeProvider([]),
        InMemorySaver(serde=checkpoint_serializer()),
    )
    return {(edge.source, edge.target) for edge in graph.get_graph().edges}


def test_the_diagram_parser_reads_start_end_and_labelled_edges() -> None:
    markdown = (
        "text\n```mermaid\nstateDiagram-v2\n  [*] --> Context\n"
        "  Context --> Clarify: missing\n  Done --> [*]\n```\n"
    )

    assert diagram_edges(markdown) == {
        ("__start__", "context"),
        ("context", "clarify"),
        ("done", "__end__"),
    }


def test_the_architecture_diagram_has_exactly_the_compiled_graphs_edges() -> None:
    documented = diagram_edges(ARCHITECTURE.read_text(encoding="utf-8"))

    assert documented == compiled_edges(), (
        "docs/architecture.md's agent graph differs from build_graph's: "
        f"missing {sorted(compiled_edges() - documented)}, "
        f"extra {sorted(documented - compiled_edges())}"
    )
