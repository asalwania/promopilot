"""`promopilot.agents` contains no business arithmetic: every number an agent uses comes from
a tool (SPEC §13.4, ADR 0002, ADR 0049).

The tools themselves (`promopilot.agents.tools`) are the seam where agents reach deterministic
computation (ADR 0025), so they are left out. Everywhere else in the package, arithmetic
operators and numeric built-ins are refused, except string and list building and the few
uses listed below, each with its reason.
"""

import ast
from pathlib import Path

import promopilot.agents

ARITHMETIC = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.MatMult)
NUMERIC_CALLS = {"sum", "round", "abs", "min", "max", "pow", "divmod", "fmean", "mean", "fsum"}
NUMERIC_MODULES = {"math", "statistics", "numpy", "decimal", "fractions", "scipy"}

ALLOWED_MODULES = {
    "resolution.py": "brief-phrase similarity scores and holiday week runs: text matching, "
    "not business numbers (ADR 0032)",
    "trace.py": "trace bookkeeping: event numbers in memory, node durations and summary "
    "cut-offs; every cost comes from the LLM layer's usage meter (ADR 0047)",
}
ALLOWED = {
    ("context.py", "as_of_week + WEEK_TABLE_WEEKS"): "the weeks the prompt's week table lists",
    ("explainer.py", "round(amount)"): "shows a tool's number in whole units (ADR 0046 D13)",
    ("explainer.py", "round(abs(amount))"): "shows a tool's rupees in whole rupees",
    ("explainer.py", "abs(amount)"): "the sign is written separately",
    ("explainer.py", "parts += _constraint_sentences(revision)"): "list building",
    ("explainer.py", "parts += notes"): "list building",
    ("explainer.py", "parts += _safety_sentences(revision)"): "list building",
    ("graph.py", "state.iteration + 1"): "counts the Planner's runs, for the Critic loop cap",
    ("graph.py", "route + list(snapshot.next)"): "list building",
    ("graph.py", "previous.number + 1"): "numbers plan revisions, one per planning round "
    "(ADR 0052)",
    ("recording.py", "cassette_dir / cassette.name"): "a file path",
}


def _is_text_or_list(node: ast.expr) -> bool:
    return isinstance(
        node, ast.Constant | ast.JoinedStr | ast.List | ast.ListComp | ast.Tuple
    ) and not (isinstance(node, ast.Constant) and not isinstance(node.value, str))


def _findings(source: Path) -> list[str]:
    text = source.read_text(encoding="utf-8")
    found = []
    for node in ast.walk(ast.parse(text)):
        segment = ast.get_source_segment(text, node) or ""
        if (source.name, segment) in ALLOWED:
            continue
        if isinstance(node, ast.BinOp) and isinstance(node.op, ARITHMETIC):
            if not (_is_text_or_list(node.left) or _is_text_or_list(node.right)):
                found.append(f"{source.name}:{node.lineno}: {segment}")
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ARITHMETIC):
            if not _is_text_or_list(node.value):
                found.append(f"{source.name}:{node.lineno}: {segment}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in NUMERIC_CALLS
        ):
            found.append(f"{source.name}:{node.lineno}: {segment}")
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names = [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            names += [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            for name in names:
                if name.split(".")[0] in NUMERIC_MODULES:
                    found.append(f"{source.name}:{node.lineno}: imports {name}")
    return sorted(found, key=lambda finding: int(finding.split(":")[1]))


def agent_sources() -> list[Path]:
    package = Path(promopilot.agents.__file__).parent
    return sorted(
        source
        for source in package.rglob("*.py")
        if "tools" not in source.relative_to(package).parts[:-1]
        and source.name not in ALLOWED_MODULES
    )


def test_the_agents_package_has_no_business_arithmetic() -> None:
    sources = agent_sources()
    assert any(source.name == "planner_agent.py" for source in sources)

    found = [finding for source in sources for finding in _findings(source)]

    assert found == [], "numbers must come from tools (ADR 0002):\n" + "\n".join(found)


def test_the_check_catches_arithmetic(tmp_path: Path) -> None:
    source = tmp_path / "planner.py"
    source.write_text(
        "import numpy as np\n"
        "margin = profit / revenue\n"
        "total += cost\n"
        "best = max(values)\n"
        "label = 'plan ' + name\n"
        "route = [a] + rest\n",
        encoding="utf-8",
    )

    assert _findings(source) == [
        "planner.py:1: imports numpy",
        "planner.py:2: profit / revenue",
        "planner.py:3: total += cost",
        "planner.py:4: max(values)",
    ]
