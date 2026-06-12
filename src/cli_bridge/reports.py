"""Human-readable reports + lane diagnostics rendered from local state.

`doctor`/`doctor_deep` (health check + live auth/flag probes), the `_render_*` markdown
formatters for usage/budget/jobs/lane-stats, `_setup_recommendation` onboarding, and small
time helpers. Pulled out of server.py so the dispatch module stays thin. Pure display +
best-effort `--help`/`--version` probes; `doctor`/`doctor_deep` take their host-detection
(`is_host`) and lane-runner (`run_lane`) couplings injected, the same pattern as council.py.
"""
from __future__ import annotations

import asyncio
import re
import time

from . import config, jobs, preamble, runner, telemetry
from . import lanes as lanes_mod
from .detect import is_installed
from .lanes import LaneSpec, all_lanes


def _rel_time(ts: float | None) -> str:
    if not ts:
        return "?"
    s = max(0, int(time.time() - ts))
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def _setup_recommendation(lanes: list[LaneSpec]) -> str:
    """Beginner-proof onboarding: detect what's installed, sort it by what it costs the user,
    and RECOMMEND a concrete profile + cap they can accept or tweak — so nobody has to pick a
    profile in the abstract."""
    if not lanes:
        return ("No delegate CLIs detected on PATH yet. Install one (run `doctor` for hints) or "
                "set CLI_BRIDGE_MOCK=1 to explore cli-bridge without any CLI.")
    free = [ln.key for ln in lanes if not ln.is_paid and not ln.is_limited]
    limited = [ln.key for ln in lanes if ln.is_limited]
    paid = [ln.key for ln in lanes if ln.is_paid]

    def _tag(keys: list[str]) -> str:
        if not keys:
            return "—"
        by = {ln.key: ln for ln in lanes}
        return ", ".join(k + ("" if by[k].cost_is_configured else " (default)") for k in keys)

    lines = [
        "**Installed lanes — typical cost (sourced defaults from docs/COSTS.md, NOT detected; "
        "'(default)' means the user hasn't told us their plan yet):**",
        f"- free: {_tag(free)}",
        f"- limited (scarce quota): {_tag(limited)}",
        f"- paid (money/credits): {_tag(paid)}",
        "",
        "**First, ask the user ONE question:** do you pay for these as flat subscriptions "
        "(Pro/Max-style plans), metered API/credits, or a mix? Their answer — not our defaults — "
        "decides each lane's real cost tier. Apply it symmetrically to every installed lane, and "
        "record each answer with `set_lane_cost(lane, cost, note)` so it persists.",
        "",
    ]
    if config.profile_is_set():
        lines.append(f"Profile already set to **{config.profile()}** — you're configured. Adjust "
                     "any lane with CLI_BRIDGE_<LANE>_COST=free|limited|paid.")
        return "\n".join(lines)
    if paid or limited:
        lines.append(
            "**Recommended: `balanced` + a daily cap.** Free lanes handle routine work; a "
            "paid/limited lane is used only when a task earns it, and the cap is a hard safety "
            "net so you never overspend by surprise:\n"
            "    CLI_BRIDGE_PROFILE=balanced\n"
            "    CLI_BRIDGE_DAILY_CREDIT_CAP=5      # est. paid 'credits'/day — tune to you\n"
            "(Set CLI_BRIDGE_<LANE>_CREDITS_PER_1K so the cap can estimate spend.)")
    else:
        lines.append(
            "**Recommended: `balanced`** (or `max`). Everything installed is free — nothing to "
            "overspend, so balanced already uses it all freely:\n"
            "    CLI_BRIDGE_PROFILE=balanced")
    lines += [
        "",
        "Profiles in plain terms: **saver**=free-only fan-out, include_paid refused (direct "
        "calls to a paid lane still work) · **balanced**=free by default, paid joins fan-out "
        "only when the caller passes include_paid · **max**=best by default, paid lanes join "
        "automatically.",
    ]
    return "\n".join(lines)


