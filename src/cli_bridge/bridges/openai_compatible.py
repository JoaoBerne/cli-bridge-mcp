"""OpenAI-compatible HTTP bridge — stdlib `urllib` only, no new dependency.

A tiny standalone CLI the council spawns like any other lane (so the exact same ban-safe spawn
model applies). It:
  • reads the API key from an ENV VAR whose NAME is given on the command line (`--key-env`) — the
    key VALUE never appears in argv, so it can't leak via `ps`. Omit `--key-env` entirely for a
    keyless local server (`fm serve`, llama.cpp, vLLM, LM Studio) and no auth header is sent;
  • POSTs a single user prompt to an OpenAI-compatible `/chat/completions` endpoint and prints the
    assistant message to stdout;
  • `--list-models` instead GETs `/models` and prints one model id per line.

Base URL is a flag, so the same bridge serves OpenRouter, xAI, Together, Groq, a local vLLM, etc.
Failures are classified to stderr (`missing-auth` / `http <code>` / `timeout` / `network`) with a
non-zero exit so the runner records a clean error kind."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _request(url: str, headers: dict, timeout: float, payload: dict | None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    method = "POST" if payload is not None else "GET"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:           # noqa: S310 (https only)
        return json.loads(resp.read().decode("utf-8", "replace"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cli-bridge-openai", add_help=True,
                                 description="OpenAI-compatible API bridge (stdlib).")
    ap.add_argument("--base-url", required=True, help="e.g. https://openrouter.ai/api/v1")
    ap.add_argument("--key-env", default="", help="NAME of the env var holding the API key; omit "
                                                  "for a keyless local server (no auth header)")
    ap.add_argument("--model", default="", help="model id (omit to use the endpoint default)")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--list-models", action="store_true", help="GET /models and print ids")
    ap.add_argument("prompt", nargs="?", default="")
    a = ap.parse_args(argv)

    # No --key-env at all = a deliberately keyless endpoint (a local `fm serve`, llama.cpp, vLLM,
    # LM Studio…): send no Authorization header. Naming a var that is EMPTY stays an auth error —
    # that's a misconfigured cloud lane, not an intentionally open server.
    headers = {"Content-Type": "application/json"}
    if a.key_env:
        key = os.environ.get(a.key_env, "").strip()
        if not key:
            print(f"[bridge] missing-auth: env var {a.key_env} is empty or unset", file=sys.stderr)
            return 2
        headers["Authorization"] = f"Bearer {key}"
    base = a.base_url.rstrip("/")
    try:
        if a.list_models:
            body = _request(f"{base}/models", headers, a.timeout, None)
            ids = [m.get("id", "") for m in (body.get("data") or []) if isinstance(m, dict)]
            print("\n".join(i for i in ids if i))
            return 0
        if not a.prompt.strip():
            print("[bridge] no prompt given", file=sys.stderr)
            return 2
        # `stream` is explicit, never left to the endpoint's default: the OpenAI spec says absent
        # means false, but Apple's `fm serve` streams SSE unless told otherwise (verified live) —
        # and this bridge parses one JSON object, so an unexpected `data: {...}` stream is a crash.
        payload: dict = {"stream": False, "messages": [{"role": "user", "content": a.prompt}]}
        if a.model:
            payload["model"] = a.model
        body = _request(f"{base}/chat/completions", headers, a.timeout, payload)
        choices = body.get("choices") or []
        content = ""
        if choices and isinstance(choices[0], dict):
            content = (choices[0].get("message") or {}).get("content") or ""
        if not content:
            print("[bridge] empty completion from endpoint", file=sys.stderr)
            return 1
        print(content)
        return 0
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        print(f"[bridge] http {e.code}: {detail}".rstrip(), file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, TimeoutError):
            print("[bridge] timeout", file=sys.stderr)
        else:
            print(f"[bridge] network error: {reason}", file=sys.stderr)
        return 1
    except TimeoutError:
        print("[bridge] timeout", file=sys.stderr)
        return 1


if __name__ == "__main__":          # pragma: no cover
    raise SystemExit(main())
