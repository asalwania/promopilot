"""The architecture document's agent-graph diagram is the graph `build_graph` compiles (ADR 0088).

The diagram in `docs/architecture.md` is hand-written, so its edges carry the reasons a route is
taken; this test keeps its edges the compiled graph's, so it cannot drift from the code.
"""

import ast
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


# The module-dependency diagram (ADR 0092). The foundation modules (`domain`, `economics`, `config`)
# are left out because every module may use them; so are `cassettes`, `demo` and `logs` (wiring and
# scripts) and `evals` (the offline harness). The diagram shows the transitive reduction, so an
# arrow means "uses directly, and not only through another module in the diagram".
PACKAGE = REPO / "backend" / "src" / "promopilot"
FOUNDATION = {"domain", "economics", "config"}
MODULE_DIAGRAM = re.compile(
    r"```mermaid\n(flowchart [A-Z]+\n\s*%% module-dependencies\n.*?)```", re.DOTALL
)
MODULE_EDGE = re.compile(r"^\s*(\w+)\s*-->\s*(\w+)\s*$")


def documented_module_edges(markdown: str) -> set[tuple[str, str]]:
    """The `user --> used` edges of the document's one module-dependency diagram."""
    diagrams = MODULE_DIAGRAM.findall(markdown)
    assert len(diagrams) == 1, "docs/architecture.md needs exactly one module-dependency diagram"
    edges: set[tuple[str, str]] = set()
    for line in diagrams[0].splitlines():
        found = MODULE_EDGE.match(line)
        if found:
            edges.add((found.group(1), found.group(2)))
    return edges


def import_edges(package: Path) -> dict[str, set[str]]:
    """Which top-level modules of the package each one imports, from its source."""
    edges: dict[str, set[str]] = {}
    for source in package.rglob("*.py"):
        parts = source.relative_to(package).parts
        user = parts[0] if len(parts) > 1 else source.stem
        if user == "__init__":
            continue
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
                else []
            )
            for name in names:
                path = name.split(".")
                if path[0] == "promopilot" and len(path) > 1 and path[1] != user:
                    edges.setdefault(user, set()).add(path[1])
    return edges


def transitive_reduction(edges: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """The edges that no longer path through another node already gives."""
    uses: dict[str, set[str]] = {}
    for user, used in edges:
        uses.setdefault(user, set()).add(used)
    return {edge for edge in edges if edge[1] not in reachable_without(uses, edge)}


def reachable_without(uses: dict[str, set[str]], edge: tuple[str, str]) -> set[str]:
    """Everything `edge`'s user reaches without taking `edge` itself."""
    user, used = edge
    seen: set[str] = set()
    stack = [nxt for nxt in uses.get(user, set()) if nxt != used]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(uses.get(node, set()))
    return seen


def real_module_edges(nodes: set[str]) -> set[tuple[str, str]]:
    imports = import_edges(PACKAGE)
    direct = {
        (user, used)
        for user, used_set in imports.items()
        for used in used_set
        if user in nodes and used in nodes
    }
    return transitive_reduction(direct)


def test_transitive_reduction_keeps_only_the_direct_edges_nothing_else_implies() -> None:
    edges = {("a", "b"), ("b", "c"), ("a", "c"), ("a", "d")}

    assert transitive_reduction(edges) == {("a", "b"), ("b", "c"), ("a", "d")}


def test_the_module_diagram_has_exactly_the_real_module_dependencies() -> None:
    documented = documented_module_edges(ARCHITECTURE.read_text(encoding="utf-8"))
    nodes = {name for edge in documented for name in edge}
    assert not nodes & FOUNDATION, "the foundation modules are left out of the diagram"
    real = real_module_edges(nodes)

    assert documented == real, (
        "docs/architecture.md's module diagram differs from the imports under src/promopilot: "
        f"missing {sorted(real - documented)}, extra {sorted(documented - real)}"
    )


def test_every_node_in_the_module_diagram_is_a_module_of_the_package() -> None:
    documented = documented_module_edges(ARCHITECTURE.read_text(encoding="utf-8"))
    modules = {path.name for path in PACKAGE.iterdir() if path.is_dir()} | {
        path.stem for path in PACKAGE.glob("*.py")
    }

    assert {name for edge in documented for name in edge} <= modules
