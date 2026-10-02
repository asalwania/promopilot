"""Every code location, test and scenario the nine-blocker matrix cites exists (#77, ADR 0091).

`docs/nine-blocker.md` is a claim a judge checks by opening what it cites. A path, a function or a
test that was renamed since the document was written would make the claim false without anyone
noticing, so this test reads the document and resolves each citation. It reads no numbers.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
PACKAGE = BACKEND / "src" / "promopilot"
DOC = REPO / "docs" / "nine-blocker.md"
TEXT = DOC.read_text(encoding="utf-8")

CODE_SPANS = re.findall(r"`([^`\n]+)`", TEXT)
PYTEST_ID = re.compile(r"^(tests/[\w/]+\.py)::(test_\w+)$")
# A cited file followed by the functions or classes in it: "`optimizer/solver.py` `solve`".
FILE_THEN_SYMBOLS = re.compile(r"`([\w/]+\.py)` ((?:`\w+`(?:, | and )?)+)")


def defines(source: str, name: str) -> bool:
    pattern = rf"^\s*(?:async\s+)?(?:def|class)\s+{re.escape(name)}\b|^{re.escape(name)}\b"
    return re.search(pattern, source, re.MULTILINE) is not None


def source_file(cited: str) -> Path | None:
    """The file a citation names: backend source paths are relative to the package."""
    for root in (PACKAGE, BACKEND, REPO):
        if (root / cited).is_file():
            return root / cited
    return None


def test_the_document_cites_enough_to_be_checked() -> None:
    pytest_ids = [span for span in CODE_SPANS if PYTEST_ID.match(span)]
    assert len(pytest_ids) >= 60
    assert len(FILE_THEN_SYMBOLS.findall(TEXT)) >= 25


def test_every_cited_pytest_id_names_a_test_function_that_exists() -> None:
    missing = []
    for span in CODE_SPANS:
        match = PYTEST_ID.match(span)
        if match is None:
            continue
        path, name = match.groups()
        file = BACKEND / path
        if not file.is_file() or not defines(file.read_text(encoding="utf-8"), name):
            missing.append(span)
    assert missing == []


def test_every_cited_source_file_exists() -> None:
    missing = [
        span
        for span in CODE_SPANS
        if re.fullmatch(r"[\w/.-]+\.(?:py|ts|tsx|yaml)", span)
        and "::" not in span
        and source_file(span) is None
    ]
    assert missing == []


def test_every_cited_function_or_class_is_defined_in_the_file_named_before_it() -> None:
    missing = []
    for path, symbols in FILE_THEN_SYMBOLS.findall(TEXT):
        file = source_file(path)
        if file is None:
            missing.append(path)
            continue
        source = file.read_text(encoding="utf-8")
        missing += [
            f"{path} {name}"
            for name in re.findall(r"`(\w+)`", symbols)
            if not defines(source, name)
        ]
    assert missing == []


def test_every_cited_eval_scenario_exists() -> None:
    scenarios = {path.stem for path in (BACKEND / "evals" / "scenarios").glob("*.yaml")}
    named = [span for span in CODE_SPANS if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", span)]
    assert named, "the document cites no scenario"
    assert [span for span in named if span not in scenarios] == []


def test_every_relative_link_resolves() -> None:
    links = re.findall(r"\]\((?!https?:|#)([^)#\s]+)", TEXT)
    assert [link for link in links if not (DOC.parent / link).exists()] == []