def _echo_header(lane_key: str, model: str, task: str) -> str:
    """'▶ gemini · gemini-2.5-pro — asked: "…"' line prepended to delegation results, so the
    user re-reading the conversation in their CLI sees who was asked what next to the answer
    (no scrolling back to the tool-call args). CLI_BRIDGE_ECHO_TASK=off disables."""
    if not config.echo_task() or not task:
        return ""
    preview = " ".join(task.split())
    if len(preview) > 140:
        preview = preview[:140] + "…"
    who = f"{lane_key} · {model}" if model else lane_key
    return f'▶ {who} — asked: "{preview}"\n\n'


async def doctor_deep(host: str, lanes: list[LaneSpec], *, is_host, run_lane) -> str:
    """doctor + a tiny live probe of each free, exposed lane to check auth/quota for real."""
    base = doctor(host, is_host=is_host)
    probes = [ln for ln in lanes if not ln.is_paid and not ln.is_limited]
    if not probes:
        return base + "\n\n_(deep probe: no free lanes to test)_"
    async def _probe(ln):
        # terse=False: the probe wants the literal string "OK"; a style preamble would only
        # tempt the model to reformat it. (Also dodges the preamble's per-call overhead here.)
        res = await run_lane(ln, {"task": "Reply with exactly: OK", "timeout_s": 60}, terse=False)
        mark = "✅ responds" if res.ok else f"❌ {res.kind}"
        ver = await _lane_version(ln)
        return f"- **{ln.key}**: {mark}{f' · v: {ver}' if ver else ''}"
    results = await asyncio.gather(*[_probe(ln) for ln in probes])
    flags = await _flag_drift_section(lanes)
    return (base + "\n\n## Deep probe (live auth check + CLI version, free lanes)\n\n"
            + "\n".join(results)
            + "\n\n_Versions help spot drift: if a CLI bumped and a lane breaks, file a `[drift]` issue._"
            + flags)


async def _lane_flag_drift(lane: LaneSpec) -> list[str]:
    """Flags this lane EMITS that are now MISSING from its `--help` (likely renamed/removed
    upstream → the invocation would break). Cheap: one `--help` spawn, no model call / quota.
    [] when there's nothing to check or help can't be read (never a false alarm)."""
    if not lane.help_args or not lane.probe_flags:
        return []
    res = await runner.arun([lane.bin, *lane.help_args], 15)
    if not res.ok:
        return []
    return lanes_mod.missing_flags(res.output, lane.probe_flags)


async def _flag_drift_section(lanes: list[LaneSpec]) -> str:
    """Check EVERY installed lane's flags against its CLI help (incl. limited/paid — it costs no
    quota, just `--help`). Surfaces a broken invocation BEFORE it fails silently at call time."""
    drifts = await asyncio.gather(*[_lane_flag_drift(ln) for ln in lanes])
    bad = [(ln, miss) for ln, miss in zip(lanes, drifts, strict=True) if miss]
    if not bad:
        return "\n\n## Flag check\n\n_All installed lanes' flags still present in their `--help`._"
    rows = [f"- ⚠️ **{ln.key}**: `{', '.join(miss)}` missing from `{ln.bin} "
            f"{' '.join(ln.help_args or [])}` — invocation may be broken (upstream flag change?)."
            for ln, miss in bad]
    return ("\n\n## ⚠️ Flag drift — lane invocation may be broken\n\n" + "\n".join(rows)
            + "\n\n_The CLI changed the flags this lane relies on. Update the lane (or pin an old "
            "CLI via `CLI_BRIDGE_<LANE>_BIN`), or file a `[drift]` issue._")


async def _lane_version(lane: LaneSpec) -> str:
    """Best-effort CLI version (first line of `<bin> --version`) — surfaces upstream drift."""
    if not lane.version_args:
        return ""
    res = await runner.arun([lane.bin, *lane.version_args], 15)
    if not res.ok:
        return ""
    first = (res.output or "").strip().splitlines()
    return first[0][:60] if first else ""


_SINCE_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_since(raw: str) -> float | None:
    """'24h' / '7d' / '90m' / bare seconds -> seconds. Empty/invalid -> None (all-time)."""
    s = (raw or "").strip().lower()
    if not s:
        return None
    m = re.fullmatch(r"(\d+)\s*([smhd])", s)
    if m:
        return int(m.group(1)) * _SINCE_UNITS[m.group(2)]
    try:
        return float(s)
    except ValueError:
        return None


