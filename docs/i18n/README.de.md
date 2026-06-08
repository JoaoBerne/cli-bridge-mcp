<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../assets/banner-dark.svg">
  <img src="../../assets/banner-light.svg" width="860" alt="Du → cli-bridge → ein Rat aus KI-CLIs parallel → ein zusammengeführtes Review">
</picture>

[English](../../README.md) · [Français](README.fr.md) · [简体中文](README.zh-CN.md) · [Español](README.es.md) · [Português (BR)](README.pt-BR.md) · [日本語](README.ja.md) · **Deutsch**

</div>

_Die englische README ist die maßgebliche Fassung; diese Übersetzung kann ihr hinterherhinken._

# cli-bridge

![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/cli-bridge-mcp)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**Dein KI-Assistent – der jederzeit einen Kollegen anrufen kann.**

`cli-bridge` ist ein [Model Context Protocol](https://modelcontextprotocol.io)-Server, der
**die KI-CLIs orchestriert, die du bereits installiert und in denen du dich angemeldet hast** – Claude Code, Codex,
Gemini CLI, opencode, … – von welchem Assistenten aus auch immer du gerade sprichst. Keine API-Schlüssel, keine
Token-Extraktion, ein rein lokales Log, ein hartes Kostenlimit, und Schreibzugriffe erfolgen nur als Diffs in einem
Wegwerf-Worktree. Das ist unstrittige Klempnerarbeit; und hier ist, was sie ermöglicht:

Festgefahren bei einem üblen Bug? Lass deinen Assistenten GPT *und* Gemini parallel fragen und beide vergleichen. Brauchst du
eine 1M-Token-Lesung einer riesigen Datei? Reich sie an Gemini weiter. Willst du eine günstige Zweitmeinung? Schick sie an ein
kostenloses Modell. Eine Frage, jedes Modell, nebeneinander – ohne dein Terminal zu verlassen.

```
You → Claude:  "ask the council whether this auth logic is safe"
Claude → cli-bridge → [ Gemini ] [ GPT ] [ Mistral ] [ Qwen ] … in parallel
            ← three independent reviews + a synthesis of where they agree & disagree
```

<div align="center">

<img src="../../assets/demo.gif" width="860" alt="cli-bridge security-review-Demo: ein commiteter Auth-Bypass wird von zwei Modellen unabhängig erkannt, zu einem nach Schweregrad sortierten Bericht zusammengeführt, 0 $ auf kostenlosen Lanes">

_Echter Lauf (2,5-fache Geschwindigkeit): ein commiteter Auth-Bypass – `security-review` verteilt OWASP-Rollen parallel über
kostenlose Modelle; zwei Modelle stufen ihn unabhängig voneinander als **Blocker** ein, und `usage` liefert den Beleg._
_Erzeugt mit [vhs](https://github.com/charmbracelet/vhs) – [Quelle ansehen](../demo/)._

</div>

> **Warum es in einem Atemzug anders ist:** Es hält niemals einen API-Schlüssel und extrahiert niemals ein Token – es
> steuert die offiziellen CLIs, die du **bereits installiert hast und in denen du angemeldet bist**. Ein Rat aus kostenlosen Lanes kostet
> **0,00 $** (den Beleg liefert `usage_report`); bezahlte Lanes laufen ausschließlich innerhalb eines harten Tageslimits,
> das *du* festlegst. Und wenn du es bittest, tatsächlich Arbeit zu *erledigen*, bearbeitet es alles in einem Wegwerf-Git-Worktree und gibt dir
> einen **Diff** zurück – dein laufendes Repository wird nie angetastet.

> **Und der ehrliche Teil:** „Mehr Modelle = besser“ ist *fragil* – große Modelle teilen sich Trainingsdaten,
> daher korrelieren ihre Fehler. Wir haben unsere eigene Kernbehauptung gemessen (`cli-bridge eval`, ausgeliefert, ohne LLM-
> Judge): Ein vielfältiger Rat hat **nicht** mehr Bugs gefunden als ein einzelnes starkes Modell – er hat die Fehlalarme
> um etwa **das Doppelte** reduziert. Wir veröffentlichen die Zahlen so oder so ([BENCHMARKS.md](../BENCHMARKS.md)), und das
> Harness wird mitgeliefert, damit du es mit *deinen* CLIs laufen lassen kannst.

---

## Warum gerade dieses

Es gibt andere „andere Modelle aufrufen“-MCPs. Hier ist, was cli-bridge unterscheidet:

- 🛡️ **Ban-sicher von Grund auf.** Es startet die **offizielle CLI** jedes Modells – genau so, wie du sie von
  Hand ausführen würdest. Keine Extraktion von OAuth-Token, keine Wiederverwendung von API-Schlüsseln, nichts, was Konten markiert. Jede CLI
  kümmert sich um ihre eigene Authentifizierung und Abrechnung.
- 💸 **Belegte Kosten-Voreinstellungen, dann stimmst *du* sie auf deinen Plan ab.** Out of the box baut `ask_all` einen
  kostenlosen Rat und greift weder auf Abo-Kontingente (Claude, GPT) noch auf bezahlte Credits zu, sofern du nicht darum bittest.
  Jede Lane bringt eine Stufe mit, die aus den veröffentlichten Plänen des Anbieters belegt ist
  ([docs/COSTS.md](../COSTS.md), datiert) – **niemals aus deinem Konto erkannt, und entsprechend gekennzeichnet** –,
  die du gemäß deinen eigenen Abonnements überschreibst
  (`CLI_BRIDGE_<LANE>_COST=free|limited|paid`); bei einem großen Plan markierst du sie alle als `free` oder setzt
  `CLI_BRIDGE_PROFILE=max`.
- 🔌 **Funktioniert von jedem Host aus.** Steuerst du Claude Code? Dann blendet es die Claude-Lane aus (du fragst dich nicht selbst)
  und stellt den Rest bereit. Steuerst du stattdessen Codex oder opencode? Dasselbe, automatisch erkannt aus
  dem MCP-Handshake.
- 🧩 **Füge jede CLI hinzu – oder deine eigene API – ohne zu forken.** Eingebaute Lanes für Claude, GPT, Gemini,
  Mistral, Qwen, Copilot, Grok und opencode. Registriere **deine eigene CLI aus einer JSON-Datei** oder kapsele
  **deine eigene API**, indem du `curl` startest. Null Code.
- 🧠 **Rats-Synthese.** `ask_all` kann ein kostenloses Modell zusammenfassen lassen, wo die anderen *übereinstimmen* und
  *abweichen* – mach aus drei Meinungen eine Entscheidung.
- 🔬 **Multi-Modell-Workflows.** `review_diff` und `security_review` verteilen **rollen­vielfältige** Reviewer
  über den Rat und führen sie dann zu einem nach Schweregrad sortierten Bericht zusammen (Merge + Dedupe). `debate` lässt Modelle
  einander über eine begrenzte Anzahl von Runden kritisieren und überarbeiten, bevor ein Judge das Fazit zieht.
- ✍️ **Standardmäßig nur lesend, Schreibzugriffe auf Anfrage.** Aktiviere `agent: build`, damit eine fähige Lane
  tatsächlich **Dateien bearbeitet** – oder wähle pro Aufruf ein bestimmtes `model`, einschließlich eines **Geschwistermodells deiner eigenen
  Familie** (frage Opus 4.6 aus Claude Code 4.8 heraus).
- 🪶 **Rückgaben im Subagent-Stil.** Ein Delegierter arbeitet in seinem eigenen Kontext und gibt eine Zusammenfassung zurück; riesige
  Ausgaben werden in eine Datei ausgelagert und es kommt nur eine Vorschau zurück, sodass der Kontext deines Assistenten schlank bleibt.
- 🔁 **Automatischer Fallback.** `ask_cascade` probiert Lanes von günstig nach stark und geht weiter, sobald
  eine an Kontingent/Auth/Timeout scheitert – so degradiert eine tote Lane anmutig, statt dich im Stich zu lassen.
- 🩺 **Selbstbewusst.** Lokale Telemetrie verfolgt den Zustand jeder Lane und versetzt eine Lane in den Cooldown,
  nachdem sie wiederholt an Kontingent/Auth/Timeout gescheitert ist, sodass `ask_all`/`ask_cascade` um sie herumleiten.
- 🎯 **Lernt deinen Stack.** Bewerte die Antwort einer Lane mit 1–5 über `rate_lane`, und `ask_best` bevorzugt die
  Modelle, die jeden Aufgabentyp **auf deiner Maschine** tatsächlich gewinnen – ein lokales Qualitätssignal, gespeichert in
  sqlite, das `/compact` und Neustarts übersteht. Keine öffentliche Bestenliste; *deine* Ergebnisse.
- 🧱 **Gehärtet.** Timeouts beenden den gesamten Prozessbaum (keine Waisen, die Kontingent verbrennen), Host-
  Abbruch beendet den Delegierten, Geheimnisse werden redigiert, Fehler werden klassifiziert
  (`quota` / `auth` / `timeout`), sodass dein Assistent weiß, was als Nächstes zu tun ist. Läuft unter
  macOS / Linux / Windows.
- 📐 **Gemessen, nicht behauptet.** „Mehr Modelle finden mehr Bugs“ ist *falsifizierbar*, also liefert cli-bridge
  den Test mit: `cli-bridge eval` lässt einen Rat gegen ein einzelnes starkes Modell + Selbstkonsistenz
  bei **gleichem Aufruf-Budget** auf einem Korpus eingestreuter Reasoning-Bugs antreten, deterministisch bewertet (kein LLM-
  Judge). Es berichtet Mittelwert ± Standardabweichung mit einer „kein messbarer Unterschied“-Schutzvorrichtung und einer Pro-Bug-Sieg/Niederlage-
  Tabelle – und veröffentlicht das Ergebnis selbst dann, wenn der Rat verliert. Siehe
  [BENCHMARKS.md § Qualität](../BENCHMARKS.md#quality--does-a-council-actually-beat-one-strong-model).

### vs. andere Multi-Modell-MCPs

| | cli-bridge | API-Schlüssel-Gateways | Token-Reuse-Bridges |
|---|:---:|:---:|:---:|
| Ban-sicher (startet offizielle CLI) | ✅ | ➖ (deine Schlüssel) | ❌ (ToS-Risiko) |
| Keine API-Schlüssel zu verwalten | ✅ | ❌ | ✅ |
| Nutzt deine bestehenden Abonnements (0,00 $ kostenloser Rat) | ✅ | ❌ | ✅ |
| Kostenstufen pro Plan + hartes Tageslimit + Cooldown | ✅ | ➖ | ❌ |
| Automatischer Fallback (Cascade) | ✅ | teilweise | ❌ |
| Routing, das **aus deinen Ergebnissen lernt** | ✅ | ❌ | ❌ |
| Jede CLI / eigene API hinzufügen, ohne zu forken | ✅ | ➖ | ❌ |
| Blendet den aufrufenden Host selbst aus | ✅ | n. z. | ➖ |
| Round-Table-Gedächtnis, das einen Neustart übersteht | ✅ | ➖ (im Arbeitsspeicher) | ➖ |
| Sicheres agentisches Schreiben (Worktree → Diff) | ✅ | ➖ | ❌ |
| Liefert eine deterministische Qualitäts-Eval (Rat vs. einzeln) | ✅ | ❌ | ❌ |

---

## Schnellstart

### 1. Installieren

```bash
# zero-install run (recommended)
uvx cli-bridge-mcp

# or install it
uv tool install cli-bridge-mcp     # or: pipx install cli-bridge-mcp
```

Du erhältst nur dann eine Lane für eine CLI, wenn du sie **bereits installiert hast und angemeldet bist**. cli-bridge erkennt
automatisch, was in deinem `PATH` liegt. Führe jederzeit das Werkzeug `doctor` aus, um zu sehen, was verdrahtet ist (`doctor deep`
prüft sogar jede Anmeldung live).

| Lane | CLI | Kosten (typisch) |
|------|-----|------|
| `ask_claude`   | [Claude Code](https://docs.claude.com/claude-code) | Abonnement |
| `ask_gpt`      | [OpenAI Codex](https://github.com/openai/codex) | Abonnement |
| `ask_gemini`   | Gemini CLI (oder `agy` / Antigravity) | kostenlos / Abonnement |
| `ask_mistral`  | Mistral Vibe | kostenlose Stufe |
| `ask_qwen` ⚗️  | Qwen Code | API-Schlüssel mit Verbrauchsabrechnung (kostenlose OAuth-Stufe im Apr. 2026 geschlossen) |
| `ask_copilot` ⚗️ | GitHub Copilot CLI | Abonnement (nutzungsbasierte Credits seit 2026-06) |
| `ask_grok` ⚗️  | xAI Grok CLI | Abonnement (SuperGrok / X Premium+) |
| `ask_opencode` | [opencode](https://opencode.ai)-Gateway (deepseek, qwen, glm, kimi…) | standardmäßig kostenlos; einige Modelle nutzen Credits |

⚗️ = experimentell (Flags noch nicht live verifiziert – bitte Fehler melden).
Kostenspalte = der *typische veröffentlichte Plan* des Anbieters mit Stand Juni 2026 ([docs/COSTS.md](../COSTS.md)
enthält Limits, Abschaltungen und Quellen) – cli-bridge erkennt niemals, was eine Lane *dich* kostet; deklariere deinen
eigenen Plan mit `CLI_BRIDGE_<LANE>_COST`.

### Der 0-$-Rat (gar keine Abonnements)

Kein bezahlter Plan, keine Karte? Du kannst trotzdem in etwa 5 Minuten einen echten Multi-Modell-Rat aus
Anbietern zusammenstellen, die eine **wirklich kostenlose Stufe mit hartem Stopp** bieten (Erschöpfung = HTTP 429, eine Rechnung ist
strukturell unmöglich – verifiziert im Juni 2026, Quellen in [docs/COSTS.md](../COSTS.md)):

```bash
# 1. Get free API keys (no card): console.groq.com · cloud.cerebras.ai ·
#    a GitHub PAT (models scope) · openrouter.ai/keys
export GROQ_API_KEY=... CEREBRAS_API_KEY=... GITHUB_MODELS_TOKEN=... OPENROUTER_API_KEY=...
# 2. Point cli-bridge at the ready-made lanes
export CLI_BRIDGE_LANES_FILE=/path/to/examples/free-apis.json
```

Das sind **Groq** (llama-3.3-70b, 1k Anfragen/Tag) + **Cerebras** (gpt-oss-120b) + **GitHub Models**
(jedes GitHub-Konto hat kostenlosen Zugang) + die Breite von **OpenRouter `:free`** – vier unabhängige
Stimmen für `ask_all`/`consensus`/`debate`, plus die eingebauten kostenlosen Modelle von opencode, falls installiert.
Vorbehalte: Die kostenlose Stufe der Gemini CLI **wird am 2026-06-18 abgeschaltet**; kostenlose Stufen wechseln im Wochentakt – prüfe
[docs/COSTS.md](../COSTS.md) für das, was zum Verifizierungszeitpunkt galt.

### 2. Beim Host registrieren

Es ist ein schlichter stdio-MCP-Server (`uvx cli-bridge-mcp`) – er funktioniert in jedem MCP-Client und
blendet automatisch die Lane des jeweils aufrufenden Hosts aus (du fragst dich nicht selbst).

**Claude Code** – ein Befehl:

```bash
claude mcp add cli-bridge -- uvx cli-bridge-mcp
```

[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_cli--bridge-0098FF?logo=githubcopilot&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=cli-bridge&config=%7B%22name%22%3A%22cli-bridge%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22cli-bridge-mcp%22%5D%7D)
[![Install in Cursor](https://img.shields.io/badge/Cursor-Install_cli--bridge-111111?logo=cursor&logoColor=white)](https://cursor.com/en/install-mcp?name=cli-bridge&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJjbGktYnJpZGdlLW1jcCJdfQ==)

<details>
<summary><b>Claude Desktop</b> (<code>claude_desktop_config.json</code>)</summary>

```json
{ "mcpServers": { "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } } }
```
</details>

<details>
<summary><b>Codex</b> (<code>~/.codex/config.toml</code>)</summary>

```toml
[mcp_servers.cli-bridge]
command = "uvx"
args = ["cli-bridge-mcp"]
```
</details>

<details>
<summary><b>Cursor</b> (<code>~/.cursor/mcp.json</code>)</summary>

```json
{ "mcpServers": { "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } } }
```
</details>

<details>
<summary><b>VS Code</b> (<code>.vscode/mcp.json</code> oder Benutzereinstellungen)</summary>

```json
{ "servers": { "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } } }
```
</details>

<details>
<summary><b>Gemini CLI</b> (<code>~/.gemini/settings.json</code>)</summary>

```json
{ "mcpServers": { "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } } }
```
</details>

<details>
<summary><b>opencode</b> (<code>opencode.json</code>)</summary>

```json
{ "mcp": { "cli-bridge": { "type": "local", "command": ["uvx", "cli-bridge-mcp"] } } }
```
</details>

<details>
<summary><b>Windsurf</b> (<code>~/.codeium/windsurf/mcp_config.json</code>)</summary>

```json
{ "mcpServers": { "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } } }
```
</details>

<details>
<summary><b>Warp</b> (Einstellungen → AI → MCP servers)</summary>

```json
{ "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } }
```
</details>

### 3. Verwenden

Sprich einfach mit deinem Assistenten:

> *„Ask Gemini for a second opinion on this function.“*
> *„Have the whole council review my diff and synthesize where they disagree.“* (→ `review_diff`)
> *„Get GPT to think hard about this race condition.“* (→ `effort: high`)
> *„Run a security review on my staged changes.“* (→ `security_review`)
> *„Make the models debate whether we need this abstraction.“* (→ `debate`)
> *„Ask gpt to implement this function.“* (→ `agent: build`, bearbeitet Dateien)
> *„Ask Opus 4.6 to double-check my reasoning.“* (Geschwistermodell, aus Claude Code)
> *„Pick the best lane for a deep review — and remember that one nailed it.“* (→ `ask_best` + `rate_lane`; beim nächsten Mal leitet es zuerst dorthin)

Hosts, die MCP-Prompts unterstützen, stellen außerdem `review_diff`, `security_review`, `debate`,
`premortem`, `test_plan`, `apilookup` und `cost_setup` als native Slash-Befehle bereit.

---

## Werkzeuge

| Werkzeug | Was es tut |
|------|--------------|
| `ask_<lane>` | Ein Modell fragen. Parameter: `task`, optional `model`, `effort`, `agent`, `cwd`, `timeout_s`, **`conversation`** (einen Round-Table-Thread starten/fortsetzen – siehe unten). |
| `ask_all` | Dieselbe Frage parallel an jede kostenlose, nicht limitierte Lane verteilen. `synthesize: true` ergänzt eine Übereinstimmungs-/Abweichungs-Zusammenfassung. `include_paid: true`, um auch limitierte/bezahlte Lanes abzufragen. |
| `ask_cascade` | Ein Modell **mit automatischem Fallback** fragen – probiert Lanes von günstig nach stark, überspringt im Cooldown befindliche, geht bei Kontingent/Auth/Timeout weiter. Gibt den ersten Erfolg zurück + eine Spur dessen, was probiert wurde (Kostenstufe, Latenz, Grund für Überspringen). |
| `ask_best` | **Eine Lane nach Modus auswählen** (`fast`/`cheap`/`deep`/`code`/`review`/`security`) auf Basis von Kosten, Zustand, gemessener Latenz **und deinen eigenen `rate_lane`-Bewertungen**, und sie dann mit Fallback ausführen. Für „nimm einfach das richtige Modell“ – `ask_all` vergleicht, `ask_cascade` ist schlicht günstigstes zuerst. |
| `rate_lane` | **Bring dem Router etwas bei.** Bewerte die Antwort einer Lane mit 1–5 für einen Aufgabentyp (`mode`) → `ask_best` bevorzugt dann die Lanes, die diesen Modus **auf deiner Maschine** gewinnen. In sqlite gespeichert (übersteht `/compact`/Neustart); eine Untergrenze von zwei Bewertungen, bevor eine Lane lenkt, damit das Feedback ehrlich und nicht verrauscht ist. Jede `ask_best`-Antwort gibt den exakten Aufruf aus. |
| `route_plan` | Zeigt die Reihenfolge an, in der `ask_cascade` es versuchen würde, gegeben dein Profil + aktuelle Cooldowns (nur lesend, führt nichts aus). Übergib `mode`, um `ask_best` vorzuschauen – einschließlich der laufenden Bewertung jeder Lane. |
| `ask_all_async` / `job_status` / `job_result` / `job_cancel` / `jobs_list` | Eine Verteilung als **Hintergrund-Job** ausführen, der in unter 1 s eine Job-ID zurückgibt, damit ein langsamer Ratslauf nicht die Tool-Call-Deadline des Hosts reißen kann. Cancel beendet die Prozessgruppen der Delegierten. |
| `review_diff` | Multi-Modell-Code-Review eines Git-Diffs: Lanes reviewen parallel mit **unterschiedlichen Schwerpunkten** (Korrektheit / Sicherheit / Tests / Wartbarkeit) und geben je JSON-Befunde zurück; deterministische Vorprüfungen (Geheimnisse, gefährliche Shell) speisen sie an; Befunde **werden nach Datei/Zeile/Titel zusammengeführt** mit übereinstimmungsbasierter Konfidenz (single/majority/consensus). `output_format: markdown` (Standard) oder `json`. Parameter: `cwd`, `base` (Standard HEAD), `diff`, `include_paid`, `timeout_s`. |
| `security_review` | OWASP-bewusstes, **rein sicherheitsbezogenes** Review eines Git-Diffs (Injection / Auth & Zugriffskontrolle / Geheimnisse & Krypto / Datenleck & SSRF) → nach Schweregrad sortierte Befunde + ein `residual_risk`-Abschnitt. |
| `debate` | Mehrere Modelle beantworten eine Frage, **sehen die Antworten der anderen und überarbeiten sie** über eine begrenzte Anzahl von Runden (Standard 1, max. 3), dann schreibt ein **unabhängiger Judge** (bei 3+ Lanes aus der Debatte herausgehalten) den endgültigen Konsens + verbleibende Uneinigkeit. Aus dem Produktiveinsatz gehärtet: `context_files` injiziert Schlüsseldateien in jeden Debattier-Prompt (**Erdung** – ohne sie paraphrasiert der Rat nur dein Briefing), ein **Faktencheck-Durchlauf** (kostenlose Lane, standardmäßig an) markiert nicht verifizierbare Befehle/Tags/Versionen im Urteil, Behauptungen tragen Provenienz-Tags (`[brief]`/`[own-knowledge]`/`[verified]`), ein dünnes Briefing erhält eine Linter-Warnung, und `steelman: true` lässt eine Lane *gegen* ein einstimmiges Urteil argumentieren, bevor der Judge erneut schließt. `summary_only` lässt die vollständigen Positionen weg (ca. 60–80 % weniger Tokens); `dry_run` gibt ein Preflight-Datenmanifest zurück (welche Dateien/Zeichen an welche Anbieter gehen), bevor irgendetwas gesendet wird. Parameter: `task`, `rounds`, `adversarial`, `context_files`, `fact_check`, `summary_only`, `allow_self_judge`, `steelman`, `dry_run`, `include_paid`, `cwd`, `timeout_s`. |
| `consensus` | Der „LLM-Rat“ besser gemacht: jede Lane antwortet blind, dann **rangiert sie die anonymisierten Antworten** (keine Selbstbevorzugung), die Stimmen werden **deterministisch** aggregiert (Borda-Zählung), und die **von den Kollegen auf Platz 1 gewählte Antwort wird wortwörtlich zurückgegeben** – denn das *Auswählen* der besten Antwort schlägt das *Vermischen* (arXiv 2603.20324: Synthese in 0/42 Aufgaben bevorzugt; Auswahl gewinnt, Glass's Δ≈2.07). `synthesize: true` aktiviert eine Vorsitzenden-Mischung (der schwächere Modus). Gibt die endgültige Antwort + eine Tabelle der Peer-Abstimmung zurück. `dry_run` gibt ein Preflight-Datenmanifest zurück (welche Dateien/Zeichen an welche Anbieter gehen), ohne zu spawnen. Unterstützt `context_files`-Erdung und `summary_only`. Parameter: `task`, `context_files`, `synthesize`, `summary_only`, `dry_run`, `include_paid`, `cwd`, `timeout_s`. |
| `challenge` | Übergibt eine Behauptung an **eine externe Lane** mit einem Prompt zur kritischen Neubewertung → ein unabhängiges skeptisches Review (mit einer Integritäts-Schutzleiste – es fabriziert keine Uneinigkeit). Stelle deine eigene Schlussfolgerung auf die Probe, bevor du handelst. Optional `lane`. |
| `premortem` | Jede Lane stellt sich vor, der Plan sei **bereits gescheitert**, und listet wahrscheinliche Fehlermodi + Gegenmaßnahmen auf; zu einer priorisierten Risikoliste zusammengeführt. Führe es vor dem Bauen aus. |
| `test_plan` | Leitet aus einem Git-Diff oder einer Beschreibung einen priorisierten **Testplan** ab (Verhaltensweisen, Randfälle, konkrete Fälle). |
| `commit_msg` | Erzeugt eine **Conventional-Commit**-Nachricht aus deinem gestagten Diff (fällt auf den Working Tree zurück). Nur lesend – gibt Text aus, committet nie. Optional `lane`, `cwd`. |
| `pr_describe` | Erzeugt einen **PR-Titel + Beschreibung** (Summary / Changes / Testing) aus dem Diff des Branches + Commit-Log gegen eine Basis (Standard origin/main → main). Nur lesend. Optional `base`, `lane`, `cwd`. |
| `ask_build` | **Einen echten Build beauftragen.** `mode=isolated` (Standard) bearbeitet einen Wegwerf-Worktree und liefert einen **Diff** – Repo unberührt. `mode=direct` baut direkt in ein Zielverzeichnis, abgesichert durch git + einen **Zonen-Vertrag** (der Delegat schreibt nur in `zone`; Schreibvorgänge außerhalb werden erkannt und zurückgerollt; das Rückgängigmachen ist zonen-begrenzt, nie ein globaler Reset) – so kann der Host andere Teile **desselben Repos parallel** bauen. `async=true` macht ihn **steuerbar**. `dry_run` zeigt das Brief vorab. (`ask_build_isolated` ist ein Legacy-Alias.) |
| `job_tail` / `build_steer` | **Einen Build wie ein Mensch verfolgen und steuern.** `job_tail(job_id, offset)` streamt sein Fortschrittsprotokoll (per Byte-Offset). `build_steer(job_id, instruction, interrupt)` stellt eine Korrektur für den nächsten Turn in die Warteschlange, oder `interrupt=true` bricht den aktuellen Turn ab (bereits geschriebene Dateien bleiben erhalten). Eine optionale ausführbare **Definition of Done** (`dod_cmd`, eine argv-Liste) läuft nach jedem Turn – Erfolg = fertig, Fehlschlag = ein weiterer Turn mit zurückgespieltem Fehler. |
| `batch_run` | **Dauerhaftes Fan-out**: viele unabhängige Anfragen parallel in **einem Aufruf** statt N (spart Host-Kontext + Kontingent). Jedes Ergebnis wird journalisiert, sodass `resume_id` die bereits fertigen Aufgaben wiederholt und nur den Rest ausführt – **übersteht einen Server-Neustart**. `async`-fähig. |
| `workflow` | **Fertige Multi-Modell-Workflows** auf dem Batch-Substrat. **`refine_plan`** – lass den Rat deinen Plan aus verschiedenen Blickwinkeln ZERLEGEN (übergib `plan_file`; jede Lane liest sie, nie kopiert). `council_review` (N Lanes beantworten eine Frage + optionaler Judge), `map_review` (viele Dateien parallel prüfen), `research_verify` (beantworten und dann adversarial gegenprüfen). Alle wiederaufnehmbar + `async`-fähig. |
| `list_models` | Listet die verfügbaren Modelle einer Lane auf (`lane`-Parameter), sofern die CLI sie offenlegt; andernfalls zeigt es das aufgelöste Standardmodell + wie man eines auswählt. (`list_<lane>_models` existiert ebenfalls für Lanes mit einem nativen List-Befehl.) |
| `conversations_list` / `conversation_show` | Listet aktuelle **Round-Table-Threads** auf (eine ID nach einem Kontext-Reset wiederfinden) / zeigt das vollständige Transkript eines Threads, nach Lane zugeordnet. |
| `doctor` | Gesundheitscheck: installierte CLIs, erkannter Host, Kosten-/Kontingent-Haltung, Cooldowns, Standardwerte. `deep: true` prüft die Authentifizierung jeder kostenlosen Lane live **und gleicht die Flags jeder Lane gegen ihre `--help` ab** – warnt, wenn eine CLI ein Flag umbenannt/entfernt hat, auf das sich cli-bridge verlässt (Drift), bevor die Lane still scheitert. |
| `usage_report` | Rein lokale Statistiken: Läufe, Erfolg/Latenz pro Lane und **geschätzte** Tokens (Zeichen/4) + Credits (pro Lane `CREDITS_PER_1K`). `since`, `format=text\|json`. |
| `usage_budget` | Heutige Läufe pro Lane gegen `CLI_BRIDGE_<LANE>_DAILY_LIMIT` + geschätzte Ausgaben; markiert Lanes über ihrem Limit. |
| `lane_stats` | Zustand pro Lane: Läufe, Fehlschläge, aufeinanderfolgende Fehlschläge/Timeouts, aktiver Cooldown. |
| `reset_lane_state` | Setzt Cooldown-/Fehlschlagzähler einer Lane zurück (nach erneuter Anmeldung oder Kontingent-Reset). |
| `setup` | Listet installierte Lanes mit ihren *belegten* typischen Plankosten auf (free/limited/paid – niemals aus deinem Konto erkannt), fragt, welche du tatsächlich bezahlst, und **empfiehlt ein Profil + Tageslimit** zur Bestätigung – und führt den Nutzer dann durch. |

Es gibt auch eine **menschliche CLI** – dieselbe Engine von deinem Terminal oder CI aus:
`cli-bridge init` (CLIs erkennen + MCP-Verdrahtung ausgeben), `doctor`, `ask <lane> <task>`, `ask-all`,
`ask-best --mode`, `review-diff --base origin/main --json`, `bench --lane gemini --prompt … `
(Latenz p50/p95/p99), `usage`, `budget`, `jobs`, `setup --write`. Siehe
`examples/github-action-pr-review.yml` für eine PR-Review-GitHub-Action (Self-Hosted Runner).

**Standardmäßig nur lesend; Schreibzugriffe per Opt-in.** Ein Delegierter analysiert und antwortet normalerweise – dein Host
wendet etwaige Änderungen an. Übergib `agent: "build"`, damit er **Dateien direkt bearbeitet** (z. B. *„ask gpt to
implement this function“*): claude → `--permission-mode acceptEdits`, gpt → `--sandbox
workspace-write`, mistral → `--agent accept-edits`, gemini → `--yolo` (oder `agy`
`--dangerously-skip-permissions`), opencode → `--agent build`. Build-fähige Lanes werden als
nicht-nur-lesend annotiert, und ein `build`-Lauf wird nie aus dem Cache bedient.

### Einen echten Build delegieren – beaufsichtigt, in deinem Repo

`ask_build` macht aus einem Delegaten einen Teamkollegen, der ein **vollständiges, echtes** Ergebnis
liefert, nicht nur einen Diff zum Kopieren. Zwei Modi:

- **`mode=isolated`** (Standard, am sichersten) – der Delegat bearbeitet einen Wegwerf-Git-Worktree
  bei HEAD; du bekommst den Diff und wendest ihn selbst an. In deinem Repo bewegt sich nichts.
- **`mode=direct`** – der Delegat schreibt **echte Dateien** in `target_dir`, sodass du (der Host)
  andere Teile **desselben Repos parallel** bauen kannst (z. B. *„ich mache das Backend, codex macht
  `frontend/`“*). Die Sicherheit beruht auf git + einem **Zonen-Vertrag**, nicht auf Isolation:
  - das Brief sagt dem Delegaten, dass er **nur in `zone`** schreiben darf (ein Pfad unter
    `target_dir`);
  - jedes Rückgängigmachen ist **zonen-begrenzt** (`git checkout -- <zone>` + `git clean -fd
    <zone>`, nie ein globales `git reset --hard`), sodass deine nicht committete Arbeit außerhalb der
    Zone nie angefasst wird;
  - ein **Zonen-Lock** lässt disjunkte Zonen gleichzeitig bauen, blockiert aber zwei Builds auf
    derselben Zone;
  - nach jedem Turn erkennt ein **globaler `git status`** alles, was außerhalb der Zone geschrieben
    wurde (Ausbruch über `../`, absoluter Pfad, Symlink) und **rollt den Build zurück** – das
    git-Scoping schützt git-Operationen, es kann den Subprozess nicht sandboxen, daher ist diese
    Prüfung Pflicht. Ein fehlendes/leeres `target_dir` wird angelegt und mit `git init` initialisiert.

**Beobachte und steuere ihn.** Starte mit `async=true`, um eine `job_id` zu bekommen, dann:

- `job_tail(job_id, offset)` streamt den Build-Fortschritt für Schritt-Zusammenfassungen;
- `build_steer(job_id, "nutze Tailwind, kein Inline-CSS")` reiht eine Korrektur für den nächsten Turn
  ein; `build_steer(job_id, interrupt=true)` bricht den aktuellen Turn ab (geschriebene Dateien
  bleiben);
- übergib `dod_cmd` (eine **argv-Liste**, z. B. `["npm","run","build"]`, nie ein Shell-String) für
  eine **wirklich getestete** Definition of Done nach jedem Turn – Erfolg = fertig, Fehlschlag = ein
  weiterer Turn mit zurückgespieltem Fehler, begrenzt durch `max_fail_retries` (Standard 3) und
  `max_turns` (12).

Kontinuität ist das Dateisystem (der Delegat liest seine eigenen Dateien jeden Turn neu); das rohe
Transkript lebt in der eigenen Sitzung des delegierten CLI, während cli-bridge das Schritt-Protokoll
für `job_tail` führt.

### Stelle deinen Plan auf die Probe, bevor du baust (`workflow refine_plan`)

cli-bridge ist stark darin, einen Plan zu *zerlegen*, bevor du Code schreibst. `workflow
preset=refine_plan` schickt deinen Plan an mehrere Lanes, die ihn je aus einem **eigenen Blickwinkel**
kritisieren (technische Schwächen & Fehlermodi / Lücken / Over-Engineering / Sequenzierung), und
gruppiert dann die Befunde für dich zum Zusammenführen – oder übergib `judge_lane` für eine einzige,
deduplizierte und nach Schweregrad sortierte Patch-Liste.

```jsonc
// ein Aufruf → N CLIs zerreißen den Plan, jeder aus einem anderen Blickwinkel
{ "preset": "refine_plan", "plan_file": "docs/plan.md", "judge_lane": "gpt" }
```

Übergib **`plan_file`** (einen Pfad), nicht den Text: jede Lane liest die Datei aus ihrem eigenen
Arbeitsverzeichnis, sodass der Plan **nie in N Prompts kopiert** wird – der token-sparsame Standard
für jede Artefakt-Prüfung (`map_review`, `review_diff`, `debate context_files` funktionieren genauso).
Wie jedes `workflow`/`batch_run` ist es **wiederaufnehmbar** (`resume_id` wiederholt fertige Aufgaben
nach einem Neustart) und kann `async` laufen.

**Pro Aufruf ein Modell wählen** mit `model` (z. B. `model: "claude-opus-4-6"`). Von innerhalb eines Hosts kannst du
sogar ein **Geschwistermodell deiner eigenen Familie** konsultieren – `ask_<your-host>` erscheint als separates
Werkzeug, das ein explizites `model` verlangt, sodass du aus Claude Code heraus Opus 4.6 fragen kannst, während 4.8 läuft.
(Antigravitys `agy` hat kein Pro-Aufruf-Modell-Flag – es nutzt, was auch immer seine eigenen Einstellungen auswählen.)

**Round-Table-Konversationen.** Übergib `conversation: "new"` an ein beliebiges `ask_<lane>`, um einen mehrstufigen
Thread zu starten; verwende die zurückgegebene ID erneut – **auch auf einer anderen Lane** – um fortzufahren. Jede Lane sieht das
geteilte Transkript mit deinen eigenen Beiträgen als „You“ markiert und den anderen namentlich genannt, sodass ein Rat aufeinander
aufbauen kann, statt jedes Mal kalt zu starten. Das Transkript wird lokal gespeichert (sqlite), sodass ein
Thread **den Kontext-Reset des Hosts (`/compact`) und einen Server-Neustart übersteht** – stelle einen mit
`conversations_list` wieder her, lies ihn mit `conversation_show`. Ein gleitendes Fenster
(`CLI_BRIDGE_CONVO_MAX_CHARS`, Standard 32000) behält die neuesten Beiträge und verwirft die ältesten, sodass die
Kosten pro Beitrag beschränkt bleiben, egal wie lange der Thread läuft.

Für opencode fragt ein leeres `model` per `opencode models` die aktuelle `opencode/*-free`-Liste ab und
nutzt eines davon (die 0-$-Stufe mit Ratenbegrenzung), ausgewählt nach Muster + sortiert – nie ein fixierter Name, sodass ein eingestelltes
kostenloses Modell automatisch ersetzt wird. Es ist **kostensicher**: ein nacktes `opencode/*`-Zen-Modell rechnet
pro Token ab (API-Kosten) und `opencode-go/*` verbraucht vorausbezahlte Credits, sodass der Standard nie stillschweigend
ein bezahltes Modell auswählt – übergib diese explizit, wenn du sie willst. Schlägt die Abfrage fehl, fällt es auf
einen kostenlosen Seed zurück; setze `CLI_BRIDGE_OPENCODE_MODEL`, um deinen eigenen Standard zu fixieren.

`ask_all` hält die Aufrufe pro Lane kurz (45 s Standard, 60 s max.), damit der MCP-Host eine Antwort erhält, bevor
seine eigene Tool-Call-Deadline greift. Für eine langsame/tiefe Antwort rufe diese Lane direkt mit einem längeren
`timeout_s` auf.

---

## Konfiguration

Alles sind Umgebungsvariablen – keine Code-Änderungen. Stimm es auf **deine** Abonnements ab:

| Variable | Wirkung |
|----------|--------|
| `CLI_BRIDGE_<LANE>_COST` | `free`, `limited` oder `paid`. `free` tritt `ask_all` bei; `limited` ist kontingent-sensibel und wird von breiter Verteilung übersprungen; `paid` gibt Geld/Credits aus und wird standardmäßig übersprungen. |
| `CLI_BRIDGE_<LANE>_ENABLED` | `false`, um eine Lane auszublenden, selbst wenn ihre CLI installiert ist. |
| `CLI_BRIDGE_<LANE>_BIN` | Richtet eine Lane auf eine andere Binärdatei aus (z. B. `CLI_BRIDGE_GEMINI_BIN=agy`). |
| `CLI_BRIDGE_<LANE>_MODEL` | Standardmodell für eine Lane, wenn der Aufrufer keines übergibt. |
| `CLI_BRIDGE_PROFILE` | `saver`, `balanced` oder `max`. `max` schließt limitierte/bezahlte Lanes in `ask_all` ein, sofern der Aufrufer `include_paid` nicht überschreibt. |
| `CLI_BRIDGE_HOST` | Erzwingt die Host-Identität (welche Lane auszublenden ist). Normalerweise automatisch erkannt. |
| `CLI_BRIDGE_LANES_FILE` | Pfad zu einer JSON-Datei, die **deine eigenen** CLIs/APIs als Lanes hinzufügt. |
| `CLI_BRIDGE_DISABLED_TOOLS` | Kommagetrennte Werkzeugnamen, die aus der Auflistung auszublenden sind (z. B. `debate,premortem,test_plan`) – kürzt den Schema-Kontext, den jeder Host pro Anfrage bezahlt. `doctor`/`setup` können nicht ausgeblendet werden. |
| `CLI_BRIDGE_ENABLED_TOOLS` | Allowlist für einen Ein-Env-**Lean-Modus**: wenn gesetzt, werden nur diese Werkzeuge (+ `doctor`/`setup`) bereitgestellt (z. B. `ask_best,ask_all,review_diff`). |
| `CLI_BRIDGE_<LANE>_PRIORITY` | Niedrigere Werte laufen früher in `ask_cascade` (Standard 50). Fixiere deine bevorzugte Reihenfolge. |
| `CLI_BRIDGE_INLINE_MAX_CHARS` | Oberhalb dessen wird eine Antwort in eine Datei ausgelagert, statt den Kontext zu fluten (Standard 12000). |
| `CLI_BRIDGE_TERSE` | `off` / `lite` (Standard) / `full` / `ultra`. Stellt den Delegierten-Prompts eine kompakte Antwortstil-Präambel voran (englisch, intern vollständig schlussfolgern, knapp antworten, Code/JSON unberührt), um sowohl deinen Kontext als auch die Ausgabe-Tokens des Delegierten zu kürzen. Wird nie auf strukturierte Workflow-Werkzeuge angewendet. |
| `CLI_BRIDGE_TERSE_MIN_CHARS` | Überspringt die knappe Präambel für Aufgaben, die kürzer als so viele Zeichen sind (Standard `0` = nie überspringen). Winzige Aufgaben können den festen Overhead der Präambel nicht hereinholen. |
| `CLI_BRIDGE_GUARD` | `off` / `warn` (Standard) / `strict`. Scannt die **Delegierten-Ausgabe** auf Prompt-Injection / Tool-Poisoning; `warn` stellt ein Banner voran, `strict` hält den Inhalt zurück. Läuft nach der Geheimnis-Redaktion. |
| `CLI_BRIDGE_MOCK` | `1` = Trockenlauf: Lanes melden sich als installiert und geben eine vorgefertigte Antwort zurück, ohne eine CLI zu starten. Probiere das gesamte Werkzeug mit **null installierten CLIs**. |
| `CLI_BRIDGE_RETRIES` | Wiederholungen bei einem TRANSIENTEN Fehlschlag (Standard 1). Bringt eine wacklige CLI beim ersten Versuch zum Laufen; Kontingent/Auth/Nicht-gefunden/Timeout werden nie wiederholt. |
| `CLI_BRIDGE_TRACE_DIR` | Wenn gesetzt, schreibt jede Delegation hierhin eine redigierte JSON-Spur (argv, Timing, Ausgabe) – reproduzierbares Debugging / Audit. Standardmäßig aus. |
| `CLI_BRIDGE_MAX_PARALLEL` | Obergrenze gleichzeitiger Delegierten-Spawns in `ask_all` (Standard 6). Hindert einen breiten Rat (viele eigene Lanes) daran, eine kleine Maschine ins OOM zu treiben oder Kontingent zu sprengen. |
| `CLI_BRIDGE_DAILY_CREDIT_CAP` | Harte Obergrenze für *geschätzte* bezahlte Ausgaben pro UTC-Tag. >0 verweigert eine bezahlte Lane, sobald die heutige Schätzung sie erreicht – macht „kostensicher“ durchsetzbar, nicht nur berichtet. Kostenlose Lanes werden nie gegated. |
| `CLI_BRIDGE_ALLOW_LANES` | Allowlist, z. B. `gemini,gpt`. Leer = alle. Abgeschottete / Team-Setups: nur diese Lanes werden bereitgestellt. |
| `CLI_BRIDGE_DISABLE_BUILD` | `1` zwingt jeden Delegierten auf nur-lesend (plan), selbst wenn ein Aufrufer `agent: build` verlangt. Für geteilte Maschinen. |
| `CLI_BRIDGE_OVERFLOW_MAX_FILES` | Obergrenze für die Dateianzahl im Overflow-Verzeichnis (Standard 200); die ältesten darüber hinaus werden beschnitten, damit `/tmp` nicht unbegrenzt wachsen kann. |
| `CLI_BRIDGE_CONFIG_FILE` | Pfad zu einer JSON-Konfiguration (Standard `~/.config/cli-bridge/config.json`). Eine freundlichere Alternative zu Umgebungsvariablen – **die Umgebung gewinnt immer**. Siehe unten. |
| `CLI_BRIDGE_CACHE_TTL_S` | `0` = aus (Standard). Bei `>0` gibt ein identischer Aufruf innerhalb dieser Sekundenzahl die zwischengespeicherte Antwort zurück, statt die CLI erneut zu starten (spart Kontingent/Credits bei Wiederholungen; Build-Läufe werden nie zwischengespeichert). |
| `CLI_BRIDGE_<LANE>_CREDITS_PER_1K` | Credits pro 1k Tokens für eine Lane, von `usage_report`/`usage_budget` verwendet, um Ausgaben zu **schätzen** (Zeichen/4). |
| `CLI_BRIDGE_<LANE>_DAILY_LIMIT` | Maximale Läufe/Tag für eine Lane; `usage_budget` markiert, wenn überschritten. |
| `CLI_BRIDGE_<LANE>_MIN_INTERVAL_S` | Anti-Burst-Spawn-Taktung: Mindestsekunden zwischen Spawns dieser Lane (Standard `0` = aus). Setze es (z. B. `2`), wenn eine kostenlose Stufe bei aufeinanderfolgenden Aufrufen die Rate begrenzt – Bursts derselben Lane werden gleichmäßig verteilt, andere Lanes bleiben parallel. `lane_stats` gibt Hinweise, wenn eine Lane das Muster der Ratenbegrenzung zeigt. |
| `CLI_BRIDGE_KEEP_WORKTREES` | Behält `ask_build_isolated`-Worktrees, statt sie zu verwerfen (zur Inspektion). |
| `CLI_BRIDGE_REVIEW_TIMEOUT_S` | Timeout pro Reviewer für `review_diff` / `security_review` (Standard 180; diese sind bewusst schwergewichtiger als `ask_all`). |
| `CLI_BRIDGE_OVERFLOW_TTL_H` | Stunden, bevor eine ausgelagerte Overflow-Datei beschnitten wird (Standard 24). |
| `CLI_BRIDGE_TELEMETRY` | `off`, um das lokale Run-Log / die Cooldown-Verfolgung zu deaktivieren (Standard an, ausschließlich maschinenlokal). |
| `CLI_BRIDGE_TRACE_FOOTER` | `off` blendet die `## Trace`-JSON-Fußzeile in Workflow-Berichten aus – angenehmer für Menschen, die sie im Terminal lesen; MCP-Hosts wollen sie meist (Standard an). |
| `CLI_BRIDGE_STATE_DB` | Pfad zur lokalen sqlite-Zustands-DB (Standard `~/.local/share/cli-bridge/state.sqlite`). |
| `CLI_BRIDGE_STORE_TRANSCRIPTS` | `true`, um eine längere Aufgabenvorschau in der Telemetrie zu behalten (Standard: nur Hash + 60-Zeichen-Vorschau). |
| `CLI_BRIDGE_LOG` / `_LOG_FILE` | `debug`/`info`, um zu protokollieren, was wo lief (Standard: still). |

### Konfigurationsdatei (statt einer Wand aus Umgebungsvariablen)

Lieber eine Datei? Leg `~/.config/cli-bridge/config.json` ab (oder richte `CLI_BRIDGE_CONFIG_FILE` darauf aus).
Sie füllt jede Umgebungsvariable, die du nicht gesetzt hast – **die Umgebung gewinnt immer**, und die Standardwerte funktionieren weiterhin
ganz ohne Datei:

```json
{
  "profile": "balanced",
  "guard": "warn",
  "daily_credit_cap": 5.0,
  "lanes": {
    "gemini":   { "cost": "free" },
    "opencode": { "cost": "free", "model": "opencode/deepseek-v4-flash-free" },
    "gpt":      { "cost": "limited", "daily_limit": 50 }
  }
}
```

### Füge deine eigene CLI hinzu (kein Fork)

`my-lanes.json`, dann `CLI_BRIDGE_LANES_FILE=/path/to/my-lanes.json`:

```json
[
  {
    "key": "aider", "display": "Aider", "bin": "aider",
    "ask": ["--message", "{task}"], "model_flag": "--model",
    "client_ids": ["aider"], "note": "Aider one-shot via --message."
  }
]
```

Jetzt hast du ein `ask_aider`-Werkzeug. (Eine eigene Lane mit einem eingebauten Schlüssel, z. B. `grok`, *überschreibt*
die eingebaute – praktisch, wenn die Flags deiner Installation abweichen.)

**Das breitere Ökosystem, bereit zum Einstöpseln:** `examples/community-lanes.json` liefert Best-Effort-
Lanes für **Aider, Goose, Plandex, Amp, Crush, Amazon Q Developer CLI und Droid (Factory)** –
alle als experimentell und `limited` markiert (aus breiter Verteilung herausgehalten, bis *du* erklärst, was sie
dich kosten), und alle abgedeckt durch die Flag-Drift-Prüfung von `doctor deep`, die jede Lane
gegen die `--help` der CLI auf *deiner* Maschine validiert, bevor etwas still bricht. Claude Code,
Codex, Gemini + Antigravity (`agy`), opencode, Qwen Code, Copilot und Grok sind bereits
eingebaut. Alles andere (Cline, OpenHands, Continue, Roo/Kilo Code, Kimi K2 CLI, …) ist nur
dasselbe 3-Zeilen-JSON entfernt – und jede dieser CLIs, die MCP spricht, kann auch auf der *anderen* Seite sitzen
und cli-bridge als ihren Server betreiben.

### Bring deine eigene API mit (keine CLI nötig)

Kapsele jeden OpenAI-kompatiblen Endpunkt, indem du `curl` startest. Dein Schlüssel bleibt in einer Umgebungsvariable, nie in der
Datei. `{task_json}` ist der Prompt, JSON-escaped:

```json
[
  {
    "key": "myapi", "display": "My API", "bin": "curl", "default_model": "gpt-4o-mini",
    "paid": true,
    "ask": [
      "-sS",
      "--variable", "%MY_API_KEY",
      "--expand-header", "Authorization: Bearer {{MY_API_KEY}}",
      "https://api.openai.com/v1/chat/completions",
      "-d", "{\"model\":\"{model}\",\"messages\":[{\"role\":\"user\",\"content\":\"{task_json}\"}]}"
    ]
  }
]
```

Das Paar `--variable %MY_API_KEY` + `--expand-header` (curl ≥ 8.3) importiert den Schlüssel *innerhalb* von
curl – er erscheint nie in der Prozessliste. `doctor` warnt, wenn eine eigene Lane stattdessen ein `${ENV}`-
Geheimnis in argv expandiert.

(Siehe `examples/` für beides, bereit zum Kopieren.)

---

## Wie es funktioniert

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
              hides the host's own lane · only shows installed, enabled CLIs
              kills the whole process tree on timeout / cancellation
              redacts secrets · classifies errors · spills huge output to a file
```

Keine eigenen Netzwerkaufrufe. Keine gespeicherten Schlüssel. Es führt dieselben Binärdateien aus, denen du bereits vertraust, in deinem
Arbeitsverzeichnis, und gibt die Antwort zurück.

### Funktioniert auch in IDE-MCP-Hosts

cli-bridge ist schlichtes MCP über stdio, also funktioniert jeder MCP-fähige Host – nicht nur Terminal-CLIs.
Richte Cursor / VS Code (Cline, Continue) / Zed auf den **gleichen Befehl** aus (`uvx cli-bridge-mcp` oder
`<python> -m cli_bridge`). Die eigene Lane des Hosts wird automatisch ausgeblendet; alles andere ist identisch.

### Bekannte Einschränkungen (ehrliche Liste)

- **Ban-Sicherheit hängt von den ToS jedes Anbieters ab.** cli-bridge führt nur die offizielle CLI aus, die du von
  Hand ausführen würdest – aber nicht-interaktive/skriptgesteuerte Nutzung ist nicht *garantiert* sanktioniert und kann sich ändern. Nutze
  deine eigenen Konten innerhalb ihrer Bedingungen; behandle „ban-sicher“ als „keine Token-/Schlüssel-Extraktion“, nicht als
  pauschale Garantie.
- **Async-Jobs laufen in-process.** Ein Server-Neustart markiert laufende Jobs als `interrupted`.
  `batch_run` und `workflow` sind die Ausnahme – sie journalisieren jede Aufgabe, sodass eine
  `resume_id` die fertigen wiederholt und nach einem Neustart nur den Rest ausführt.
- **PATH-Fallen durch Shell-Wrapper.** Wenn deine Shell die delegierten CLIs in eine Funktion oder
  einen Alias hüllt (z. B. eine `_opsec`-Schutzfunktion in `.zshrc`), kann der Start von cli-bridge
  *aus dieser Shell* fehlschlagen – aber cli-bridge startet die **Binärdatei direkt** (ohne Shell)
  und ist daher nicht betroffen; nur ein Wrapper, der die Binärdatei im `PATH` überdeckt, zählt.
  `doctor` zeigt den aufgelösten Pfad je Lane.
- **Die Injection-Schutzleiste ist heuristisch.** Sie fängt Muster mit hohem Signalgehalt, nicht alles; im
  `warn`-Modus erreicht der Text trotzdem den Host (behandle Delegierten-Ausgabe als Daten).
- **Token-/Credit-Zahlen sind Schätzungen** (Zeichen/4 + dein `CREDITS_PER_1K`), nie exakt.
- **BYO-API-(curl-)Lanes:** ein `${ENV}`-Schlüssel wird in argv substituiert, sodass er in der
  Prozessliste dieser Maschine erscheinen kann, während der Aufruf läuft (er wird nie protokolliert – Spuren redigieren ihn). Bevorzuge die
  eigene CLI eines Anbieters, wo möglich; für curl vermeidet eine Header-Datei (`curl -H @file`) die argv-Offenlegung.
- **Experimentelle Lanes** (`qwen`, `copilot`, `grok`): Flags sind nicht live verifiziert – Fehler melden.
- **Kostenstufen sind belegte Voreinstellungen, keine Erkennung** – Anbieterplan-Fakten datiert Juni 2026
  ([docs/COSTS.md](../COSTS.md)); Pläne/Kontingente wechseln, `doctor` warnt, wenn der Snapshot veraltet ist.
- **Sandboxed Host:** wenn dein Host den Server in einer strikten Sandbox ausführt (nur-lesendes FS / kein
  Netzwerk), erben gespawnte CLIs sie und erreichen ihre Anbieter möglicherweise nicht. cli-bridge meldet
  dies als `auth`/`failed`-Fehler, statt hängen zu bleiben.

---

## Entwicklung

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration (cross-host) tests
```

## Lizenz

MIT

---

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../assets/mark-dark.svg">
  <img src="../../assets/mark-light.svg" width="84" alt="cli-bridge">
</picture>

<sub>eine Seite · verbunden mit einem Rat</sub>

</div>
