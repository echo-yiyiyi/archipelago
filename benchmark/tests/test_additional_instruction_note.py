"""Check the prompt append block without starting a benchmark environment."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("enabled", [False, True])
def test_optional_user_note(enabled):
    source = Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(source.read_text())
    block = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and "USER_ALLOW_ADDITIONAL_INSTRUCTION" in ast.unparse(node.test)
    )
    scope = {
        "os": SimpleNamespace(environ={"USER_ALLOW_ADDITIONAL_INSTRUCTION": "1" if enabled else "0"}),
        "user_prompt": "Original task prompt",
        "log": lambda message: None,
    }
    exec(compile(ast.Module(body=[block], type_ignores=[]), str(source), "exec"), scope)
    assert scope["user_prompt"].startswith("Original task prompt")
    if enabled:
        assert "I may include additional task instructions in some files" in scope["user_prompt"]
        assert "special cases and different scenarios" in scope["user_prompt"]
    else:
        assert scope["user_prompt"] == "Original task prompt"
