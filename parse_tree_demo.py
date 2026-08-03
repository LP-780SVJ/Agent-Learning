# parse_tree_demo.py

from __future__ import annotations

import ast
from textwrap import dedent

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser


PY_LANGUAGE = Language(tspython.language())
TS_PARSER = Parser(PY_LANGUAGE)


SAMPLES = {
    "function": """
        def add(a: int, b: int = 0) -> int:
            return a + b
    """,
    "class": """
        class UserService(BaseService):
            def get_user(self, user_id: int):
                return self.repository.find(user_id)
    """,
    "import": """
        import os
        import json as json_lib
        from pathlib import Path
        from app.services import UserService as Service
    """,
    "call": """
        result = service.create_user(
            name="Alice",
            active=True,
        )
    """,
    "exception": """
        try:
            user = repository.find(user_id)
            if user is None:
                raise ValueError("user not found")
        except ValueError as exc:
            logger.warning(str(exc))
        finally:
            repository.close()
    """,
}


def print_tree_sitter_node(
    node: Node,
    source: bytes,
    depth: int = 0,
    max_text_length: int = 50,
) -> None:
    """打印所有 Tree-sitter 节点，包括匿名节点。"""
    indent = "  " * depth

    raw_text = source[node.start_byte:node.end_byte]
    text = raw_text.decode("utf-8", errors="replace")
    text = text.replace("\n", "\\n")

    if len(text) > max_text_length:
        text = text[:max_text_length] + "..."

    node_kind = "named" if node.is_named else "anonymous"

    print(
        f"{indent}{node.type} "
        f"[{node_kind}] "
        f"{node.start_point}->{node.end_point} "
        f"text={text!r}"
    )

    for child in node.children:
        print_tree_sitter_node(
            child,
            source,
            depth + 1,
            max_text_length,
        )


def inspect_sample(name: str, source: str) -> None:
    source = dedent(source).lstrip()
    source_bytes = source.encode("utf-8")

    print("=" * 100)
    print(f"SAMPLE: {name}")
    print("-" * 100)
    print(source)

    print("\n[Python AST]")
    try:
        python_tree = ast.parse(source)
        print(
            ast.dump(
                python_tree,
                indent=2,
                include_attributes=True,
            )
        )
    except SyntaxError as exc:
        print(f"SyntaxError: {exc}")

    print("\n[Tree-sitter S-expression]")
    tree_sitter_tree = TS_PARSER.parse(source_bytes)
    print(str(tree_sitter_tree.root_node))

    print("\n[Tree-sitter full nodes]")
    print_tree_sitter_node(
        tree_sitter_tree.root_node,
        source_bytes,
    )

    print(
        "\nTree-sitter has error:",
        tree_sitter_tree.root_node.has_error,
    )


def main() -> None:
    for name, source in SAMPLES.items():
        inspect_sample(name, source)


if __name__ == "__main__":
    main()