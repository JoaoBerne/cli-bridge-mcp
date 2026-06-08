"""The shipped local-model lane recipes (examples/*.lane.json) must parse and build the right
argv. These are zero-code custom lanes loaded via CLI_BRIDGE_LANES_FILE — ban-safe (cli-bridge
just spawns the local CLI), local open weights, $0/offline. Loading the REAL files also catches a
JSON typo in a shipped recipe."""
import os

from cli_bridge import lanes

EX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")


def _one(filename):
    loaded = lanes.load_custom_lanes(os.path.join(EX, filename))
    assert len(loaded) == 1, f"{filename} should define exactly one lane"
    return loaded[0]


def test_lmstudio_recipe_argv():
    lane = _one("lmstudio.lane.json")
    assert lane.key == "lmstudio" and lane.cost_label == "free"
    # model is POSITIONAL for `lms chat <model> -p <task> -y` → inline {model}, no model_flag.
    argv = lane.build_ask("Reply OK", "qwen2.5-7b-instruct", "", "")
    assert argv == ["chat", "qwen2.5-7b-instruct", "-p", "Reply OK", "-y"]


def test_mlx_recipe_argv():
    lane = _one("mlx.lane.json")
    assert lane.key == "mlx" and lane.cost_label == "free"
    assert "model" in lane.caps                                   # --model is a real flag
    argv = lane.build_ask("Reply OK", "mlx-community/Foo-4bit", "", "")
    assert argv == ["--model", "mlx-community/Foo-4bit", "--prompt", "Reply OK"]


def test_llamacpp_recipe_argv():
    lane = _one("llamacpp.lane.json")
    assert lane.key == "llamacpp" and lane.cost_label == "free"
    assert "model" in lane.caps                                   # -m is a real flag (a .gguf path)
    argv = lane.build_ask("Reply OK", "/models/q.gguf", "", "")
    assert argv == ["-m", "/models/q.gguf", "-p", "Reply OK", "-no-cnv", "-n", "512"]
    # with no model the -m flag is omitted (builder skips an empty model) rather than passing -m ""
    assert lane.build_ask("hi", "", "", "") == ["-p", "hi", "-no-cnv", "-n", "512"]


def test_recipes_carry_no_secret_risk():
    # Local lanes never expand a ${SECRET} into argv — sanity-check the loader flagged none.
    for f in ("lmstudio.lane.json", "mlx.lane.json", "llamacpp.lane.json"):
        lanes.load_custom_lanes(os.path.join(EX, f))
        assert lanes.LANES_LOAD_STATUS["argv_secret_risk"] == []