def _render_usage(rep: dict) -> str:
    if not rep.get("enabled"):
        return ("Telemetry is off or unavailable (set CLI_BRIDGE_TELEMETRY=on, or it couldn't "
                "open its local DB). No usage to report.")
    window = f" (last {int(rep['since_s'])}s)" if rep.get("since_s") else ""
    lines = [f"# cli-bridge usage — {rep['total_runs']} total runs{window} (local only)",
             f"_tokens {rep['token_basis']}_", ""]
    lines.append("## By lane")
    for r in rep["by_lane"]:
        cred = f", ~{r['est_credits']} credits" if r.get("est_credits") is not None else ""
        lines.append(f"- **{r['lane']}**: {r['runs']} runs, {r['ok']} ok, ~{r['avg_ms']}ms avg, "
                     f"~{r['est_input_tokens']}+{r['est_output_tokens']} tok{cred}")
    if rep.get("est_total_credits") is not None:
        lines.append(f"\n_Estimated total credits: ~{rep['est_total_credits']}._")
    lines.append("\n## Recent")
    for r in rep["recent"]:
        lines.append(f"- {r['lane'] or r['tool']} [{r['status']}/{r['kind']}] "
                     f"{r['duration_ms']}ms — {r['task']}")
    return "\n".join(lines)


def _render_budget(rep: dict) -> str:
    if not rep.get("enabled"):
        return "Telemetry is off or unavailable. No budget to report."
    if not rep["by_lane"]:
        return "No runs today (since UTC midnight)."
    lines = ["# Today's usage (since UTC midnight) — estimated", ""]
    for r in rep["by_lane"]:
        limit = (f"{r['runs_today']}/{r['daily_limit']}" if r["daily_limit"] is not None
                 else f"{r['runs_today']} (no limit set)")
        cred = f", ~{r['est_credits_today']} credits" if r.get("est_credits_today") is not None else ""
        flag = "  ⚠️ LIMIT REACHED (further spawns blocked today)" if r["over_limit"] else ""
        lines.append(f"- **{r['lane']}**: {limit} runs, ~{r['est_tokens_today']} tok{cred}{flag}")
    lines.append("\n_CLI_BRIDGE_<LANE>_DAILY_LIMIT is enforced at spawn (any lane). "
                 "_CREDITS_PER_1K makes CLI_BRIDGE_DAILY_CREDIT_CAP enforceable — docs/BUDGET.md._")
    return "\n".join(lines)


def _render_job_status(st: dict) -> str:
    lines = [f"Job `{st['id']}` — **{st['status']}** ({st.get('kind', 'ask_all')})"]
    if st.get("preview"):
        lines.append(f"_task: {st['preview']}_")
    if st.get("kind") == "build" and st.get("turn") is not None:
        lines.append(f"turn {st['turn']}/{st.get('max_turns', '?')} · "
                     f"{st.get('files_changed', 0)} files changed in zone `{st.get('zone', '')}` · "
                     f"{st.get('queued_steers', 0)} steer(s) queued")
        if st.get("note"):
            lines.append(f"_{st['note']}_")
    if st.get("error"):
        lines.append(f"error: {st['error']}")
    if st["status"] == jobs.SUCCEEDED:
        lines.append(f"Fetch it with `job_result {st['id']}`.")
    elif st["status"] == jobs.RUNNING:
        if st.get("kind") == "build":
            lines.append(f"Follow with `job_tail {st['id']}`, steer with `build_steer {st['id']}`.")
        else:
            lines.append("Still running — poll again shortly.")
    return "\n".join(lines)


def _render_jobs_list(rows: list[dict]) -> str:
    if not rows:
        return "No async jobs yet. Start one with `ask_all_async`."
    lines = ["# Async jobs", ""]
    for r in rows:
        prev = f" — {r['preview']}" if r.get("preview") else ""
        lines.append(f"- `{r['id']}` **{r['status']}** ({r['kind']}){prev}")
    return "\n".join(lines)


