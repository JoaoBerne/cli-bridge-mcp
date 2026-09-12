"""The shipped local-model lane recipe (examples/local-runtime.lane.json) must parse and build the
right argv. These are zero-code custom lanes loaded via CLI_BRIDGE_LANES_FILE — ban-safe (cli-bridge
just spawns the local CLI), local open weights, $0/offline. Loading the REAL file also catches a
JSON typo in a shipped recipe."""
import os

from cli_bridge import lanes

RECIPE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "examples", "local-runtime.lane.json")


def _lane(key):
    loaded = {ln.key: ln for ln in lanes.load_custom_lanes(RECIPE)}
    assert set(loaded) == {"lmstudio", "mlx", "llamacpp"}
    assert lanes.LANES_LOAD_STATUS["argv_secret_risk"] == []       # no ${SECRET} expands into argv
    lane = loaded[key]
    assert lane.cost_label == "free"
    return lane


def test_lmstudio_recipe_argv():
    lane = _lane("lmstudio")
    # model is POSITIONAL for `lms chat <model> -p <task> -y` → inline {model}, no model_flag.
    argv = lane.build_ask("Reply OK", "qwen2.5-7b-instruct", "", "")
    assert argv == ["chat", "qwen2.5-7b-instruct", "-p", "Reply OK", "-y"]


def test_mlx_recipe_argv():
    lane = _lane("mlx")
    assert "model" in lane.caps                                   # --model is a real flag
    argv = lane.build_ask("Reply OK", "mlx-community/Foo-4bit", "", "")
    assert argv == ["--model", "mlx-community/Foo-4bit", "--prompt", "Reply OK"]


def test_llamacpp_recipe_argv():
    lane = _lane("llamacpp")
    assert "model" in lane.caps                                   # -m is a real flag (a .gguf path)
    argv = lane.build_ask("Reply OK", "/models/q.gguf", "", "")
    assert argv == ["-m", "/models/q.gguf", "-p", "Reply OK", "-no-cnv", "-n", "512"]
    # with no model the -m flag is omitted (builder skips an empty model) rather than passing -m ""
    assert lane.build_ask("hi", "", "", "") == ["-p", "hi", "-no-cnv", "-n", "512"]
