import ast
from pathlib import Path

import promopilot.domain

ALLOWED_IMPORTS = {"collections", "enum", "pydantic", "typing", "uuid", "promopilot"}


def test_domain_imports_nothing_that_could_do_io_or_numerics() -> None:
    package_dir = Path(promopilot.domain.__file__).parent
    imported: set[str] = set()
    for source in package_dir.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("promopilot.") and not node.module.startswith(
                    "promopilot.domain"
                ):
                    imported.add(node.module)
                imported.add(node.module.split(".")[0])

    assert imported <= ALLOWED_IMPORTS, f"domain must stay logic-free: {imported - ALLOWED_IMPORTS}"
