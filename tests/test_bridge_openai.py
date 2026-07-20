"""Bundled OpenAI-compatible bridge — unit-tested against a FAKED urllib (no network). Asserts the
key is read from env (never argv), the request shape, and failure classification."""
import io
import json
import urllib.error

from cli_bridge.bridges import openai_compatible as br


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_bridge_success_reads_key_from_env_not_argv(monkeypatch, capsys):
    monkeypatch.setenv("MY_KEY", "sk-secret")
    cap = {}

    def fake_urlopen(req, timeout=0):
        cap["url"] = req.full_url
        cap["auth"] = req.headers.get("Authorization")
        cap["body"] = json.loads(req.data)
        return _FakeResp({"choices": [{"message": {"content": "hello world"}}]})

    monkeypatch.setattr(br.urllib.request, "urlopen", fake_urlopen)
    rc = br.main(["--base-url", "https://x/v1", "--key-env", "MY_KEY", "--model", "m", "hi there"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "hello world"
    assert cap["auth"] == "Bearer sk-secret"                         # key read from env, sent in header
    assert cap["url"] == "https://x/v1/chat/completions"
    assert cap["body"]["model"] == "m"
    assert cap["body"]["messages"][0]["content"] == "hi there"
    # Explicit, not left to the endpoint's default: Apple's `fm serve` streams SSE unless told
    # otherwise, and this bridge parses a single JSON object.
    assert cap["body"]["stream"] is False


def test_bridge_without_key_env_sends_no_auth_header(monkeypatch, capsys):
    # A keyless LOCAL server (`fm serve`, llama.cpp, vLLM, LM Studio) has nothing to authenticate
    # against: omitting --key-env must succeed and send no Authorization header at all.
    cap = {}

    def fake_urlopen(req, timeout=0):
        cap["auth"] = req.headers.get("Authorization")
        return _FakeResp({"choices": [{"message": {"content": "local answer"}}]})

    monkeypatch.setattr(br.urllib.request, "urlopen", fake_urlopen)
    rc = br.main(["--base-url", "http://127.0.0.1:1976/v1", "--model", "pcc", "hi"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "local answer"
    assert cap["auth"] is None


def test_bridge_missing_key_returns_missing_auth(monkeypatch, capsys):
    monkeypatch.delenv("MY_KEY", raising=False)
    rc = br.main(["--base-url", "https://x/v1", "--key-env", "MY_KEY", "hi"])
    assert rc == 2
    assert "missing-auth" in capsys.readouterr().err


def test_bridge_http_error_is_classified(monkeypatch, capsys):
    monkeypatch.setenv("MY_KEY", "k")

    def boom(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, io.BytesIO(b"slow down"))

    monkeypatch.setattr(br.urllib.request, "urlopen", boom)
    rc = br.main(["--base-url", "https://x/v1", "--key-env", "MY_KEY", "hi"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "http 429" in err and "slow down" in err


def test_bridge_timeout_is_classified(monkeypatch, capsys):
    monkeypatch.setenv("MY_KEY", "k")

    def boom(req, timeout=0):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(br.urllib.request, "urlopen", boom)
    rc = br.main(["--base-url", "https://x/v1", "--key-env", "MY_KEY", "hi"])
    assert rc == 1
    assert "timeout" in capsys.readouterr().err


def test_bridge_empty_completion_is_error(monkeypatch, capsys):
    monkeypatch.setenv("MY_KEY", "k")
    monkeypatch.setattr(br.urllib.request, "urlopen",
                        lambda req, timeout=0: _FakeResp({"choices": [{"message": {"content": ""}}]}))
    rc = br.main(["--base-url", "https://x/v1", "--key-env", "MY_KEY", "hi"])
    assert rc == 1
    assert "empty completion" in capsys.readouterr().err


def test_bridge_list_models(monkeypatch, capsys):
    monkeypatch.setenv("MY_KEY", "k")
    cap = {}

    def fake_urlopen(req, timeout=0):
        cap["method"] = req.get_method()
        cap["url"] = req.full_url
        return _FakeResp({"data": [{"id": "vendor/a"}, {"id": "vendor/b"}, {"nope": 1}]})

    monkeypatch.setattr(br.urllib.request, "urlopen", fake_urlopen)
    rc = br.main(["--list-models", "--base-url", "https://x/v1", "--key-env", "MY_KEY"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "vendor/a" in out and "vendor/b" in out
    assert cap["method"] == "GET" and cap["url"] == "https://x/v1/models"


def test_bridge_no_model_omits_model_field(monkeypatch, capsys):
    monkeypatch.setenv("MY_KEY", "k")
    cap = {}

    def fake_urlopen(req, timeout=0):
        cap["body"] = json.loads(req.data)
        return _FakeResp({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(br.urllib.request, "urlopen", fake_urlopen)
    rc = br.main(["--base-url", "https://x/v1", "--key-env", "MY_KEY", "hi"])
    assert rc == 0 and "model" not in cap["body"]                    # endpoint default used
