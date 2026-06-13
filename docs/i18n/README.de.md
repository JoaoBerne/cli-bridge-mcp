<div align="center">

<img src="../../assets/banner.gif" width="860" alt="cli-bridge — dein Assistent leiht sich die Fähigkeiten aller KI-CLIs, die du schon hast: riesige Kontext-Reads, Vision, parallele Builds, anbieterübergreifende Prüfungen">

[English](../../README.md) · [Français](README.fr.md) · [简体中文](README.zh-CN.md) · [Español](README.es.md) · [Português (BR)](README.pt-BR.md) · [日本語](README.ja.md) · **Deutsch**

</div>

_Das englische README ist maßgeblich; diese Übersetzung kann hinterherhinken. Community-Review willkommen._

# cli-bridge

![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/cli-bridge-mcp)
![stars](https://img.shields.io/github/stars/JoaoBerne/cli-bridge-mcp?style=flat&color=yellow)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-Apache%202.0-green)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**Dein Assistent ist nur so gut wie das eine Modell, das du geöffnet hast.** cli-bridge ist ein [Model Context Protocol](https://modelcontextprotocol.io)-Server, der ihn die *anderen* KI-CLIs ausleihen lässt, die du ohnehin schon nutzt — ein größeres Kontextfenster, Vision, eine kostenlose Zweitmeinung von einem *anderen Anbieter* oder ein delegierter Build, der als prüfbares Diff zurückkommt.

> **Keine API-Schlüssel · keine Token-Extraktion · kein Node · kein Daemon · nur stdlib + `mcp`.**

### In einem Satz

Du sprichst mit einem KI-Assistenten. Du hast auch andere installiert und bist dort eingeloggt —
Claude Code, Codex, Gemini, opencode, Ollama. **cli-bridge verbindet sie**: Wenn dein Assistent
etwas braucht, das er allein nicht kann, fragt er eine der anderen CLIs und liefert dir das Ergebnis.

### Das Problem, das es löst

Egal welchen Assistenten du nutzt — er hat harte Grenzen. Er kann kein 2-Mio.-Token-Repo in einem
Durchgang lesen, keinen Screenshot sehen, dir kein generiertes Bild liefern und seine eigene Arbeit
nicht verzerrungsfrei prüfen — aber *irgendeine andere CLI auf deinem Rechner kann jede dieser
Sachen*. cli-bridge ist die Brücke dazwischen: Es startet die offizielle CLI als Subprozess (genau
so, wie du sie von Hand ausführen würdest — keine Schlüssel, keine Token-Extraktion) und gibt die
Antwort an deinen Assistenten zurück.

Das Ergebnis: ein Assistent, dessen Obergrenze auf jeder Achse das *beste* Werkzeug deines Kastens
ist — nicht das, das du zufällig geöffnet hast.

---

## Die 10-Sekunden-Demo

Du bist in Claude. Claude kann dir kein Bild liefern. Codex schon — es schreibt den Code, der eines
rendert, und führt ihn aus. Also frag es:

```
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png — write a script that renders it, then run it", zone="assets")
→ Codex writes assets/card.png · you get the path back, never a binary blob (artifact-return)
```

Dein Assistent hat gerade eine Fähigkeit gewonnen, die er nicht hat. Das ist die ganze Idee — jetzt
skaliere sie auf riesige Kontext-Reads, Vision, parallele Fleißarbeit und unabhängige
anbieterübergreifende Verifikation.

_(Codex erzeugt das Bild mit **`gpt-image-2`**, einem echten Text-zu-Bild-Modell direkt im CLI —
angerechnet auf dein ChatGPT-Abo, ohne separaten API-Schlüssel (Bildgenerierung erfordert ein
**bezahltes** Abo; im Free-Tarif nicht verfügbar). Das Ergebnis kommt als **Pfad** zurück, nicht als
Blob, weil Binärdateien per Artifact-Return laufen, nicht über den Textkanal. Eine Build-Lane kann
außerdem Diagramme, Charts oder SVGs *rendern*, indem sie Code schreibt — wenn das besser passt.)_

### …und es delegiert echte Arbeit, sicher

`cli-bridge build <lane> "<Aufgabe>"` übergibt die Arbeit einem anderen Modell, das in einem
**wegwerfbaren git-Worktree** läuft, und gibt dir dann einen **Diff** zurück — dein Repo wird nie
angefasst, bis du ihn selbst anwendest.

<p align="center">
<img src="../../assets/demo-borrow.gif" width="860" alt="cli-bridge build: opencode fügt in einem wegwerfbaren Worktree eine Funktion hinzu und gibt einen prüfbaren Diff zurück; das echte Repo bleibt sauber">
</p>

---

## Was du bekommst — die vier Hebel

cli-bridge ist keine Funktion, sondern **vier Hebel**. Verstehe sie, und jedes Tool unten fügt sich ein:

1. **Leihen** — eine Fähigkeit erreichen, die deinem Assistenten fehlt (Vision, ein 1-Mio.-Token-
   Kontextfenster, eine Datei, die ein Coding-Agent generiert, ein Modell, das hierin schlicht besser
   ist).
2. **Verteilen** — wenn ein Abo sein Limit erreicht, auf einer anderen Lane weitermachen, die du schon
   bezahlst.
3. **Auslagern** — mühsame, parallelisierbare Fleißarbeit auf günstige/kostenlose Lanes verteilen,
   während du anderswo baust.
4. **Verifizieren** — eine *andere Anbieterfamilie* die Arbeit prüfen lassen, weil ein Modell seine
   eigenen blinden Flecken nicht sieht. Das Einzige, was ein Single-Vendor-Tool strukturell nicht kann.

---

## Was das freischaltet

Jeder Block: ein Satz dazu, *wann du dazu greifst*, der genaue Aufruf, und *was du zurückbekommst*.

### Leihe Fähigkeiten, die dein Assistent nicht hat
Jede CLI hat einen anderen Superpower, und jede läuft nicht-interaktiv — also kann cli-bridge sie
starten. Leihe dir die, die deinem Host fehlt (sie muss installiert + eingeloggt sein):

| Superpower | Welche CLI hat ihn | Leihen, wenn |
|------------|------------------|----------------|
| **Bilder** | Codex (`gpt-image-2`, **kein API-Schlüssel** — bezahltes ChatGPT-Abo, nicht Free) | dein Host nicht zeichnen kann |
| **Riesiger Kontext** | Gemini (1-Mio.-Token-Fenster) | eine Datei/ein Repo nicht in den Kontext deines Hosts passt |
| **Frisches Wissen** | Gemini (Google-Search-Grounding) · Grok (Live-Web/X) ⚗️ | einen Stichtag schlagen: *„wie ist die aktuelle API von `<lib>`?“* |
| **Vision** | Gemini (`images=[…]`) ⚗️ | einen Screenshot oder ein Diagramm analysieren |
| **Eine kostenlose Zweitmeinung** | Gemini (kostenlose Tagesstufe) · opencode · Ollama (lokal, 0 $) | ein 0-$-Gegencheck |
| **Generierte Dateien** | jede Build-Lane → artifact-return | ein Chart / PDF / Diagramm **per Pfad** zurückbekommen |
| **Video** ⚗️ | Gemini (Veo) · Grok (Imagine) — *wenn deine installierte CLI es bereitstellt* | du brauchst einen generierten Clip |

```
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png", zone="assets")   # Codex image → file by path, no API key (paid ChatGPT plan)
ask_gemini(task="find the bug across ./src — read the files you need", cwd="path/to/repo")         # 1M-token context
ask_gemini(task="what's the current recommended API for <lib>? check the latest docs")            # fresh knowledge (Search grounding)
ask_gemini(task="what's wrong in this UI?", images=["screenshot.png"])                             # vision (experimental)
```

⚗️ = experimentell / hängt vom aktuellen Build der installierten CLI ab (z. B. ist Grok Build Beta) — mit `doctor deep` prüfen.

### Hör nie auf zu arbeiten, wenn du an ein Limit stößt
Wenn dein Haupt-Abo mitten in der Aufgabe ausläuft. `ask_cascade` fällt auf eine andere Lane zurück,
die du schon bezahlst, und überspringt jede Lane, die nach einem Kontingent-/Auth-/Timeout-Fehler in
Abkühlung ist.

```
ask_cascade(task="finish wiring this endpoint")   # cheapest→strongest; a cooled-down lane is skipped
ask_best(task="…", mode="deep")                   # let the router pick the most suitable available lane
```

### Lagere die Fleißarbeit aus — parallel und günstig
Wenn die Arbeit mühsam, aber nicht schwer ist (Refactorings, Migrationen, Test-Abdeckung). Fächere sie
auf, journaled, sodass ein Server-Neustart fortsetzt statt neu zu beginnen; delegiere einen Build und
arbeite weiter.

```
batch_run(tasks=[...], dry_run=true)                       # cost envelope first — nothing is spawned
batch_run(tasks=[...], max_calls=20, max_credits=2.0)      # then run under a hard budget (resumable)
ask_build(lane="opencode", task="add the landing page", zone="frontend", mode="direct", async=true)   # delegate, keep building
job_tail(job_id="…")  ·  build_steer(job_id="…", instruction="use Tailwind, not inline CSS")
```

### Brich die Selbstbestätigung — das 2026-Problem, das ein Anbieter nicht lösen kann
Wenn du einem Ergebnis *vertrauen* musst. Ein Modell, das seine eigene Arbeit (oder die eines
Geschwisters) prüft, bestätigt nur seine eigenen blinden Flecken. cli-bridge setzt eine **andere
Modellfamilie** auf den Prüferstuhl.

```
workflow(preset="jury", task="is this migration safe?", author_lane="gpt")            # cross-family vote, fail-closed
workflow(preset="verify_repair", task="add retry with backoff",
         builder_lane="gpt", verifier_lane="gemini")                                   # A builds, B reviews, loop to green
security_review(base="origin/main")   ·   review_diff(base="origin/main")              # OWASP, severity-ranked
```

### Hol dir eine echte Zweitmeinung
Wenn du zu einem Schluss gekommen bist und ihn unter Druck testen willst, oder mehrere Modelle
nebeneinander.

```
challenge(task="I'm dropping the cache layer — here's why: …")                         # one skeptic attacks it
consensus(task="which migration strategy is safest here?")                             # N answer, peer-rank the best
workflow(preset="fanout_compare", task="fix this failing test", lanes=["gpt","gemini","opencode"])
```

---

## Der Werkzeugkasten

~30 Werkzeuge, nach Absicht gruppiert (konsultieren / bauen / prüfen / orchestrieren). **Vollständige Referenz — jedes Werkzeug, jeder Flag: [`docs/TOOLS.md`](../../docs/TOOLS.md)** (oder `cli-bridge --help`). `CLI_BRIDGE_LEAN=1` für eine schlanke Oberfläche (~12 Werkzeuge).

---

## Was du tatsächlich bekommst, wenn du sie kombinierst

Ein einziger Assistent, dessen Obergrenze auf **jeder Achse das Beste des Ökosystems** ist — nicht das
Tool, das du heute Morgen geöffnet hast: coden mit dem stärksten Modell, 1–2 Mio. Tokens lesen, wenn
deiner zu kurz ist, mit frischem Wissen über einen Stichtag hinaus antworten, Bilder/Video generieren,
Screenshots sehen, und auf eine kostenlose/lokale Lane zurückfallen, wenn du gedeckelt bist —
verteilt über die Abos, die du ohnehin bezahlst.

Die emergente Eigenschaft, **die keine einzelne CLI hat: echte anbieterübergreifende Kontrolle** — ein
*anderer Anbieter* auf dem Prüferstuhl. Subagenten derselben Familie (die von Claude Code, von Grok)
können sich nur selbst bestätigen.

Die ehrliche Naht: Dies vereint **Fähigkeiten, keinen Verstand** — zustandslose Spawns (kein
geteiltes Gedächtnis), Spawn-Latenz/-Kosten, ungleiche Qualität, und der Host steuert immer. Es ist
**Orchestrierung, keine Fusion**: Du dirigierst Spezialisten, du bekommst kein einzelnes Gehirn mit
allen Kräften.

→ Stärken & Grenzen pro CLI (datiert, ändert sich schnell): **[docs/COMPARISON.md](../COMPARISON.md)**.

## Warum cli-bridge (und nicht ein anderes „andere Modelle aufrufen“-MCP)

- 🛡️ **Ban-safe per Design.** Es startet die **offizielle CLI** jedes Modells, genau so, wie du sie von
  Hand ausführen würdest — keine OAuth-Token-Extraktion, keine API-Schlüssel-Wiederverwendung. Jede
  CLI regelt ihre eigene Auth und Abrechnung.
- 💸 **Cost-safe-Defaults, die du an deinen Plan anpasst.** Out of the box bauen `ask_all` /
  `ask_cascade` einen *kostenlosen* Rat und rühren bezahltes Kontingent nie an, außer du verlangst es.
  Jede Lane bringt eine Stufe aus den veröffentlichten Plänen des Anbieters mit (datiert in
  [docs/COSTS.md](../COSTS.md), **nie aus deinem Konto erkannt**); pro Lane überschreiben mit
  `CLI_BRIDGE_<LANE>_COST=free|limited|paid`.
- 🔌 **Funktioniert von jedem Host.** Claude Code, Codex, opencode, Cursor, VS Code (Cline/Continue),
  Zed — alles, was MCP über stdio spricht. Die eigene Lane des Hosts bleibt aus dem Fan-out; blende sie
  mit `CLI_BRIDGE_HIDE_HOST=1` aus. Sogar ein **lokales Modell kann der Host sein** — siehe
  [`examples/local-first-host.md`](../../examples/local-first-host.md).
- 🧭 **Der anbieterübergreifende Vorteil ist der Burggraben.** Unabhängige Verifikation bedeutet einen
  *anderen Anbieter* auf dem Prüferstuhl — das Knappe, je mehr KI einen größeren Teil des Codes
  schreibt, und genau das, was ein Single-Vendor-Tool nicht bieten kann.

---

## Wie es funktioniert

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
       keeps the host's own lane out of fan-out · only shows installed, enabled CLIs
       kills the whole process tree on timeout/cancellation · redacts secrets
       classifies errors (auth/limit/failed) · spills huge output to a file
```

Keine eigenen Netzwerkaufrufe. Keine gespeicherten Schlüssel. Es führt dieselben Binaries aus, denen
du schon vertraust, in deinem Arbeitsverzeichnis, und gibt dir die Antwort zurück.

<div align="center">

<img src="../../assets/demo.gif" width="860" alt="cli-bridge security-review-Demo: ein committetes Autorisierungs-Bypass wird von einem anbieterübergreifenden Rat erfasst, in einen nach Schweregrad geordneten Bericht zusammengeführt, 0 $ auf kostenlosen Lanes">

_Echter Lauf (2,2× Geschwindigkeit): der Verifizieren-Hebel — `security-review` fächert OWASP-Rollen
über kostenlose Modelle parallel auf (hier claude/gpt/opencode/ollama); sie melden ein committetes
Auth-Bypass als **Blocker**, und `usage` zeigt die Belege._

</div>

---

## Code sicher schreiben: zwei Modi

Schreibvorgänge sind eingegrenzt, auf zwei Arten — **du wählst** review-gegated oder freihändig:

- **`isolated` (Standard).** Editiert in einem wegwerfbaren git-Worktree und gibt einen **Diff**
  zurück. Dein Arbeitsbaum wird nie angefasst.
- **`direct`.** Schreibt echte Dateien, **aber nur innerhalb einer `zone`, die du deklarierst**, hinter
  einer Sperre pro Zone mit Zonenverletzungs-Check nach dem Zug. Du in `backend/`, ein Delegierter in
  `frontend/`, gleichzeitig — keiner kann dein ganzes Repo verkritzeln; das Rückgängigmachen ist
  zonen-begrenzt, nie ein globaler Reset.

Der Wiedereintritt von Delegierten ist tiefenbegrenzt (`CLI_BRIDGE_MAX_DEPTH`, Standard 1), damit ein
fehlkonfigurierter Delegierter den Rat nicht fork-bomben kann.

Setze `CLI_BRIDGE_VERIFY_PLAN_READONLY=1`, und jeder `plan`-Delegierte (read-only), der trotzdem in
einen git-Arbeitsbereich schreibt, erhält das Flag `⚠️ WORKSPACE MUTATION DETECTED` an seiner Antwort
(sichtbar gemacht, nie automatisch zurückgerollt).

---

## Schnellstart (≈5 Min)

```bash
# Run it (no install) — uvx fetches, runs, discards:
uvx --from cli-bridge-mcp cli-bridge doctor
# or, from a clone:  python -m cli_bridge

# Point your MCP host at that same command, then:
cli-bridge doctor        # see which CLIs are detected + their resolved paths
```

### Lanes

**Eingebaut:** Claude Code, Codex, Gemini (+ Antigravity `agy`), opencode, **Ollama (lokale Modelle,
0 $, offline)**, Qwen Code, Copilot, Grok und **OpenRouter** (Opt-in-API-Lane — 400+ Modelle; bleibt
verborgen, bis du `OPENROUTER_API_KEY` setzt, sodass die ban-safe-Standardoberfläche unverändert
bleibt).

**Lokale Runtimes** jenseits von Ollama — **LM Studio · MLX · llama.cpp** — kommen als Code-freie
Rezepte: richte `CLI_BRIDGE_LANES_FILE` auf [`examples/lmstudio.lane.json`](../../examples/lmstudio.lane.json),
[`mlx.lane.json`](../../examples/mlx.lane.json) oder [`llamacpp.lane.json`](../../examples/llamacpp.lane.json).
(Mehrere lokale Runtimes *derselben* offenen Gewichte liefern korrelierte Antworten — echte
Rat-Diversität kommt von verschiedenen Anbietern, nicht von einem zweiten lokalen Runtime.)

**Community-Lanes** (`examples/community-lanes.json`, experimentell + `limited`, bis du ihre Kosten
deklarierst): Aider, Goose, Plandex, Amp, Crush, Amazon Q Developer CLI, Droid.

**Alles andere sind ~3 Zeilen JSON.** Füge eine eigene Lane hinzu, oder umhülle jeden
OpenAI-kompatiblen Endpoint, indem du `curl` startest (der Schlüssel bleibt in curl, nie in argv),
oder nutze die mitgelieferte stdlib-Brücke **`cli-bridge-openai`** — setze `availability_env`, damit
die Lane verborgen bleibt, bis ihr Schlüssel exportiert ist. Siehe
[`examples/openai-compatible.lane.json`](../../examples/openai-compatible.lane.json).
Siehe [`examples/`](../../examples/) für Rezepte.

---

## Der ehrliche Teil

„Mehr Modelle = besser“ ist *fragil* — große Modelle teilen Trainingsdaten, also korrelieren ihre
Fehler. Wir haben unsere eigene zentrale Behauptung gemessen (`cli-bridge eval`, kein LLM-Richter): ein
diverser Rat fand **nicht** mehr Bugs als ein einzelnes starkes Modell — er halbierte die Fehlalarme
**~2×**. Gleiche Trefferquote, weit weniger Rauschen — genau das, was einen Prüfer vertrauenswürdig
statt überhört hält. **Präzision ist das Produkt, nicht Recall.** Das Harness wird mitgeliefert, du
kannst es also an *deinen* CLIs bestätigen — Zahlen in beide Richtungen in
[docs/BENCHMARKS.md](../BENCHMARKS.md).

---

## Bekannte Einschränkungen

- **Ban-safe = keine Token-/Schlüssel-Extraktion**, keine pauschale Garantie — nicht-interaktive
  Nutzung der CLI eines Anbieters ist nicht überall formell sanktioniert und kann sich ändern. Nutze
  deine eigenen Konten im Rahmen ihrer Bedingungen.
- **Asynchrone Jobs laufen in-process** — ein Server-Neustart markiert laufende Jobs als
  `interrupted`. `batch_run` / `workflow` sind die Ausnahme: Sie journaln jede Aufgabe und setzen via
  `resume_id` fort.
- **Der Injection-Guard ist heuristisch** — er fängt Muster mit hohem Signal, nicht alles; behandle
  Delegierten-Ausgabe als Daten, nicht als Anweisungen.
- **Token-/Credit-Zahlen sind Schätzungen** (chars/4 + dein `CREDITS_PER_1K`), nie exakt.
- **Kostenstufen sind gesourcte Defaults, keine Erkennung** — Plan-Fakten sind datiert; `doctor` warnt,
  wenn der Snapshot veraltet ist.
- **Experimentell** (`qwen`, `copilot`, `grok`, Community-Lanes, Gemini `images=`): Flags sind nicht
  live verifiziert — `doctor deep` prüft sie gegen das `--help` jeder CLI auf deiner Maschine.

---

## Roadmap

Siehe [`CHANGELOG.md`](../../CHANGELOG.md) für die ausgelieferte Historie. Derzeit **in Erkundung
(nicht ausgeliefert)**: ein Verifikations-Modus mit **unabhängigem Orakel** (eine Lane einer anderen
Familie schreibt die Tests aus der *Spec*, blind für die Implementierung, sodass der Test den Bug fängt
statt ihn zu spiegeln) und feineres **limit-bewusstes Failover**. Große Inter-Agent-„Bus“-Ideen
(rekursives Spawnen, geteilter Zustand, Wire-Protokoll) sind ehrlich als *Richtung* positioniert, nie
als ausgeliefertes Protokoll verkauft — siehe [docs/ARCHITECTURE.md](../ARCHITECTURE.md).

---

## Referenzen

Die obigen Designentscheidungen sind keine Bauchgefühle — jede entspricht einem Befund aus der
Literatur. Jeder Eintrag wurde gegen seine Quelle geprüft (Autoren + Veranstaltungsort), denn ein Tool,
das „ehrliche anbieterübergreifende Verifikation“ verkauft, sollte seine eigenen Zitate richtig haben.

| Paper | ID | Was es hier untermauert |
|-------|----|--------------------|
| Du et al. — *Improving Factuality and Reasoning via Multiagent Debate* | [2305.14325](https://arxiv.org/abs/2305.14325) | `debate`: Modelle, die einander kritisieren, schlagen ein Modell allein |
| ReConcile — *Round-Table Conference Improves Reasoning* | [2309.13007](https://arxiv.org/abs/2309.13007) | `debate`-Konvergenz + konfidenzgewichteter Konsens |
| Mixture-of-Agents | [2406.04692](https://arxiv.org/abs/2406.04692) | geschichtete Aggregation über diverse Modelle (und ihre Grenzen) |
| Chain-of-Agents | [2406.02818](https://arxiv.org/abs/2406.02818) | rollenspezialisierte Multi-Agent-Pipelines |
| CriticGPT — *LLM Critics Help Catch LLM Bugs* | [2407.00215](https://arxiv.org/abs/2407.00215) | `review_diff` / `security_review`: ein LLM-Kritiker fängt Bugs, die Menschen übersehen |
| Perez et al. — *Discovering Language Model Behaviors* (Sycophancy) | [2212.09251](https://arxiv.org/abs/2212.09251) | warum ein Richter derselben Familie schwach ist → anbieterübergreifendes `jury` + Peer-Anonymisierung |
| Wynn, Satija & Hadfield — *Talk Isn't Always Cheap* | [2509.05396](https://arxiv.org/abs/2509.05396) | Fehlermodi der Debatte → fail-closed-Verdikte, begrenzte Runden |
| CONSENSAGENT — *Consensus via Sycophancy Mitigation* (Findings of ACL 2025) | [ACL 2025](https://aclanthology.org/2025.findings-acl.1141/) | Sycophancy im Konsens → „Sitz verdienen“ / anonymisierte Peers |
| Maryanskyy — *When Agents Disagree: The Selection Bottleneck* | [2603.20324](https://arxiv.org/abs/2603.20324) | `consensus`: **Auswahl > Synthese** (der deterministische Peer-Vote-Default) |

> **Eine Anmerkung zur Zitierhygiene.** *Talk Isn't Always Cheap* (2509.05396) ist von **Wynn, Satija
> & Hadfield** — ein populäres Rat-Framework zitiert es falsch als „Xiong et al.“. Wir prüfen
> Zuschreibungen doppelt, bevor wir sie wiederholen, und weisen darauf hin, weil Ehrlichkeit der ganze
> Pitch ist.

## Entwicklung

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration (cross-host) tests; no real CLI or network needed
```

## Lizenz

Apache 2.0

---

<div align="center">

<img src="../../assets/mark.gif" width="84" alt="cli-bridge">

<sub>ein Ufer · mit einem Rat verbunden</sub>

</div>
