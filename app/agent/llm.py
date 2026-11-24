"""LiteLLM wrapper for Apex Margin Advisor.

Supports local Ollama (`ollama/qwen2.5-coder:14b`, `ollama/gpt-oss:20b`), Gemini (`gemini/gemini-2.5-flash`),
OpenAI (`openai/gpt-4o-mini`), and Vertex AI (`vertex_ai/...`) through LiteLLM, plus native/JSON tool call recovery.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

import litellm

from app.config import env
from mcp_server.server import ALLOWED_TOOLS

litellm.drop_params = True
litellm.suppress_debug_info = True
litellm.telemetry = False

TOOL_NAMES = tuple(sorted(ALLOWED_TOOLS))

SESSION_USAGE = {
    "requests": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
}


@dataclass
class LLMResult:
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    latency: float = 0.0
    model: str = ""
    usage: dict = field(default_factory=dict)
    native_tool_call: bool = False


def resolve_model(model: str | None = None) -> str:
    m = (model or env("LLM_MODEL", "rules") or "rules").strip()
    if m.startswith("ollama/"):
        m = "ollama_chat/" + m.split("/", 1)[1]
    return m


def _kwargs(model: str) -> dict:
    kw: dict = {
        "temperature": float(env("LLM_TEMPERATURE", "0") or 0),
        "timeout": float(env("LLM_TIMEOUT_SECONDS", "180") or 180),
    }
    if model.startswith("ollama"):
        kw["api_base"] = env("OLLAMA_API_BASE", "http://localhost:11434")
        kw["num_ctx"] = int(env("OLLAMA_NUM_CTX", "8192") or 8192)
        if "gpt-oss" in model:
            kw["reasoning_effort"] = env("GPT_OSS_REASONING_EFFORT", "low")
    elif model.startswith("openai/"):
        api_key = env("OPENAI_API_KEY")
        if not api_key:
            raise PermissionError("Missing OPENAI_API_KEY for OpenAI model mode.")
        kw["api_key"] = api_key
    elif model.startswith("gemini/"):
        api_key = env("GEMINI_API_KEY")
        if not api_key:
            raise PermissionError("Missing GEMINI_API_KEY for Gemini model mode.")
        kw["api_key"] = api_key
    elif model.startswith("vertex_ai/"):
        if env("VERTEXAI_PROJECT"):
            kw["vertex_project"] = env("VERTEXAI_PROJECT")
        kw["vertex_location"] = env("VERTEXAI_LOCATION", "us-central1")
    return kw


def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
    tool_choice: str | None = None,
    max_tokens: int | None = 800,
) -> LLMResult:
    m = resolve_model(model)
    kw = _kwargs(m)
    if tools:
        kw["tools"] = tools
        if tool_choice:
            kw["tool_choice"] = tool_choice
    if max_tokens:
        if "gpt-oss" in m:
            max_tokens = max(max_tokens, 1800)
        kw["max_tokens"] = max_tokens

    t0 = time.time()
    resp = litellm.completion(model=m, messages=messages, **kw)
    msg = resp.choices[0].message
    calls, native = parse_tool_calls(msg)
    usage = {}
    if getattr(resp, "usage", None):
        try:
            pt = int(resp.usage.prompt_tokens or 0)
            ct = int(resp.usage.completion_tokens or 0)
            usage = {"prompt_tokens": pt, "completion_tokens": ct}
            SESSION_USAGE["requests"] += 1
            SESSION_USAGE["prompt_tokens"] += pt
            SESSION_USAGE["completion_tokens"] += ct
        except Exception:  # noqa: BLE001
            usage = {}
    return LLMResult(
        content=(msg.content or "").strip(),
        tool_calls=calls,
        latency=time.time() - t0,
        model=m,
        usage=usage,
        native_tool_call=native,
    )


def _loads(s) -> dict:
    if isinstance(s, dict):
        return s
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}


def parse_tool_calls(msg) -> tuple[list[dict], bool]:
    calls = []
    for tc in (getattr(msg, "tool_calls", None) or []):
        fn = getattr(tc, "function", None)
        if fn is None or not getattr(fn, "name", None):
            continue
        if fn.name in ALLOWED_TOOLS:
            calls.append({"name": fn.name, "arguments": _loads(fn.arguments)})
    if calls:
        return calls, True
    return calls_from_text(getattr(msg, "content", "") or ""), False


def _balanced_objects(text: str) -> list[str]:
    out, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                out.append(text[start : i + 1])
    return out


def calls_from_text(text: str) -> list[dict]:
    if not text:
        return []
    calls = []
    for obj in _balanced_objects(text):
        d = _loads(obj)
        name = d.get("name") or d.get("tool") or d.get("function") or d.get("tool_name")
        if isinstance(name, dict):
            name = name.get("name")
        args = d.get("arguments") or d.get("args") or d.get("parameters") or d.get("input")
        if name in ALLOWED_TOOLS:
            calls.append({"name": name, "arguments": _loads(args) if args is not None else {}})
    if calls:
        return calls
    for m in re.finditer(r"\b(" + "|".join(TOOL_NAMES) + r")\b\s*\(?\s*(\{)", text):
        objs = _balanced_objects(text[m.start(2) :])
        if objs:
            calls.append({"name": m.group(1), "arguments": _loads(objs[0])})
    return calls
