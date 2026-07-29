"""cli-bridge — let your AI assistant consult a council of other AI CLIs.

Low-level MCP server so we can filter tools per client at list time:
- only lanes whose CLI is installed are exposed,
- the *calling* client's own lane is shown as a normal tool but kept out of fan-out
  (CLI_BRIDGE_HIDE_HOST=1 hides it entirely, sibling-model-consult only),
detected from the MCP `clientInfo.name` (with a CLI_BRIDGE_HOST env override).

Every lane spawns the official CLI as a subprocess — no token extraction, no API keys,
so accounts can't get flagged for ToS-breaking token reuse. Read-only by default.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
import warnings

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    GetPromptResult,
    Prompt,
    PromptMessage,
    Resource,
    TextContent,
    Tool,
)

from . import (
    budget,
    buildloop,
    config,
    conversations,
    council,
    guards,
    jobs,
    mcp_compat,
    orchestrate,
    preamble,
    prompts,
    reports,
    resources,
    router,
    runner,
    schemas,
    telemetry,
    workflows,
    worktrees,
)
from . import (
    lanes as lanes_mod,
)
from .config import (
    ASK_ALL_DEFAULT_TIMEOUT_S,
    ASK_ALL_MAX_TIMEOUT_S,
    DEFAULT_TIMEOUT_S,
    INLINE_MAX_CHARS,
    INSTRUCTIONS,
    MAX_TIMEOUT_S,
    OVERFLOW_DIR,
    SETUP_TEXT,
)
from .detect import installed_lanes
from .lanes import LaneSpec, all_lanes, models_from_file

# config.py is the single source of truth for env/timeouts/profile/onboarding. These thin
# aliases keep the historical server.* call sites (and tests) working after the extraction.
_int_env = config.int_env
_profile = config.profile
_profile_is_set = config.profile_is_set
_cost_config_is_set = config.cost_config_is_set
# How long a spilled overflow file is kept before best-effort pruning (P0-4).
OVERFLOW_TTL_H = config.int_env("CLI_BRIDGE_OVERFLOW_TTL_H", 24, 0, 24 * 365)

# server.py was split for size; the tool-schema, report, prompt and resource bodies now live in
# dedicated modules. Re-export the moved symbols so the historical server.* surface — pinned by
# the test suite and used by the @decorators / dispatch below — stays byte-identical. (doctor /
# doctor_deep keep a thin wrapper further down: they need the host-detection + lane-runner
# couplings that stay in server.py, injected the same way council.py takes run_lane.)
_tools_for = schemas._tools_for
_self_ask_tool = schemas._self_ask_tool
_host_ask_tool = schemas._host_ask_tool
_filter_tools = schemas._filter_tools
_ann = schemas._ann
_PROMPTS = prompts._PROMPTS
_REVIEW_DIFF_SCHEMA = resources._REVIEW_DIFF_SCHEMA
_RESOURCES = resources._RESOURCES
_config_snapshot = resources._config_snapshot
_render_usage = reports._render_usage
_render_budget = reports._render_budget
_render_job_status = reports._render_job_status
_render_jobs_list = reports._render_jobs_list
_render_lane_stats = reports._render_lane_stats
_echo_header = reports._echo_header
_setup_recommendation = reports._setup_recommendation
_rel_time = reports._rel_time
_parse_since = reports._parse_since
_lane_version = reports._lane_version
_flag_drift_section = reports._flag_drift_section


server: Server = Server("cli-bridge", instructions=INSTRUCTIONS)


_OVERFLOW_MAX_FILES = config.int_env("CLI_BRIDGE_OVERFLOW_MAX_FILES", 200, 0, 100_000)


def _prune_overflow() -> None:
    """Best-effort: drop overflow files older than OVERFLOW_TTL_H, and cap the file COUNT (keep
    the newest CLI_BRIDGE_OVERFLOW_MAX_FILES, delete the oldest beyond) so the temp dir can't
    grow without bound even within the TTL window. Never raises — overflow is a convenience."""
    try:
        entries = []
        cutoff = time.time() - OVERFLOW_TTL_H * 3600 if OVERFLOW_TTL_H > 0 else None
        for name in os.listdir(OVERFLOW_DIR):
            p = os.path.join(OVERFLOW_DIR, name)
            try:
                if not os.path.isfile(p):
                    continue
                mtime = os.path.getmtime(p)
            except OSError:
                continue
            if cutoff is not None and mtime < cutoff:
                try:
                    os.remove(p)
                except OSError:
                    pass
            else:
                entries.append((mtime, p))
        # count cap: delete oldest beyond the limit
        if _OVERFLOW_MAX_FILES and len(entries) > _OVERFLOW_MAX_FILES:
            entries.sort()                       # oldest first
            for _mtime, p in entries[:len(entries) - _OVERFLOW_MAX_FILES]:
                try:
                    os.remove(p)
                except OSError:
                    pass
    except OSError:
        pass


def _emit(text: str, label: str = "answer", guard: bool = True) -> TextContent:
    """Return small answers inline; spill big ones to a file and return a preview + path.
    This is what makes a delegate behave like a subagent: the host gets a compact digest,
    and the full output stays out of its context until it deliberately reads the file.

    guard=True (the default) runs the injection/tool-poisoning guard over UNTRUSTED delegate
    output first; internal reports (doctor/usage/lane_stats) pass guard=False — they're ours."""
    if guard:
        text = guards.apply(text)
    if len(text) <= INLINE_MAX_CHARS:
        return TextContent(type="text", text=text)
    try:
        os.makedirs(OVERFLOW_DIR, exist_ok=True)
        _prune_overflow()
        digest = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:10]
        path = os.path.join(OVERFLOW_DIR, f"{label}-{digest}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        head = text[:INLINE_MAX_CHARS]
        return TextContent(type="text", text=(
            f"{head}\n\n[... {len(text)} chars total — truncated. Full output saved to:\n{path}\n"
            f"Read it selectively (grep / a subagent), not all at once, to keep context lean.]"))
    except OSError:
        # If we can't write the file, fall back to a hard clip rather than flooding context.
        return TextContent(type="text", text=text[:INLINE_MAX_CHARS] + "\n\n[... clipped]")


async def _emit_progress(done: int, total: int, msg: str = "") -> None:
    """Stream an MCP progress notification during a slow fan-out — so the host shows live "3/5
    lanes done" instead of a frozen spinner. No-op when the host sent no progress token, or
    outside a request context (async jobs / human CLI / tests). NEVER raises into a delegation."""
    try:
        ctx = mcp_compat.request_ctx(server)
        token = mcp_compat.progress_token(ctx.meta) if ctx else None
        if token is None:
            return
        await ctx.session.send_progress_notification(
            progress_token=token, progress=done, total=total,
            message=(f"{msg} ({done}/{total})" if msg else f"{done}/{total}"))
    except Exception:
        return


async def _host_sample(prompt: str, max_tokens: int = 1024) -> str | None:
    """Ask the HOST's own model to complete a prompt via MCP 'sampling' — a FREE judge /
    synthesizer: no lane spawned, no API key, no quota burned. Returns the text, or None if the
    host doesn't support sampling or anything goes wrong (the caller then falls back to a lane).
    Never raises. This is cli-bridge's zero-cost edge: reuse the model you're already running."""
    try:
        from mcp.types import SamplingMessage
        from mcp.types import TextContent as _TC
        ctx = mcp_compat.request_ctx(server)
        result = await ctx.session.create_message(
            messages=[SamplingMessage(role="user", content=_TC(type="text", text=prompt))],
            max_tokens=max_tokens,
        )
        text = getattr(getattr(result, "content", None), "text", None)
        return text.strip() if isinstance(text, str) and text.strip() else None
    except Exception:
        return None


# ─────────────────────────────── host detection (self-hide) ───────────────────────────────

def _slug(name: str) -> str:
    """Normalize a client name so 'Claude Code', 'claude-code', 'claude_code' all match."""
    return "".join(c if c.isalnum() else "-" for c in (name or "").lower()).strip("-")


def _host_name() -> str:
    """Who is calling us? Env override wins; else the MCP client's declared name (slugged)."""
    forced = os.environ.get("CLI_BRIDGE_HOST", "").strip()
    if forced:
        return _slug(forced)
    try:
        params = mcp_compat.request_ctx(server).session.client_params
        return _slug(mcp_compat.attr(params, "clientInfo").name)
    except Exception:
        return ""


def _is_host(lane: LaneSpec, host: str) -> bool:
    return bool(host) and host in {_slug(c) for c in lane.client_ids}


def _active_lanes() -> tuple[list[LaneSpec], str]:
    """Installed lanes minus the caller's own lane — the delegates used for fan-out/cascade.
    (Asking your OWN model the same question wastes a call, so the host lane is excluded here.)"""
    host = _host_name()
    lanes = [ln for ln in installed_lanes(all_lanes()) if not _is_host(ln, host)]
    allow = config.allowed_lanes()                 # optional team/locked-down allowlist
    if allow:
        lanes = [ln for ln in lanes if ln.key in allow]
    return lanes, host


def _host_lane(host: str) -> LaneSpec | None:
    """The caller's OWN installed lane. Visible as a normal ask_<host> tool by default; with
    CLI_BRIDGE_HIDE_HOST=1 it is hidden and only reachable as an explicit-model SIBLING consult.
    Returned separately from the delegates either way, so it never joins a fan-out."""
    if not host:
        return None
    return next((ln for ln in installed_lanes(all_lanes()) if _is_host(ln, host)), None)


# ─────────────────────────────── tool list (schemas built in schemas.py) ───────────────────────────────

async def list_tools() -> list[Tool]:
    lanes, host = _active_lanes()
    tools = _tools_for(lanes)
    own = _host_lane(host)
    if own:
        if config.hide_host():
            if "model" in own.caps:                # legacy: reach a sibling model of your own family
                tools.insert(0, _self_ask_tool(own))
        else:
            tools.insert(0, _host_ask_tool(own))   # visible by default: a normal direct ask_<host>
    return _filter_tools(tools)


# ─────────────────────────────── MCP prompts (builders + registry in prompts.py) ───────────────────────────

async def list_prompts() -> list[Prompt]:
    return [Prompt(name=name, description=spec["description"], arguments=spec["arguments"])
            for name, spec in _PROMPTS.items()]


async def get_prompt(name: str, arguments: dict | None) -> GetPromptResult:
    spec = _PROMPTS.get(name)
    if spec is None:
        raise ValueError(f"unknown prompt: {name}")
    text = spec["build"](arguments or {})
    return GetPromptResult(
        description=spec["description"],
        messages=[PromptMessage(role="user", content=TextContent(type="text", text=text))])


# ─────────────────────────────── MCP resources (payloads in resources.py) ───────────────────────────────

async def list_resources() -> list[Resource]:
    # uri is our own constant str (the SDK types it AnyUrl; pydantic coerces at runtime), and
    # mimeType is the wire name — from_wire covers both, see mcp_compat.
    return [mcp_compat.from_wire(Resource, uri=uri, name=name, description=desc,
                                 mimeType="application/json")
            for uri, (name, desc) in _RESOURCES.items()]


async def read_resource(uri) -> str:
    key = str(uri)
    if key == "cli-bridge://config":
        return json.dumps(_config_snapshot(_host_name()), indent=2)
    if key == "cli-bridge://lane-stats":
        return json.dumps(telemetry.lane_stats(), indent=2)
    if key == "cli-bridge://usage-summary":
        return json.dumps(telemetry.usage_report(), indent=2)
    if key == "cli-bridge://workflow-schemas/review-diff":
        return json.dumps(_REVIEW_DIFF_SCHEMA, indent=2)
    raise ValueError(f"unknown resource: {key}")


# ─────────────────────────────── execution helpers ───────────────────────────────

def _str(args: dict, key: str) -> str:
    """Coerce an arg to a clean string. JSON-RPC callers often send null -> must not become
    the literal 'None'."""
    val = args.get(key)
    return str(val).strip() if val is not None else ""


def _timeout(raw) -> int:
    try:
        t = int(raw)
    except (TypeError, ValueError):
        t = DEFAULT_TIMEOUT_S
    return max(1, min(t, MAX_TIMEOUT_S))


def _ask_all_timeout(raw) -> int:
    """Keep fan-out below typical MCP client call deadlines.

    Individual `ask_<lane>` calls may run for minutes, but `ask_all` needs room for every
    parallel lane plus optional synthesis before the host gives up on the MCP call.
    """
    try:
        t = int(raw)
    except (TypeError, ValueError):
        t = ASK_ALL_DEFAULT_TIMEOUT_S
    return max(1, min(t, ASK_ALL_MAX_TIMEOUT_S))


def _ask_all_include_paid(args: dict) -> bool:
    # One shared rule (config.include_paid_resolved): saver = include_paid refused, enforced.
    return config.include_paid_resolved(args.get("include_paid"))


def _ask_all_targets(lanes: list[LaneSpec], include_paid: bool,
                     skip_cooled: bool = True) -> list[LaneSpec]:
    out = [ln for ln in lanes if include_paid or (not ln.is_paid and not ln.is_limited)]
    if skip_cooled:
        out = [ln for ln in out if telemetry.cooldown_remaining(ln.key) == 0]
    return out


def _cache_key(lane: LaneSpec, model: str, effort: str, agent: str, cwd: str,
               task: str, terse_level: str) -> str:
    raw = "\x00".join([lane.key, model, effort, agent, cwd or "", terse_level, task])
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


# Transient kinds worth a quick retry (a flaky CLI blip). NOT timeout (would burn another full
# wait), nor quota/auth/not_found (those are sticky and cooled — retrying just wastes a call).
_RETRYABLE = {"failed", "spawn"}


async def _spawn_with_retry(argv: list[str], timeout: int, cwd: str | None,
                            env: dict | None = None, *, retry: bool = True) -> runner.RunResult:
    """Run the CLI, retrying a TRANSIENT failure up to CLI_BRIDGE_RETRIES times with backoff —
    so an occasionally-flaky lane 'works the first time' from the caller's point of view.

    `retry=False` for a spawn that is NOT replayable: the loop re-runs the SAME argv, which is
    only safe when running it twice means the same thing as running it once."""
    attempts = config.retries() + 1 if retry else 1
    res = await runner.arun(argv, timeout, cwd, env)
    n = 1
    while not res.ok and res.kind in _RETRYABLE and n < attempts:
        await asyncio.sleep(min(0.4 * (2 ** (n - 1)), 3.0))
        res = await runner.arun(argv, timeout, cwd, env)
        n += 1
    return res


def _write_trace(lane: LaneSpec, model: str, argv: list[str], cwd: str | None,
                 timeout: int, res: runner.RunResult) -> None:
    """Best-effort reproducible trace (redacted argv + output, timing) for debug/audit. Off
    unless CLI_BRIDGE_TRACE_DIR is set. Never raises into a delegation."""
    d = config.trace_dir()
    if not d:
        return
    try:
        os.makedirs(d, exist_ok=True)
        rec = {"ts": time.time(), "lane": lane.key, "model": model,
               "argv": [runner.redact(a) for a in argv], "cwd": cwd or "", "timeout_s": timeout,
               "ok": res.ok, "kind": res.kind, "exit_code": res.exit_code,
               "latency_ms": res.latency_ms,
               "output_chars": len(res.output), "output": runner.redact(res.output)[:4000]}
        h = hashlib.sha1("\x00".join(argv).encode("utf-8", "replace")).hexdigest()[:10]
        with open(os.path.join(d, f"{lane.key}-{h}.json"), "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2)
    except OSError:
        pass


def _mock_answer(lane: LaneSpec, model: str, task: str) -> str:
    return (f"[mock:{lane.key}] dry-run — no CLI spawned (CLI_BRIDGE_MOCK). "
            f"model={model or 'default'} would answer:\n{task[:300]}")


def _readonly_guard_snapshot(agent: str, expanded: str | None):
    """Pre-spawn workspace snapshot for the opt-in read-only mutation guard. Returns
    (snapshot, repo_root), or (None, "") when the guard is off, the run isn't read-only, or cwd
    isn't a git repo. Cheap: one `git status` only when the toggle is on."""
    if agent == "build" or not expanded or not config.verify_plan_readonly():
        return None, ""
    root, _err = worktrees._repo_root(expanded)
    if not root:                               # not a git repo -> nothing to diff against
        return None, ""
    return worktrees._porcelain(root), root


def _readonly_guard_diff(root: str, before: dict) -> list[str]:
    """Paths that changed/appeared since `before` — i.e. what a 'read-only' delegate wrote."""
    after = worktrees._porcelain(root)
    return sorted(p for p, s in after.items() if before.get(p) != s)


def _readonly_mutation_banner(paths: list[str]) -> str:
    """Prominent warning prepended to a read-only delegate's answer when it wrote files anyway."""
    shown = "\n".join(f"  - {p}" for p in paths[:20])
    more = f"\n  …and {len(paths) - 20} more" if len(paths) > 20 else ""
    return ("⚠️ WORKSPACE MUTATION DETECTED — this lane ran READ-ONLY (plan) but changed "
            f"{len(paths)} path(s) in the repo. cli-bridge did NOT revert them; review/restore if "
            f"unexpected (git checkout / git clean).\n{shown}{more}\n\n---\n\n")


_workspace_cache: str | None = None


def _path_from_root_uri(uri: str) -> str:
    """`file:///Users/x/repo` -> `/Users/x/repo`. Non-file schemes and junk yield ""."""
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "file":
        return ""
    return urllib.request.url2pathname(parsed.path)   # handles %20 and Windows /C:/…


async def _workspace_root() -> str:
    """Where a delegate should run when the caller named no cwd. "" = keep the inherited cwd.

    A host launches a user-scoped MCP server from $HOME, not from the project, so the cwd we
    inherit is an accident — yet it decides real things. `claude --continue` and the /resume
    picker are scoped to the current directory, so a delegated session filed under $HOME is
    invisible from the repo it is about; and an agent='build' delegate with no cwd edits files
    there. MCP roots are the protocol's own answer to "what is the workspace": ask once, keep it.
    Deprecated in revision 2026-07-28 (SEP-2577) but still served — when a successor lands, this
    function is the only thing that changes.
    """
    global _workspace_cache
    forced = config.default_cwd()
    if forced:                                 # explicit config always wins over asking the host
        path = os.path.expanduser(forced)
        if os.path.isdir(path):
            return path
        runner.log.warning("CLI_BRIDGE_DEFAULT_CWD=%r is not a directory; ignoring", forced)
        return ""
    if _workspace_cache is not None:
        return _workspace_cache
    ctx = mcp_compat.request_ctx(server)
    if ctx is None:                            # no host to ask: human CLI, async job, tests
        return ""
    try:
        caps = getattr(getattr(ctx.session, "client_params", None), "capabilities", None)
        if getattr(caps, "roots", None) is None:
            _workspace_cache = ""              # host declares no roots — don't ask on every call
            return ""
        with warnings.catch_warnings():        # mcp 2.x flags roots as deprecated; still served
            warnings.simplefilter("ignore")
            result = await ctx.session.list_roots()
        for root in result.roots or []:
            path = _path_from_root_uri(str(root.uri))
            if path and os.path.isdir(path):
                _workspace_cache = path
                return path
        _workspace_cache = ""                  # host answered, nothing usable in it
        return ""
    except Exception:                          # noqa: BLE001 — never break a delegation over this
        return ""                              # uncached: a live host may answer next time


async def _run_lane(lane: LaneSpec, args: dict, *, tool: str = "ask",
                    terse: bool = True) -> runner.RunResult:
    task = _str(args, "task")
    if not task:
        return runner.RunResult(False, "task is required", "failed")
    model = lane.model_for(_str(args, "model"))
    # M11-7: a non-paid lane resolving to a paid opencode-go/* model (usually a per-call override)
    # spends real credits — the doctor cost-mismatch only catches the DEFAULT model, so warn here
    # too. Best-effort log (no behaviour change): visible with CLI_BRIDGE_LOG=warning.
    if not lane.is_paid and lanes_mod.is_paid_opencode_model(model):
        runner.log.warning("%s is a free lane but model %r spends credits (opencode-go/*)",
                           lane.key, model)
    if config.mock():                          # dry-run: canned answer, no spawn
        return runner.RunResult(True, _mock_answer(lane, model, task), "ok", latency_ms=0)
    # Re-entry guard: a delegate cli-bridge spawns is given CLI_BRIDGE_DEPTH below. If THIS bridge
    # is already a delegate at/over the cap, it must not spawn another — else a delegate configured
    # to load cli-bridge could fork-bomb the council and the user's quota.
    depth = config.current_depth()
    if depth >= config.max_depth():
        return runner.RunResult(False, (
            f"re-entry guard: this cli-bridge is a delegate at depth {depth} (max "
            f"{config.max_depth()}); refusing to spawn another to avoid recursion. Raise "
            "CLI_BRIDGE_MAX_DEPTH only if you deliberately want nested delegation."),
            "blocked")
    # Spend guard (budget.py): the one pre-spawn chokepoint — per-lane daily run limit
    # (any lane) + daily credit cap (paid or CREDITS_PER_1K-rated lanes).
    block_reason = budget.check_spawn(lane)
    if block_reason:
        return runner.RunResult(False, block_reason, "blocked")
    agent = _str(args, "agent").lower()
    if agent not in {"", "plan", "build"}:    # never let a hallucinated value enable writes
        agent = "plan"
    if agent == "build" and config.build_disabled():   # team lock: no delegate edits files
        agent = "plan"
    effort = _str(args, "effort")
    cwd = _str(args, "cwd")
    expanded = os.path.expanduser(cwd) if cwd else None
    if expanded and not os.path.isdir(expanded):
        return runner.RunResult(False, f"cwd `{cwd}` is not an existing directory", "failed")
    if expanded is None:                       # caller named none -> the host's workspace, if any
        expanded = await _workspace_root() or None
    # Opt-in response cache (CLI_BRIDGE_CACHE_TTL_S>0): an identical call returns the stored
    # answer instead of re-spawning the CLI. Keyed on everything that changes the output,
    # incl. the terse level (it changes the prompt) and a build run is never served stale.
    terse_level = preamble.level() if terse else "off"
    ttl = config.CACHE_TTL_S
    key = ""
    # Never cache native-session turns: the same prompt means something different inside a
    # session (the CLI holds prior context the cache key can't see).
    if ttl > 0 and agent != "build" and not args.get("_native_argv"):
        key = _cache_key(lane, model, effort, agent, expanded or "", task, terse_level)
        hit = telemetry.cache_get(key, ttl)
        if hit is not None:
            return runner.RunResult(hit[0], hit[1], hit[2], latency_ms=0)
    # Compress the FINAL answer (cuts host context + delegate output tokens). Skipped for
    # structured-output tools (terse=False) so JSON stays intact. Telemetry keys on the raw
    # task, not the prefixed prompt.
    task = preamble.with_role(_str(args, "role"), task)   # V.2: optional named persona
    raw_images = args.get("images")                        # V.3: vision, shape declared per lane
    img_paths = ([os.path.abspath(os.path.expanduser(str(p))) for p in raw_images if str(p).strip()]
                 if raw_images and isinstance(raw_images, list) and "images" in lane.caps else [])
    # Text-prefix lanes fold the paths into the prompt itself ("@" for gemini, bare for ollama).
    if img_paths and not lane.image_arg.startswith("-"):
        task = f"{task}\n\n{' '.join(lane.image_arg + p for p in img_paths)}"
    prompt = preamble.apply(task) if terse else task
    argv = [lane.bin] + lane.build_ask(prompt, model, effort, agent, lane.bin)
    # Native-session extras (conversation turns only): inserted just before the PROMPT, found by
    # position rather than assumed to be the tail. Custom lanes can declare a native_session
    # (lanes.py's JSON loader builds one), and a template may well end in a flag's value —
    # splicing at the tail would then land between a flag and what it takes.
    native_extra = args.get("_native_argv")
    if native_extra and len(argv) > 1:
        i = argv.index(prompt) if prompt in argv else len(argv) - 1
        argv = argv[:i] + [str(a) for a in native_extra] + argv[i:]
    # Flag lanes get their images AFTER that splice, and after the task: codex's `-i <FILE>...` and
    # opencode's `-f` are variadic and would otherwise swallow the prompt (verified live 2026-07).
    if img_paths and lane.image_arg.startswith("-"):
        argv += [a for p in img_paths for a in (lane.image_arg, p)]
    # Some lanes select the model via ENV (e.g. vibe's VIBE_ACTIVE_MODEL), not a flag. Merge any
    # such overrides onto a COPY of the environment (a bare dict would drop the CLI's own PATH/auth).
    extra_env = lane.env_ask(model, effort, agent) if lane.env_ask else {}
    # Opt-in nested-session guard: strip the host's own CLAUDE_*/CODEX_* session markers so a
    # delegate `claude`/`codex` doesn't refuse to run "inside a session" (auth tokens kept).
    base_env = config.strip_nesting(dict(os.environ)) if config.strip_nesting_env() else os.environ
    # Always stamp the child's depth (current+1) so a delegate that itself loads cli-bridge trips
    # the re-entry guard above. Merge onto a COPY of the env (a bare dict drops the CLI's PATH/auth).
    spawn_env = {**base_env, **extra_env, "CLI_BRIDGE_DEPTH": str(depth + 1)}
    await runner.pace(lane.key, lane.min_interval_s)   # anti-burst (opt-in, per lane)
    # Opt-in read-only guard: snapshot the workspace before a 'plan' delegate runs (no-op unless
    # CLI_BRIDGE_VERIFY_PLAN_READONLY is on and cwd is a git repo).
    ro_before, ro_root = _readonly_guard_snapshot(agent, expanded)
    rec = telemetry.start(tool, lane.key, model, task, role=_str(args, "role"))
    timeout = _timeout(args.get("timeout_s"))
    t0 = time.monotonic()
    # A spawn carrying STATE is not idempotent, so replaying it does not retry — it corrupts.
    # A minted --session-id collides on the second attempt ("Session ID … is already in use",
    # which then MASKS the transient error that caused the retry); a --resume re-delivers the
    # same delta into a session that already ingested it; a build agent re-edits a tree it has
    # already changed. Gated on the session HANDLE, not on _native_argv: opencode's capture-first
    # turn passes --print-logs with no handle, and it is still perfectly safe to retry.
    res = await _spawn_with_retry(argv, timeout, expanded, spawn_env,
                                  retry=not (agent == "build" or args.get("_native_sid")))
    res.latency_ms = int((time.monotonic() - t0) * 1000)
    res.model = model                          # provenance: the resolved model that actually ran
    if ro_before is not None and res.ok:       # read-only delegate that wrote files -> flag (no revert)
        mutated = _readonly_guard_diff(ro_root, ro_before)
        if mutated:
            res.output = _readonly_mutation_banner(mutated) + res.output
            res.mutated = True
    telemetry.record(rec, res.ok, res.kind, len(res.output), input_chars=len(prompt))
    _write_trace(lane, model, argv, expanded, timeout, res)
    if key and res.ok:                        # cache only successes; failures are transient
        telemetry.cache_put(key, res.ok, res.output, res.kind)
    if res.ok:
        _refresh_models_soon(lane)
    return res


def _refresh_models_soon(lane: LaneSpec) -> None:
    """Re-list this lane's models in the background when the remembered set has gone stale.

    Listing costs a subprocess, so it must never sit in front of an answer — and it can't run
    while tool schemas are built either (that would put a spawn on the listing path). Doing it
    just after a lane has answered is the one moment it is both free of the caller's latency and
    known to be working. Fire-and-forget: a failure leaves the previous list in place."""
    _, stale = lanes_mod.known_models(lane)
    if not stale or lane.models_args is None:
        return
    argv = [lane.bin] + lane.models_args       # bound here: the closure can't re-narrow the None

    async def _go() -> None:
        with contextlib.suppress(Exception):   # never let a background refresh reach a delegation
            probe = await runner.arun(argv, 30)
            if probe.ok:
                telemetry.lane_models_set(lane.key, lanes_mod.parse_model_ids(probe.output))
    with contextlib.suppress(RuntimeError):    # no running loop (sync CLI path) -> just skip
        asyncio.get_running_loop().create_task(_go())


async def _run_lane_maybe_convo(lane: LaneSpec, args: dict) -> tuple[runner.RunResult, str]:
    """Round-table wrapper around _run_lane. With no `conversation` it's a plain ask (zero
    change). With one, it replays the thread's recipient-aware history before the task, runs the
    lane, then records the exchange so the NEXT turn — on this or another lane — sees it.
    Returns (result, conversation_id) where the id is "" when no thread is in play."""
    cid = _str(args, "conversation").strip()
    if not cid:
        # Auto-thread: run as a plain ask (no replay, no native session — nothing to resume yet),
        # then record the one exchange under a fresh id so it's resumable later without the caller
        # having had to pass conversation='new'. Cache/behaviour of the run itself are unchanged.
        if not config.convo_autothread_enabled():
            return await _run_lane(lane, args), ""
        res = await _run_lane(lane, args)
        task = _str(args, "task")
        if not (task and res.ok):           # nothing real to record → stay stateless, no dangling id
            return res, ""
        cid = conversations.new_id()
        conversations.record_turn(cid, lane.key, "user", task)
        conversations.record_turn(cid, lane.key, "assistant", res.output)
        return res, cid
    if cid.lower() == "new":
        cid = conversations.new_id()
    elif not conversations.is_valid_id(cid):
        return runner.RunResult(False, f"invalid conversation id: {cid!r}", "failed"), ""
    task = _str(args, "task")
    sub = dict(args)
    # Native session continuity (claude mint / opencode capture …): the lane's own session
    # carries the turns it has already seen, so the prompt replays only the DELTA other lanes
    # added since. Replay stays the cross-lane source of truth (sqlite records every turn).
    # Not under mock: nothing is spawned, so a handle committed here names a session that was
    # never created. Turn mock off mid-thread and the next real turn resumes a ghost — with an
    # empty replay prefix, so it has no context from either store.
    ns = lane.native_session if config.native_sessions_enabled() and not config.mock() else None
    sid, last_seen = "", 0
    if ns:
        extra, sid, last_seen = conversations.native_step(ns, cid, lane.key)
        if extra:
            sub["_native_argv"] = extra
        if sid:                    # mint/resume only — a capture-first turn has no handle yet
            sub["_native_sid"] = sid
    prefix, trimmed = conversations.build_history_prefix(
        cid, lane.key, config.convo_max_chars(), since_turn=last_seen)
    # The high-water mark this prompt actually delivers. -1 when the delta was cut to fit the
    # budget, so it can never compare equal below.
    covered = -1 if trimmed else conversations.head_turn(cid)
    if prefix:
        sub["task"] = f"{prefix}\n{task}"
    res = await _run_lane(lane, sub)
    if ns and not res.ok and last_seen:        # broken resume → fall back to replay next turn
        conversations.native_drop(cid, lane.key)
    if task and res.ok:                        # only record a real exchange
        conversations.record_turn(cid, lane.key, "user", task)
        n = conversations.record_turn(cid, lane.key, "assistant", res.output)
        if ns:
            # Keep the handle only if this lane's session now holds EVERY turn below n. Three
            # ways the mark would otherwise lie: the delta was budget-trimmed, another lane
            # appended a turn while this spawn was awaiting, or the append itself failed (n=0).
            # A lying mark is permanent — later deltas filter on turn_number > last_turn, so the
            # skipped turns are never sent to this lane again. Dropping the handle only costs a
            # re-mint plus a full replay; replay remains the source of truth.
            if n and n - 2 == covered:
                conversations.native_commit(ns, cid, lane.key, sid,
                                            f"{res.err}\n{res.output}", n)
            else:
                conversations.native_drop(cid, lane.key)
        await _maybe_compact_convo(cid, lane)
    return res, cid


_COMPACT_FAILED_AT: dict[str, float] = {}     # thread id -> monotonic time of last failed fold
_COMPACT_RETRY_S = 600                        # don't re-pay the failed-summarizer latency every turn


async def _maybe_compact_convo(cid: str, lane: LaneSpec) -> None:
    """Rolling summary: once the stored thread outgrows the replay budget, the lane that just
    answered (it had the full history in front of it — no third model to route) condenses the
    old tail into one summary turn. Best-effort: any failure leaves the thread as it was, and
    a failed fold isn't retried for a while (a dead summarizer otherwise adds its timeout to
    EVERY subsequent turn of an over-budget thread)."""
    if not config.convo_summary_enabled():
        return
    try:
        failed_at = _COMPACT_FAILED_AT.get(cid)
        if failed_at is not None and time.monotonic() - failed_at < _COMPACT_RETRY_S:
            return
        upto, excerpt = conversations.compaction_plan(cid, config.convo_max_chars())
        if not upto:
            return
        res = await _run_lane(lane, {"task": conversations.SUMMARY_PROMPT + excerpt},
                              tool="convo_summary")
        if res.ok and res.output.strip():
            conversations.apply_compaction(cid, upto, res.output, lane.key)
            _COMPACT_FAILED_AT.pop(cid, None)
        else:
            _COMPACT_FAILED_AT[cid] = time.monotonic()
    except Exception:                          # noqa: BLE001 — never break the user's call
        pass


def _lane_by_key(key: str, lanes: list[LaneSpec]) -> LaneSpec | None:
    return next((ln for ln in lanes if ln.key == key), None)


# ─────────────────────────────── tool dispatch ───────────────────────────────

async def call_tool(name: str, args: dict) -> list[TextContent]:
    lanes, host = _active_lanes()

    if name == "setup":
        cur = _profile() + ("" if _profile_is_set() else " (default — not explicitly set)")
        reco = _setup_recommendation(lanes)
        return [_emit(f"Current profile: **{cur}**\n\n{reco}\n\n---\n{SETUP_TEXT}",
                      label="setup", guard=False)]

    if name == "doctor":
        text = await _doctor_deep(host, lanes) if bool(args.get("deep")) else _doctor(host)
        return [_emit(text, label="doctor", guard=False)]

    if name == "usage_report":
        since_s = _parse_since(_str(args, "since"))
        rep = telemetry.usage_report(since_s=since_s)
        # output_format is the project-wide name; accept legacy `format` too (no break).
        if (_str(args, "output_format") or _str(args, "format")).lower() == "json":
            return [_emit(json.dumps(rep, indent=2), label="usage_report", guard=False)]
        return [_emit(_render_usage(rep), label="usage_report", guard=False)]

    if name == "usage_budget":
        return [_emit(_render_budget(telemetry.usage_budget()), label="usage_budget", guard=False)]

    if name == "lane_stats":
        return [_emit(_render_lane_stats(), label="lane_stats", guard=False)]

    if name == "reset_lane_state":
        lane_key = _str(args, "lane")
        ok = telemetry.reset_lane(lane_key) if lane_key else False
        msg = (f"Lane '{lane_key}' cooldown/failure counters cleared." if ok
               else f"No state to clear for lane '{lane_key}' (already clean or unknown).")
        return [TextContent(type="text", text=msg)]

    if name == "ask_cascade":
        return await _ask_cascade(lanes, args)

    if name == "ask_best":
        return await _ask_best(lanes, args)

    if name == "rate_lane":
        return _rate_lane(lanes, args)

    if name == "set_lane_cost":
        return _set_lane_cost(args)

    if name == "route_plan":
        include_paid = (bool(args["include_paid"]) if args.get("include_paid") is not None
                        else _profile() == "max")
        mode = _str(args, "mode").lower()
        if mode and mode in router.MODES:
            perf = telemetry.lane_perf()
            quality = telemetry.lane_quality(mode)
            return [TextContent(type="text", text=router.explain_mode(
                lanes, telemetry.cooldown_remaining, lambda k: perf.get(k, {}), mode, include_paid,
                quality_of=lambda k: quality.get(k, {})))]
        return [TextContent(type="text", text=router.explain(
            lanes, telemetry.cooldown_remaining, include_paid))]

    if name == "ask_all":
        return await _ask_all(lanes, args)

    if name == "ask_all_async":
        if not _str(args, "task"):
            return [TextContent(type="text", text="[error] task is required")]
        job_id = jobs.start_job("ask_all", lambda: _ask_all_body(lanes, dict(args)),
                                preview=_str(args, "task"))
        return [TextContent(type="text", text=(
            f"Started background job `{job_id}` (ask_all). It runs while you keep working. "
            f"Check it with `job_status {job_id}`, fetch the answer with `job_result {job_id}`."))]

    if name == "job_status":
        info = jobs.status(_str(args, "job_id"))
        if info is None:
            return [TextContent(type="text", text=f"[error] unknown job_id: {_str(args, 'job_id')}")]
        if info.get("kind") == "build":                # fold in live build progress
            snap = buildloop.snapshot(_str(args, "job_id"))
            if snap:
                info = {**info, **snap}
        return [TextContent(type="text", text=_render_job_status(info))]

    if name == "job_result":
        r = jobs.result(_str(args, "job_id"))
        if r is None:
            return [TextContent(type="text", text=f"[error] unknown job_id: {_str(args, 'job_id')}")]
        st, body = r
        if st == jobs.RUNNING:
            return [TextContent(type="text", text=(
                "Job still running — poll `job_status` and fetch again when it's succeeded."))]
        if not body:
            return [TextContent(type="text", text=f"[{st}] job produced no output.")]
        return [_emit(body, label="job_result")]

    if name == "job_cancel":
        st = jobs.cancel(_str(args, "job_id"))
        msg = {"unknown": f"[error] unknown job_id: {_str(args, 'job_id')}",
               "cancelling": "Cancellation requested — the delegates' process groups are being "
                             "killed; poll `job_status` for the final state."}.get(
            st, f"Job is already **{st}** — nothing to cancel.")
        return [TextContent(type="text", text=msg)]

    if name == "jobs_list":
        return [TextContent(type="text", text=_render_jobs_list(jobs.listing()))]

    if name == "review_diff":
        return await _review_diff(lanes, args)

    if name == "security_review":
        targets = _ask_all_targets(lanes, _ask_all_include_paid(args))
        return [_emit(await workflows.security_review(targets, args, _run_lane),
                      label="security_review")]

    if name == "debate":
        targets = _ask_all_targets(lanes, _ask_all_include_paid(args))
        return [_emit(await workflows.debate(targets, args, _run_lane, progress=_emit_progress),
                      label="debate")]

    if name == "consensus":
        targets = _ask_all_targets(lanes, _ask_all_include_paid(args))
        return [_emit(await workflows.consensus(targets, args, _run_lane, progress=_emit_progress),
                      label="consensus")]

    if name == "challenge":
        key = _str(args, "lane")
        if key:
            ln = _lane_by_key(key, lanes)
            targets = [ln] if ln else []
        else:
            targets = _ask_all_targets(lanes, _ask_all_include_paid(args))
        return [_emit(await workflows.challenge(targets, args, _run_lane), label="challenge")]

    if name in ("commit_msg", "pr_describe"):
        key = _str(args, "lane")
        if key:
            ln = _lane_by_key(key, lanes)
            targets = [ln] if ln else []
        else:
            targets = _ask_all_targets(lanes, _ask_all_include_paid(args))
        fn = workflows.commit_msg if name == "commit_msg" else workflows.pr_describe
        return [_emit(await fn(targets, args, _run_lane), label=name)]

    if name == "premortem":
        targets = _ask_all_targets(lanes, _ask_all_include_paid(args))
        return [_emit(await workflows.premortem(targets, args, _run_lane), label="premortem")]

    if name == "test_plan":
        targets = _ask_all_targets(lanes, _ask_all_include_paid(args))
        return [_emit(await workflows.test_plan(targets, args, _run_lane), label="test_plan")]

    if name in ("ask_build", "ask_build_isolated"):
        key = _str(args, "lane")
        if key:
            lane = _lane_by_key(key, lanes)
        else:                                        # no lane named → first free build-capable
            lane = next((ln for ln in _ask_all_targets(lanes, False) if "agent" in ln.caps), None)
        if not lane:
            msg = (f"[error] no such lane: {key}." if key else
                   "[error] no free build-capable lane available.")
            return [TextContent(type="text", text=msg + " Pass a build-capable `lane`.")]
        if "agent" not in lane.caps:
            return [TextContent(type="text", text=(
                f"[error] lane '{key}' has no build/write mode."))]
        mode = _str(args, "mode") or "isolated"      # ask_build_isolated == ask_build mode=isolated
        if name == "ask_build" and mode == "direct":
            if bool(args.get("dry_run")):            # preview the brief, launch nothing
                zlabel = _str(args, "zone") or _str(args, "target_dir") or "the target directory"
                brief = worktrees._build_brief(_str(args, "task"), zlabel,
                                               interface=_str(args, "interface"),
                                               dod=_str(args, "dod"))
                return [_emit("# Dry run — brief preview (nothing was launched)\n\n" + brief,
                              label="ask_build")]
            if config.build_disabled():
                return [_emit("[error] direct builds are disabled on this machine "
                              "(CLI_BRIDGE_NO_BUILD). Use mode=isolated for a review-only diff.",
                              label="ask_build")]
            if bool(args.get("async")):              # steerable background build job
                state = buildloop.BuildState()
                _args = dict(args)
                job_id = jobs.start_job(
                    "build", lambda: buildloop.run_build(state, run_lane=_run_lane, lane=lane,
                                                         args=_args), preview=_str(args, "task"))
                state.log_path = jobs.log_path_for(job_id)
                buildloop.register(job_id, state)
                return [TextContent(type="text", text=(
                    f"Steerable build started: `{job_id}`. Follow it with `job_tail {job_id}`, "
                    f"steer with `build_steer {job_id} \"…\"` (interrupt=true to cut a turn), "
                    f"fetch the result with `job_result {job_id}`."))]
            return [_emit(await worktrees.ask_build_direct(
                lane, args, _run_lane, build_disabled=config.build_disabled()), label="ask_build")]
        architect = None
        akey = _str(args, "architect_lane")
        if akey:
            architect = _lane_by_key(akey, lanes)
            if not architect:
                return [TextContent(type="text", text=(
                    f"[error] no such architect_lane: {akey}."))]
        return [_emit(await worktrees.ask_build_isolated(lane, args, _run_lane, architect=architect),
                      label=name)]

    if name == "job_tail":
        tailed = buildloop.tail(_str(args, "job_id"), int(args.get("offset") or 0))
        if tailed is None:
            return [TextContent(type="text", text=(
                "No live build for that job_id (it may have finished — use `job_result`, or it "
                "was started in another server process)."))]
        new_offset, chunk = tailed
        body = chunk if chunk else "_(no new output yet)_"
        return [_emit(f"offset={new_offset}\n{body}", label="job_tail", guard=False)]

    if name == "build_steer":
        msg = buildloop.steer(_str(args, "job_id"), _str(args, "instruction"),
                              interrupt=bool(args.get("interrupt")))
        if msg == "unknown":
            return [TextContent(type="text", text=(
                "No live build for that job_id (already finished, or started elsewhere)."))]
        return [TextContent(type="text", text=msg)]

    if name == "batch_run":
        raw = args.get("tasks")
        tasks = [t for t in raw if isinstance(t, dict) and t.get("task")] if isinstance(raw, list) \
            else []
        if not tasks:
            return [TextContent(type="text", text=(
                "[error] tasks must be a non-empty list of {task, lane?, model?, effort?, cwd?}."))]
        if len(tasks) > orchestrate.MAX_BATCH_TASKS:
            return [TextContent(type="text", text=(
                f"[error] too many tasks ({len(tasks)} > {orchestrate.MAX_BATCH_TASKS}). Split it."))]
        default_lanes = _ask_all_targets(lanes, _ask_all_include_paid(args))
        default_lane = default_lanes[0] if default_lanes else None

        def _resolve(k):
            return _lane_by_key(k, lanes)

        if bool(args.get("dry_run")):              # cost envelope, nothing spawned
            env = orchestrate.estimate(tasks, resolve_lane=_resolve, default_lane=default_lane,
                                       telemetry=telemetry)
            return [_emit(orchestrate.render_estimate(env), label="batch_run", guard=False)]

        async def _batch_body():
            rid, res = await orchestrate.batch_run(
                tasks, run_lane=_run_lane, resolve_lane=_resolve, default_lane=default_lane,
                telemetry=telemetry, run_id=_str(args, "resume_id"),
                max_concurrency=int(args.get("max_concurrency") or 0),
                max_calls=int(args.get("max_calls") or 0),
                max_credits=float(args.get("max_credits") or 0.0))
            return orchestrate.render_batch(rid, res)
        if bool(args.get("async")):
            job_id = jobs.start_job("batch", _batch_body, preview=f"{len(tasks)} tasks")
            return [TextContent(type="text", text=(
                f"Batch started: `{job_id}`. Poll `job_status {job_id}`, fetch `job_result "
                f"{job_id}`."))]
        return [_emit(await _batch_body(), label="batch_run")]

    if name == "workflow":
        return await _run_workflow_preset(args, lanes)

    if name == "conversations_list":
        rows = telemetry.convo_list()
        if not rows:
            return [_emit("No round-table threads yet. Start one: call any ask_<lane> with "
                          "conversation='new', then reuse the returned id (on any lane).",
                          label="conversations_list", guard=False)]
        lines = ["# Round-table conversations", ""]
        for row in rows:
            lanes_txt = ", ".join(row["lanes"]) or "—"
            lines.append(f"- **{row['conversation_id']}** · {row['turns']} turns · {lanes_txt} · "
                         f"{_rel_time(row['last_at'])}\n      {row['preview']}")
        return [_emit("\n".join(lines), label="conversations_list", guard=False)]

    if name == "conversation_show":
        cid = _str(args, "conversation").strip()
        turns = telemetry.convo_turns(cid)
        if not turns:
            return [_emit(f"[conversation: {cid or '(none)'}] no turns found. "
                          "List threads with conversations_list.",
                          label="conversation_show", guard=False)]
        parts = [f"# Conversation {cid}", ""]
        for t in turns:
            if t["role"] == "summary":
                who = f"Summary of earlier turns (by {t['lane'] or 'a lane'})"
            else:
                who = "User" if t["role"] == "user" else (t["lane"] or "assistant")
            parts.append(f"## Turn {t['turn_number']} — {who}\n{t['content']}")
        return [_emit("\n\n".join(parts), label="conversation_show")]

    if name.startswith("ask_"):
        key = name[4:]
        lane = _lane_by_key(key, lanes)
        if not lane:
            # The host's OWN lane. Visible/callable by default; in CLI_BRIDGE_HIDE_HOST mode it is
            # allowed only with an explicit model (a SIBLING consult, not re-asking yourself).
            own = _host_lane(host)
            if own and own.key == key:
                if config.hide_host() and not _str(args, "model"):
                    return [TextContent(type="text", text=(
                        f"[error] ask_{key} is your own family — pass an explicit `model` to "
                        "consult a SIBLING model (e.g. claude-opus-4-6). Re-asking the model "
                        "you're already running is pointless."))]
                lane = own
            else:
                avail = ", ".join(ln.key for ln in lanes) or "none installed"
                return [TextContent(type="text", text=(
                    f"[error] no such lane: {key}. Available: {avail}. Run `doctor` for install "
                    "hints, or set CLI_BRIDGE_MOCK=1 to try without any CLI."))]
        res, cid = await _run_lane_maybe_convo(lane, args)
        out = res.render()
        if cid:
            out = f"[conversation: {cid}] — reuse this id (on any lane) to continue the thread.\n\n{out}"
        out = _echo_header(lane.key, res.model, _str(args, "task")) + out
        return [_emit(out, label=f"ask_{lane.key}")]

    if name == "list_models":
        key = _str(args, "lane")
        lane = _lane_by_key(key, lanes)
        if not lane:
            avail = ", ".join(ln.key for ln in lanes) or "none installed"
            return [TextContent(type="text",
                                text=f"[error] no such lane: {key or '(none)'}. Available: {avail}.")]
        if lane.models_args is not None:
            res = await runner.arun([lane.bin] + lane.models_args, 60)
            if res.ok:      # remember it, so the `model` parameter can name these for free later
                telemetry.lane_models_set(lane.key, lanes_mod.parse_model_ids(res.output))
            return [_emit(res.render(), label=f"list_models:{lane.key}")]
        # No list command, but the CLI may cache the set the server said this account can use.
        cached = models_from_file(lane.models_file) if lane.models_file else []
        if cached:
            listing = "\n".join(f"- {m}" + (f" — {d}" if d else "") for m, d in cached)
            return [_emit(f"{lane.display}: the CLI exposes no model-list command; this is the set "
                          f"it cached from the server for YOUR account (read from "
                          f"{lane.models_file}).\n{listing}", label=f"list_models:{lane.key}")]
        # Nothing discoverable — surface the resolved default + how to choose.
        dm = lane.model_for("")
        how = (f"pass model=… per call, or set CLI_BRIDGE_{lane.key.upper()}_MODEL"
               if "model" in lane.caps else "this lane uses its own model (not selectable here)")
        return [_emit(f"{lane.display}: no model-list command exposed by the CLI. "
                      f"Default model: {dm or '(the CLI default)'}. To choose: {how}.",
                      label=f"list_models:{lane.key}", guard=False)]

    if name.startswith("list_") and name.endswith("_models"):
        lane = _lane_by_key(name[5:-7], lanes)
        if not lane or (lane.models_args is None and not lane.models_file):
            return [TextContent(type="text", text=f"[error] no model list for: {name}")]
        if lane.models_args is None:                      # cached-file lanes (see list_models above)
            cached = models_from_file(lane.models_file)
            listing = "\n".join(f"- {m}" + (f" — {d}" if d else "") for m, d in cached)
            return [_emit(listing or f"[error] could not read {lane.models_file}",
                          label=f"list_{lane.key}_models")]
        res = await runner.arun([lane.bin] + lane.models_args, 60)
        if res.ok:
            telemetry.lane_models_set(lane.key, lanes_mod.parse_model_ids(res.output))
        return [_emit(res.render(), label=f"list_{lane.key}_models")]

    return [TextContent(type="text", text=f"[error] unknown tool: {name}")]


async def _ask_cascade(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    # Thin glue: the cascade itself lives in council.py; inject the host couplings.
    return await council.ask_cascade(lanes, args, run_lane=_run_lane, emit=_emit)


async def _ask_best(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    # Thin glue: ask_best lives in council.py; inject the host couplings.
    return await council.ask_best(lanes, args, run_lane=_run_lane, emit=_emit)


def _rate_lane(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    """Record the host's quality score for a lane on a task-type (outcome-tracked routing). Pure
    dispatch glue: validates, writes via telemetry, reports the lane's new running average."""
    ln = _lane_by_key(_str(args, "lane"), lanes)
    if ln is None:
        return [TextContent(type="text", text=(
            f"[error] unknown lane '{_str(args, 'lane')}'. See `doctor` for lane keys."))]
    try:
        # args.get returns an untyped JSON-RPC value; the except IS the validation (None/str/etc).
        score = int(args.get("score"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return [TextContent(type="text", text="[error] score must be an integer 1..5.")]
    if not 1 <= score <= 5:
        return [TextContent(type="text", text="[error] score must be between 1 and 5.")]
    mode = _str(args, "mode").lower()
    if mode and mode not in router.MODES:
        return [TextContent(type="text", text=(
            f"[error] unknown mode '{mode}'. One of: {', '.join(router.MODES)} — or omit it."))]
    res = telemetry.rate_lane(ln.key, mode, score, _str(args, "note"))
    where = f" for mode '{mode}'" if mode else ""
    if res.get("n"):
        return [TextContent(type="text", text=(
            f"Recorded {score}/5 for {ln.key}{where}. Now {res['n']} rating(s), avg "
            f"{res['avg']}/5 — ask_best will weight {ln.key} accordingly for {mode or 'this'} tasks."))]
    return [TextContent(type="text", text=(
        f"Recorded {score}/5 for {ln.key}{where}, but telemetry is off "
        "(CLI_BRIDGE_TELEMETRY) so it won't steer routing."))]


def _set_lane_cost(args: dict) -> list[TextContent]:
    """Persist a cost fact the host learned (from the user's words or its own knowledge): set the
    lane's tier (+ optional why-note) in THIS process now, and merge it into the JSON config file
    so it survives restarts — the self-maintaining half of the cost policy. Uses all_lanes(), not
    the host-filtered list: the user may well be telling us about the HOST's own lane."""
    lane_key = _str(args, "lane")
    ln = _lane_by_key(lane_key, all_lanes())
    if ln is None:
        return [TextContent(type="text", text=(
            f"[error] unknown lane '{lane_key}'. See `doctor` for lane keys."))]
    cost = _str(args, "cost").lower()
    if cost not in {"free", "limited", "paid"}:
        return [TextContent(type="text", text="[error] cost must be free, limited or paid.")]
    note = _str(args, "note")[:200]
    if not note:
        # Anti-injection friction: every cost write must state its provenance. A delegate's
        # output can't quietly rewrite the policy through the host without leaving a why.
        return [TextContent(type="text", text=(
            "[error] note is required — one line saying who/what established this, e.g. "
            "'user: on the Go plan' or 'vendor: free tier sunset 2026-06-18'."))]
    env_key = ln.key.upper().replace("-", "_")
    shadowed = f"CLI_BRIDGE_{env_key}_COST" in config.ENV_PRESET_KEYS
    os.environ[f"CLI_BRIDGE_{env_key}_COST"] = cost          # effective immediately
    os.environ[f"CLI_BRIDGE_{env_key}_COST_NOTE"] = note
    fields: dict = {"cost": cost, "cost_note": note}
    path = config.update_config_file({ln.key: fields})
    persisted = (f"persisted to `{path}`" if path
                 else "applied for THIS session only — config file not writable")
    why = f" — {note}" if note else ""
    caveat = ""
    if shadowed and path:
        caveat = (f"\n⚠️ Your MCP host config/shell also sets CLI_BRIDGE_{env_key}_COST — env "
                  "wins at every restart, so that value will override this persisted one. "
                  "Remove it from the host config to let the config file apply.")
    return [TextContent(type="text", text=(
        f"Lane **{ln.key}** cost set to **{cost}** (set by you){why}. {persisted}. "
        "ask_all / ask_cascade / ask_best route on it from the next call." + caveat))]


async def _ask_all(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    out = await _ask_all_body(lanes, args)
    return [_emit(_echo_header("council (ask_all)", "", _str(args, "task")) + out,
                  label="ask_all")]


async def _run_workflow_preset(args: dict, lanes: list[LaneSpec]) -> list[TextContent]:
    """Dispatch a `workflow` preset over the durable orchestrate substrate. Lane resolution +
    _run_lane are injected so orchestrate stays testable. Each preset returns a string report;
    async=true wraps it in a background job."""
    preset = _str(args, "preset")
    default_lanes = _ask_all_targets(lanes, _ask_all_include_paid(args))

    def _resolve(k):
        return _lane_by_key(k, lanes)

    common = dict(run_lane=_run_lane, resolve_lane=_resolve, default_lanes=default_lanes,
                  telemetry=telemetry, run_id=_str(args, "resume_id"))
    judge = _str(args, "judge_lane") or None
    if preset == "refine_plan":
        def make():
            return orchestrate.refine_plan(**common, plan_file=_str(args, "plan_file"),
                                           plan=_str(args, "plan"), lanes=args.get("lanes"),
                                           angles=args.get("angles"), judge_lane=judge)
    elif preset == "council_review":
        def make():
            return orchestrate.council_review(
                **common, question=_str(args, "question") or _str(args, "task"),
                lanes=args.get("lanes"), judge_lane=judge)
    elif preset == "map_review":
        def make():
            return orchestrate.map_review(**common, files=args.get("files") or [],
                                          lane=_str(args, "lane") or None, judge_lane=judge)
    elif preset == "research_verify":
        def make():
            return orchestrate.research_verify(**common, questions=args.get("questions") or [],
                                               lanes=args.get("lanes"))
    elif preset == "verify_repair":
        try:
            max_rounds = int(args.get("max_rounds") or 3)
        except (TypeError, ValueError):
            max_rounds = 3

        def make():
            # verify_repair is a sequential dependent loop (not a fan-out), so it does NOT use the
            # batch journal — pass only what it needs, not the durable **common.
            return orchestrate.verify_repair(
                run_lane=_run_lane, resolve_lane=_resolve, default_lanes=default_lanes,
                task=_str(args, "task"), builder_lane=_str(args, "builder_lane"),
                verifier_lane=_str(args, "verifier_lane"), max_rounds=max_rounds,
                cwd=_str(args, "cwd"), cross_family=bool(args.get("cross_family")))
    elif preset == "fanout_compare":
        def make():
            return orchestrate.fanout_compare(**common, task=_str(args, "task"),
                                              lanes=args.get("lanes"), judge_lane=judge,
                                              cwd=_str(args, "cwd"))
    elif preset == "jury":
        def make():
            return orchestrate.jury(
                **common, task=_str(args, "task"), author_lane=_str(args, "author_lane"),
                verifier_lanes=args.get("verifier_lanes"),
                verifiers=int(args.get("verifiers") or 0),
                threshold=int(args.get("threshold") or 0), cwd=_str(args, "cwd"))
    elif preset == "converge":
        try:
            c_rounds = min(int(args.get("max_rounds") or 5), orchestrate.VERIFY_MAX_ROUNDS)
        except (TypeError, ValueError):
            c_rounds = 5

        def make():
            return orchestrate.converge(
                **common, task=_str(args, "task"), author_lane=_str(args, "author_lane"),
                arbiter_lane=_str(args, "arbiter_lane"), peer_lanes=args.get("peer_lanes"),
                peers=int(args.get("verifiers") or 0), max_rounds=c_rounds, cwd=_str(args, "cwd"))
    else:
        return [TextContent(type="text", text=f"[error] unknown preset: {preset or '(none)'}")]

    if bool(args.get("async")):
        job_id = jobs.start_job(f"workflow:{preset}", make, preview=preset)
        return [TextContent(type="text", text=(
            f"Workflow `{preset}` started: `{job_id}`. Poll `job_status {job_id}`, fetch "
            f"`job_result {job_id}`."))]
    return [_emit(await make(), label=f"workflow:{preset}")]


async def _ask_all_body(lanes: list[LaneSpec], args: dict) -> str:
    # Thin glue: the fan-out lives in council.py. Inject host couplings (run_lane/progress/
    # host_sample) and the cost-policy helpers that stay in server.py (shared by dispatch).
    return await council.ask_all_body(
        lanes, args, run_lane=_run_lane, progress=_emit_progress, host_sample=_host_sample,
        include_paid_fn=_ask_all_include_paid, targets_fn=_ask_all_targets,
        timeout_fn=_ask_all_timeout)


async def _review_diff(lanes: list[LaneSpec], args: dict) -> list[TextContent]:
    # Same cost policy as ask_all: free/non-limited reviewers unless the caller widens, and
    # never a cooled lane. Then hand off to the (decoupled, testable) workflow engine.
    include_paid = _ask_all_include_paid(args)
    targets = _ask_all_targets(lanes, include_paid)
    report = await workflows.review_diff(targets, args, _run_lane)
    return [_emit(report, label="review_diff")]


# doctor lives in reports.py; these wrappers inject the host-detection (_is_host) and lane-runner
# (_run_lane) couplings that stay here, so the test-pinned server._doctor(host) surface is intact.
def _doctor(host: str) -> str:
    return reports.doctor(host, is_host=_is_host)


async def _doctor_deep(host: str, lanes: list[LaneSpec]) -> str:
    return await reports.doctor_deep(host, lanes, is_host=_is_host, run_lane=_run_lane)


# Bind the six handlers above to the installed SDK. Kept here at the bottom (rather than as
# @decorators) because mcp 2.0 removed them; mcp_compat is the only module that knows which
# major is present. The functions themselves are untouched and still callable directly.
mcp_compat.register(
    server, list_tools=list_tools, call_tool=call_tool, list_prompts=list_prompts,
    get_prompt=get_prompt, list_resources=list_resources, read_resource=read_resource)


def main() -> None:
    config.apply_file_config_to_env()   # JSON config fills any unset env var (env still wins)
    # Any job left 'running' in the DB is from a previous process whose delegates are gone —
    # flip it to 'interrupted' so its status is honest (v1 doesn't resume work across restarts).
    jobs.mark_interrupted_on_startup()
    async def _serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