def _render_lane_stats() -> str:
    stats = telemetry.lane_stats()
    if not stats:
        return "No lane stats yet (telemetry off, or no runs recorded)."
    by_key = {ln.key: ln for ln in all_lanes()}
    seat = telemetry.seat_report()
    lines = ["# Lane health", ""]
    for s in stats:
        cd = f", cooldown {s['cooldown_remaining_s']}s" if s["cooldown_remaining_s"] else ""
        lines.append(
            f"- **{s['lane']}**: {s['total_runs']} runs, {s['total_failures']} failed, "
            f"{s['consecutive_failures']} consecutive fail, last={s['last_kind']}{cd}")
        # "Earn their seat" (Lens B, advisory): how a lane votes as a jury verifier over time —
        # shown beside the latency/error stats above (Lens A), never auto-applied to routing.
        sr = seat.get(s["lane"])
        if sr and sr["n_votes"]:
            parts = []
            if sr["accuracy_rate"] is not None:
                parts.append(f"accuracy {sr['accuracy_rate']:.0%} (eval, vs ground truth)")
            if sr["conformity_rate"] is not None:
                parts.append(f"conformity {sr['conformity_rate']:.0%} "
                             "(live — agreement with the verdict, NOT accuracy)")
            if parts:
                lines.append(f"  - ↳ jury seat: {sr['n_votes']} votes · " + "; ".join(parts))
        # Burst rate-limiting pattern (failures interleaved with successes never trip the
        # cooldown): point at the opt-in pacer instead of leaving the lane to die quietly.
        ln = by_key.get(s["lane"])
        if (s["last_kind"] in {"empty", "quota"} and s["total_failures"] >= 5
                and ln is not None and ln.min_interval_s <= 0):
            env_key = s["lane"].upper().replace("-", "_")
            lines.append(f"  - ↳ looks rate-limited under bursts — consider spawn pacing: "
                         f"`CLI_BRIDGE_{env_key}_MIN_INTERVAL_S=2`")
    return "\n".join(lines)


