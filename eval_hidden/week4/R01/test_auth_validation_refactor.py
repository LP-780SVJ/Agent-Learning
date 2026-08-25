import ast
from pathlib import Path


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function: {name}")


def _called_names(function: ast.FunctionDef) -> list[str]:
    names: list[str] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.append(node.func.attr)
    return names


def test_both_public_methods_use_the_extracted_private_helper() -> None:
    source = Path("src/auth/service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    helper = _function(tree, "_decode_refresh")
    refresh = _function(tree, "refresh_session")
    revoke = _function(tree, "revoke_session")

    assert _called_names(helper).count("decode_refresh_payload") == 1
    assert "_decode_refresh" in _called_names(refresh)
    assert "_decode_refresh" in _called_names(revoke)
    assert "decode_refresh_payload" not in _called_names(refresh)
    assert "decode_refresh_payload" not in _called_names(revoke)
