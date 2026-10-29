"""Claude API (Messages) with images, returning parsed JSON. Needs ANTHROPIC_API_KEY."""
import json
import os
import re

from .common import ReelFlowError, b64, http_json

API = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("REELFLOW_MODEL", "claude-sonnet-4-5")


def ask_json(system, parts, max_tokens=4000):
    """parts: list of str (text) or ("image", path, label). Returns the JSON object Claude puts in <json></json>."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ReelFlowError("ANTHROPIC_API_KEY is not set (needed for automatic scripts and trend picks)")
    content = []
    for p in parts:
        if isinstance(p, str):
            content.append({"type": "text", "text": p})
        else:
            _, path, label = p
            content.append({"type": "text", "text": label})
            mt = "image/png" if path.lower().endswith(".png") else "image/jpeg"
            content.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64(path)}})
    content.append({"type": "text", "text": "Answer with one JSON object inside <json></json> tags and nothing else."})
    r = http_json(API, {"model": MODEL, "max_tokens": max_tokens, "system": system,
                        "messages": [{"role": "user", "content": content}]},
                  headers={"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=300)
    text = "".join(b.get("text", "") for b in r.get("content", []))
    m = re.search(r"<json>(.*?)</json>", text, re.S) or re.search(r"(\{.*\})", text, re.S)
    if not m:
        raise ReelFlowError(f"Claude returned no JSON: {text[:400]}")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise ReelFlowError(f"Claude returned bad JSON ({e}): {m.group(1)[:400]}")
