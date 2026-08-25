"""Normalize provider response dialects into CodeTeam's action protocol."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import Enum
from html import escape
from typing import Any


class ModelOutputDialect(str, Enum):
    JSON = "json"
    MARKDOWN_JSON = "markdown_json"
    DEEPSEEK_DSML = "deepseek_dsml"


class ModelOutputNormalizationError(ValueError):
    """Raised when a provider response has no single unambiguous action."""


@dataclass(frozen=True)
class NormalizedModelOutput:
    payload: dict[str, Any]
    dialect: ModelOutputDialect


_DSML_PREFIX = "｜｜DSML｜｜"
_DSML_OPEN = f"<{_DSML_PREFIX}tool_calls>"
_DSML_CLOSE = f"</{_DSML_PREFIX}tool_calls>"


def normalize_model_output(raw_output: str) -> NormalizedModelOutput:
    """Decode one raw provider response without changing the retained raw text."""
    stripped = raw_output.strip()
    if not stripped:
        raise ModelOutputNormalizationError("Model output was empty.")

    if stripped.startswith("```"):
        payload = _decode_markdown_json(stripped)
        return NormalizedModelOutput(payload, ModelOutputDialect.MARKDOWN_JSON)

    if _DSML_OPEN in stripped or _DSML_CLOSE in stripped:
        payload = _decode_dsml(stripped)
        return NormalizedModelOutput(payload, ModelOutputDialect.DEEPSEEK_DSML)

    return NormalizedModelOutput(
        _decode_json_object(stripped),
        ModelOutputDialect.JSON,
    )


def _decode_json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ModelOutputNormalizationError(
            f"Model output was not valid JSON: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise ModelOutputNormalizationError("Model output must be a JSON object.")
    return payload


def _decode_markdown_json(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip().lower() not in {"```", "```json"}:
        raise ModelOutputNormalizationError(
            "Markdown output must be exactly one JSON code fence."
        )
    if lines[-1].strip() != "```" or any(
        line.strip().startswith("```") for line in lines[1:-1]
    ):
        raise ModelOutputNormalizationError(
            "Markdown output must contain one unambiguous JSON code fence."
        )
    return _decode_json_object("\n".join(lines[1:-1]).strip())


def _decode_dsml(text: str) -> dict[str, Any]:
    if text.count(_DSML_OPEN) != 1 or text.count(_DSML_CLOSE) != 1:
        raise ModelOutputNormalizationError(
            "DSML output must contain exactly one tool_calls envelope."
        )
    start = text.index(_DSML_OPEN)
    end = text.index(_DSML_CLOSE, start) + len(_DSML_CLOSE)
    preamble = text[:start].strip()
    trailing = text[end:].strip()
    if (
        trailing
        or len(preamble) > 512
        or any(character in preamble for character in "{}[]<>")
    ):
        raise ModelOutputNormalizationError(
            "DSML output contained ambiguous text outside its action envelope."
        )

    xml_text = text[start:end].replace(
        f"<{_DSML_PREFIX}",
        "<dsml_",
    ).replace(
        f"</{_DSML_PREFIX}",
        "</dsml_",
    )
    xml_text = _escape_dsml_parameter_text(xml_text)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise ModelOutputNormalizationError(f"Malformed DSML output: {error}") from error
    if root.tag != "dsml_tool_calls" or root.attrib or (root.text or "").strip():
        raise ModelOutputNormalizationError("Invalid DSML tool_calls envelope.")

    tool_calls: list[dict[str, Any]] = []
    for invoke in root:
        if invoke.tag != "dsml_invoke" or set(invoke.attrib) != {"name"}:
            raise ModelOutputNormalizationError("Invalid DSML invoke element.")
        if (invoke.tail or "").strip():
            raise ModelOutputNormalizationError("Unexpected text between DSML calls.")
        name = invoke.attrib["name"].strip()
        if not name:
            raise ModelOutputNormalizationError("DSML tool name cannot be empty.")
        arguments: dict[str, Any] = {}
        for parameter in invoke:
            if parameter.tag != "dsml_parameter":
                raise ModelOutputNormalizationError("Invalid DSML parameter element.")
            if set(parameter.attrib) - {"name", "string"} or "name" not in parameter.attrib:
                raise ModelOutputNormalizationError("Invalid DSML parameter attributes.")
            if list(parameter):
                raise ModelOutputNormalizationError("Nested DSML parameters are not allowed.")
            if (parameter.tail or "").strip():
                raise ModelOutputNormalizationError(
                    "Unexpected text between DSML parameters."
                )
            parameter_name = parameter.attrib["name"].strip()
            if not parameter_name or parameter_name in arguments:
                raise ModelOutputNormalizationError(
                    "DSML parameter names must be non-empty and unique."
                )
            arguments[parameter_name] = _decode_dsml_parameter(
                parameter.text or "",
                parameter.attrib.get("string"),
            )
        tool_calls.append({"name": name, "arguments": arguments})

    if not tool_calls:
        raise ModelOutputNormalizationError("DSML tool_calls cannot be empty.")
    return {"tool_calls": tool_calls}


def _decode_dsml_parameter(text: str, string_marker: str | None) -> Any:
    value = text.strip()
    if string_marker == "true":
        return value
    if string_marker not in {None, "false"}:
        raise ModelOutputNormalizationError(
            "DSML parameter string marker must be true or false."
        )
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise ModelOutputNormalizationError(
            "Non-string DSML parameter must contain a JSON scalar or value."
        ) from error


def _escape_dsml_parameter_text(xml_text: str) -> str:
    """Keep arbitrary source text opaque while ElementTree validates structure."""
    opening = "<dsml_parameter"
    closing = "</dsml_parameter>"
    pieces: list[str] = []
    cursor = 0
    while True:
        parameter_start = xml_text.find(opening, cursor)
        if parameter_start < 0:
            pieces.append(xml_text[cursor:])
            return "".join(pieces)
        opening_end = xml_text.find(">", parameter_start)
        parameter_end = xml_text.find(closing, opening_end + 1)
        if opening_end < 0 or parameter_end < 0:
            raise ModelOutputNormalizationError("Malformed DSML parameter boundary.")
        pieces.extend(
            (
                xml_text[cursor : opening_end + 1],
                escape(xml_text[opening_end + 1 : parameter_end], quote=False),
                closing,
            )
        )
        cursor = parameter_end + len(closing)
