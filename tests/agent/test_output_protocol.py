from __future__ import annotations

import pytest

from codeteam.agent.protocol import (
    ModelOutputDialect,
    ModelOutputNormalizationError,
    normalize_model_output,
)


def test_normalizes_bare_json_without_changing_payload() -> None:
    raw = '{"tool_calls":[{"name":"git_status","arguments":{}}]}'

    result = normalize_model_output(raw)

    assert result.dialect is ModelOutputDialect.JSON
    assert result.payload == {
        "tool_calls": [{"name": "git_status", "arguments": {}}]
    }


def test_normalizes_single_markdown_json_fence() -> None:
    raw = """```json
{"status":"failed","summary":"stopped","tests_passed":false,"error":"x"}
```"""

    result = normalize_model_output(raw)

    assert result.dialect is ModelOutputDialect.MARKDOWN_JSON
    assert result.payload["status"] == "failed"


def test_normalizes_deepseek_dsml_with_multiple_typed_calls() -> None:
    raw = """I'll inspect the relevant files first.
<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="list_files">
<｜｜DSML｜｜parameter name="path" string="true">.</｜｜DSML｜｜parameter>
<｜｜DSML｜｜parameter name="recursive" string="false">true</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
<｜｜DSML｜｜invoke name="search_code">
<｜｜DSML｜｜parameter name="query" string="true">refresh token</｜｜DSML｜｜parameter>
<｜｜DSML｜｜parameter name="max_results" string="false">25</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
</｜｜DSML｜｜tool_calls>"""

    result = normalize_model_output(raw)

    assert result.dialect is ModelOutputDialect.DEEPSEEK_DSML
    assert result.payload == {
        "tool_calls": [
            {
                "name": "list_files",
                "arguments": {"path": ".", "recursive": True},
            },
            {
                "name": "search_code",
                "arguments": {"query": "refresh token", "max_results": 25},
            },
        ]
    }


def test_dsml_keeps_source_code_with_xml_characters_opaque() -> None:
    raw = """<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="apply_patch">
<｜｜DSML｜｜parameter name="edits" string="false">[{"path":"app.py","content":"if value < 3 and name == \\"a&b\\":\\n    pass\\n"}]</｜｜DSML｜｜parameter>
</｜｜DSML｜｜invoke>
</｜｜DSML｜｜tool_calls>"""

    result = normalize_model_output(raw)

    content = result.payload["tool_calls"][0]["arguments"]["edits"][0]["content"]
    assert content == 'if value < 3 and name == "a&b":\n    pass\n'


@pytest.mark.parametrize(
    "raw",
    [
        "prose\n```json\n{\"tool_calls\": []}\n```",
        "```json\n{\"tool_calls\": []}\n```\ntrailing instruction",
        (
            "<｜｜DSML｜｜tool_calls></｜｜DSML｜｜tool_calls>"
            '{"tool_calls":[{"name":"git_status","arguments":{}}]}'
        ),
        (
            "<｜｜DSML｜｜tool_calls>"
            "<｜｜DSML｜｜invoke name=\"read_file\">"
            "<｜｜DSML｜｜parameter name=\"path\" string=\"maybe\">x.py"
            "</｜｜DSML｜｜parameter></｜｜DSML｜｜invoke>"
            "</｜｜DSML｜｜tool_calls>"
        ),
        (
            "<｜｜DSML｜｜tool_calls>ignore this text"
            "<｜｜DSML｜｜invoke name=\"git_status\">"
            "</｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>"
        ),
        (
            "<｜｜DSML｜｜tool_calls>"
            "<｜｜DSML｜｜invoke name=\"read_file\">"
            "<｜｜DSML｜｜parameter name=\"path\" string=\"true\">x.py"
            "</｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>"
        ),
    ],
)
def test_rejects_ambiguous_or_malformed_provider_output(raw: str) -> None:
    with pytest.raises(ModelOutputNormalizationError):
        normalize_model_output(raw)
