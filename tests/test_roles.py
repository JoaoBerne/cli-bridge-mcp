"""Role personas: curated built-ins + user-extensible CLI_BRIDGE_ROLES_FILE."""

import json

from cli_bridge import preamble


def test_builtin_role_prepends_persona():
    out = preamble.with_role("reviewer", "check this diff")
    assert out.startswith("[role] Act as a rigorous code reviewer")
    assert out.endswith("check this diff")


def test_unknown_or_empty_role_is_noop():
    assert preamble.with_role("nonexistent", "t") == "t"
    assert preamble.with_role("", "t") == "t"


def test_curated_set_stays_small_and_distinct():
    # Anti-bloat guard: a 32-persona catalog is prompt theater. If this grows past ~8,
    # someone must argue the new role catches a failure mode no existing one does.
    assert len(preamble.ROLES) <= 8
    assert len(set(preamble.ROLES.values())) == len(preamble.ROLES)


def test_roles_file_adds_custom_role(tmp_path, monkeypatch):
    f = tmp_path / "roles.json"
    f.write_text(json.dumps({"dba": "Act as a database engineer."}))
    monkeypatch.setenv("CLI_BRIDGE_ROLES_FILE", str(f))
    assert "dba" in preamble.roles()
    assert preamble.with_role("DBA", "t").startswith("[role] Act as a database engineer.")


def test_roles_file_overrides_builtin_without_forking(tmp_path, monkeypatch):
    f = tmp_path / "roles.json"
    f.write_text(json.dumps({"reviewer": "Our team's house reviewer rules."}))
    monkeypatch.setenv("CLI_BRIDGE_ROLES_FILE", str(f))
    assert preamble.roles()["reviewer"] == "Our team's house reviewer rules."
    assert preamble.ROLES["reviewer"].startswith("Act as a rigorous")   # built-in untouched


def test_roles_file_ignores_garbage(tmp_path, monkeypatch):
    f = tmp_path / "roles.json"
    f.write_text(json.dumps({"ok": "fine", "bad": 7, "": "no name", "blank": "  "}))
    monkeypatch.setenv("CLI_BRIDGE_ROLES_FILE", str(f))
    custom = {k: v for k, v in preamble.roles().items() if k not in preamble.ROLES}
    assert custom == {"ok": "fine"}


def test_roles_file_missing_or_malformed_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_BRIDGE_ROLES_FILE", str(tmp_path / "absent.json"))
    assert preamble.roles() == preamble.ROLES
    f = tmp_path / "broken.json"
    f.write_text("not json {")
    monkeypatch.setenv("CLI_BRIDGE_ROLES_FILE", str(f))
    assert preamble.roles() == preamble.ROLES
    f.write_text(json.dumps(["a", "list"]))
    assert preamble.roles() == preamble.ROLES


def test_inline_persona_is_dynamic_role_assignment():
    out = preamble.with_role("Act as a kernel locking expert; hunt deadlocks.", "review this")
    assert out.startswith("[role] Act as a kernel locking expert; hunt deadlocks.")
    assert out.endswith("review this")


def test_unknown_single_word_stays_noop():
    # A typo'd registry name must never silently become the persona text.
    assert preamble.with_role("reviewr", "t") == "t"


def test_roles_file_status_reports_errors_and_overrides(tmp_path, monkeypatch):
    f = tmp_path / "roles.json"
    f.write_text("not json {")
    monkeypatch.setenv("CLI_BRIDGE_ROLES_FILE", str(f))
    st = preamble.roles_file_status()
    assert st["error"] and st["roles"] == {}
    f.write_text(json.dumps({"reviewer": "house rules", "bad": 3}))
    st = preamble.roles_file_status()
    assert st["error"] == ""
    assert st["overrides"] == ["reviewer"] and st["dropped"] == ["bad"]


def test_doctor_surfaces_broken_roles_file(tmp_path, monkeypatch):
    from cli_bridge import server
    f = tmp_path / "roles.json"
    f.write_text("{broken")
    monkeypatch.setenv("CLI_BRIDGE_ROLES_FILE", str(f))
    out = server._doctor("")
    assert "Roles file NOT loaded" in out


def test_run_records_role_column(tmp_path, monkeypatch):
    from cli_bridge import telemetry
    monkeypatch.setenv("CLI_BRIDGE_STATE_DB", str(tmp_path / "state.sqlite"))
    monkeypatch.setenv("CLI_BRIDGE_TELEMETRY", "on")
    telemetry._reset_for_tests()
    try:
        rec = telemetry.start("ask", "fakelane", "m", "t", role="security")
        telemetry.record(rec, True, "ok", output_chars=1)
        conn = telemetry._connect()
        row = conn.execute("SELECT role FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        assert row[0] == "security"
    finally:
        telemetry._reset_for_tests()


def test_example_roles_file_is_valid():
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "examples" / "roles.example.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data and all(isinstance(k, str) and isinstance(v, str) for k, v in data.items())