def doctor(host: str, *, is_host) -> str:
    lines = ["# cli-bridge - health check", ""]
    host_note = ("its own lane is hidden (CLI_BRIDGE_HIDE_HOST)" if config.hide_host()
                 else "its own lane is shown (direct calls only, never in fan-out)")
    lines.append(f"Host (caller): **{host or 'unknown'}** - {host_note}.")
    if config.profile_is_set():
        prof = config.profile()
    elif config.cost_config_is_set():
        prof = config.profile() + " (default profile; per-lane costs set)"
    else:
        prof = config.profile() + " (default — run `setup` to configure)"
    lines.append(f"Cost profile: **{prof}**")
    cap = config.daily_credit_cap()
    if cap > 0:
        unrated = [ln.key for ln in lanes_mod.all_lanes()
                   if ln.is_paid and config.lane_env_float(ln.key, "CREDITS_PER_1K") is None]
        if unrated:
            lines.append(f"⚠️ _CLI_BRIDGE_DAILY_CREDIT_CAP={cap:g} is set but UNENFORCEABLE for "
                         f"paid lane(s) {', '.join(unrated)} — their spend always estimates to 0. "
                         "Set CLI_BRIDGE_<LANE>_CREDITS_PER_1K (suggestions in docs/COSTS.md)._")
    lines.append("_Cost tiers are NOT detected from your account — '(default)' = a sourced "
                 "typical-plan default (docs/COSTS.md); '(set by you)' = your own setting._")
    if lanes_mod.cost_facts_stale():
        lines.append(f"⚠️ _Cost facts last verified {lanes_mod.COST_FACTS_VERIFIED} "
                     f"({lanes_mod.cost_facts_age_days()} days ago) — plans/quotas churn fast; "
                     "re-check docs/COSTS.md against the vendor pages before trusting defaults._")
    lines.append("")
    for lane in all_lanes():
        installed = is_installed(lane)
        mark = "installed" if installed else "NOT on PATH"
        if not lane.enabled:
            mark += " (disabled by env)"
        hidden = ((" - hidden (this is the host)" if config.hide_host()
                   else " - this is the host (shown; never in fan-out)")
                  if is_host(lane, host) else "")
        cost_env_key = f"CLI_BRIDGE_{lane.key.upper()}_COST"
        if not lane.cost_is_configured:
            src = "default — yours may differ"
        elif cost_env_key in config.ENV_PRESET_KEYS:
            src = "set by you: host env — wins over the config file"
        else:
            src = "set by you: config file"
        paid = f" - {lane.cost_label} ({src})"
        exp = " - experimental" if lane.experimental else ""
        model = lane.model_for("")
        default = f" - default model: {model}" if model else ""
        lines.append(f"- **{lane.key}** ({lane.bin}) - {mark}{paid}{exp}{hidden}{default}")
        if installed and lane.sunset:
            from datetime import date
            try:
                left = (date.fromisoformat(lane.sunset) - date.today()).days
            except ValueError:
                left = None
            if lane.sunset_passed():
                alts = " / ".join(lane.bin_alts) or "none"
                lines.append(f"  - ⚠️ _free tier SUNSET {lane.sunset}: a 'free' default now "
                             f"degrades to 'limited' and the spawn prefers `{alts}` over "
                             f"`{lane.bin_default}`. Set CLI_BRIDGE_{lane.key.upper()}_COST "
                             "to override._")
                if lane.cost_is_configured and lane.cost_label == "free":
                    lines.append(f"  - ⚠️ _your CLI_BRIDGE_{lane.key.upper()}_COST=free may "
                                 "predate this sunset — re-check that the free tier still "
                                 "exists on your plan._")
            elif left is not None and left <= 14:
                lines.append(f"  - ⚠️ _free tier sunsets {lane.sunset} (in {left} day"
                             f"{'s' if left != 1 else ''}) — after that the lane degrades to "
                             "'limited' and prefers its successor binary automatically._")
        if not installed and lane.install_hint:
            lines.append(f"  - _install: {lane.install_hint}_")
        if installed and lane.cost_note_effective:
            lines.append(f"  - _{lane.cost_note_effective}_")
        daily_limit = config.lane_env_int(lane.key, "DAILY_LIMIT")
        if installed and daily_limit is not None:
            lines.append(f"  - _daily run limit: {telemetry.lane_runs_today(lane.key)}/"
                         f"{daily_limit} today (UTC; enforced at spawn)_")
        if not lane.is_paid and lanes_mod.is_paid_opencode_model(model):
            lines.append(f"  - ⚠️ **cost mismatch**: lane is '{lane.cost_label}' but its model "
                         f"`{model}` spends money/credits — set `CLI_BRIDGE_"
                         f"{lane.key.upper()}_COST=paid` or pick an `opencode/*-free` model.")
    rstat = preamble.roles_file_status()
    if rstat["path"]:
        if rstat["error"]:
            lines.append(f"\n⚠️ **Roles file NOT loaded** ({rstat['path']}): {rstat['error']} — "
                         "running with built-in roles only.")
        else:
            note = f"\nRoles file: {len(rstat['roles'])} custom role(s) loaded from {rstat['path']}"
            if rstat["overrides"]:
                note += f" (overriding built-in: {', '.join(sorted(rstat['overrides']))})"
            if rstat["dropped"]:
                note += f" — ⚠️ dropped non-string entr{'ies' if len(rstat['dropped']) != 1 else 'y'}: " \
                        f"{', '.join(rstat['dropped'])}"
            lines.append(note + ".")
    risky = lanes_mod.LANES_LOAD_STATUS.get("argv_secret_risk") or []
    if risky:
        lines.append(f"\n⚠️ **Secret in argv** — custom lane(s) {', '.join(risky)} expand a "
                     "${ENV} key into the command line, visible in `ps` while the call runs. "
                     "Safe pattern (curl ≥ 8.3): `--variable %MY_KEY` + `--expand-header "
                     "\"Authorization: Bearer {{MY_KEY}}\"` keeps the secret out of argv — "
                     "see examples/free-apis.json.")
    lines.append("\nPer-lane config (your plan): CLI_BRIDGE_<LANE>_COST=free|limited|paid, "
                 "_ENABLED=false, _BIN=<path>, _MODEL=<id>, _DAILY_LIMIT=<runs/day> "
                 "(enforced at spawn — the simplest cap, works for every lane).")
    lines.append("Add your own CLI via a JSON file in CLI_BRIDGE_LANES_FILE - no code changes.")
    return "\n".join(lines)
