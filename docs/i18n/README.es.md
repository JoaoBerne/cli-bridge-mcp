<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../assets/banner-dark.svg">
  <img src="../../assets/banner-light.svg" width="860" alt="Tú → cli-bridge → un consejo de CLIs de IA en paralelo → una sola revisión combinada">
</picture>

[English](../../README.md) · [Français](README.fr.md) · [简体中文](README.zh-CN.md) · **Español** · [Português (BR)](README.pt-BR.md) · [日本語](README.ja.md) · [Deutsch](README.de.md)

_El README en inglés es la versión canónica; esta traducción puede quedar desactualizada._

</div>

# cli-bridge

![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/cli-bridge-mcp)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**Tu asistente de IA, pero puede llamar a un amigo.**

`cli-bridge` es un servidor de [Model Context Protocol](https://modelcontextprotocol.io) que
**orquesta las CLIs de IA que ya instalaste y donde ya iniciaste sesión** — Claude Code, Codex,
Gemini CLI, opencode, … — desde el asistente con el que estés hablando. Sin claves de API, sin
extracción de tokens, un registro solo local, un tope de costo estricto, y escribe únicamente como
diffs en un worktree descartable. Esa parte es plomería indiscutible; esto es lo que desbloquea:

¿Atascado en un bug peliagudo? Haz que tu asistente le pregunte a GPT *y* a Gemini en paralelo y
compara. ¿Necesitas leer un archivo enorme con 1M de tokens? Pásaselo a Gemini. ¿Quieres una segunda
opinión barata? Dispárasela a un modelo gratuito. Una pregunta, todos los modelos, lado a lado — sin
salir de tu terminal.

```
You → Claude:  "ask the council whether this auth logic is safe"
Claude → cli-bridge → [ Gemini ] [ GPT ] [ Mistral ] [ Qwen ] … in parallel
            ← three independent reviews + a synthesis of where they agree & disagree
```

<div align="center">

<img src="../../assets/demo.gif" width="860" alt="Demo de security-review de cli-bridge: un bypass de autenticación commiteado es detectado de forma independiente por dos modelos, combinado en un único informe ordenado por severidad, $0 en lanes gratuitos">

_Ejecución real (a 2.5× de velocidad): un bypass de autenticación commiteado — `security-review`
reparte roles de OWASP entre modelos gratuitos en paralelo; dos modelos lo marcan como **blocker**
de forma independiente, y `usage` muestra los comprobantes._

</div>

> **Por qué es diferente, en una frase:** nunca tiene una clave de API y nunca extrae un token —
> maneja las CLIs oficiales que **ya instalaste y donde ya iniciaste sesión**. Un consejo de lanes
> gratuitos cuesta **$0.00** (los comprobantes están en `usage_report`); los lanes de pago solo se
> ejecutan dentro de un tope diario estricto que *tú* defines. Y cuando le pides que *haga* trabajo,
> edita en un worktree de git descartable y te devuelve un **diff** — tu repo en vivo nunca se toca.

> **Y la parte honesta:** "más modelos = mejor" es *frágil* — los modelos grandes comparten datos de
> entrenamiento, así que sus errores están correlacionados. Medimos nuestra propia afirmación central
> (`cli-bridge eval`, ya disponible, sin juez LLM): un consejo diverso **no** detectó más bugs que un
> solo modelo fuerte — redujo las falsas alarmas **~2×**. Publicamos los números de cualquier manera
> ([BENCHMARKS.md](../BENCHMARKS.md)), y el harness se incluye para que puedas ejecutarlo en *tus*
> CLIs.

---

## Por qué esta

Hay otros MCPs de "llamar a otros modelos". Esto es lo que hace que cli-bridge sea diferente:

- 🛡️ **A prueba de baneos por diseño.** Lanza la **CLI oficial** de cada modelo — exactamente como
  la ejecutarías a mano. Sin extracción de tokens OAuth, sin reutilización de claves de API, nada que
  haga que las cuentas queden marcadas. Cada CLI maneja su propia autenticación y facturación.
- 💸 **Costos por defecto con fuente, y luego *tú* los ajustas a tu plan.** De fábrica, `ask_all`
  arma un consejo gratuito y nunca toca la cuota de tu suscripción (Claude, GPT) ni créditos de pago
  a menos que lo pidas. Cada lane trae un tier obtenido de los planes publicados del proveedor
  ([docs/COSTS.md](../COSTS.md), con fecha) — **nunca detectado desde tu cuenta, y etiquetado como
  tal** — que tú sobrescribes según tus propias suscripciones
  (`CLI_BRIDGE_<LANE>_COST=free|limited|paid`); en un plan grande, márcalos todos como `free`, o
  define `CLI_BRIDGE_PROFILE=max`.
- 🔌 **Funciona desde cualquier host.** ¿Estás usando Claude Code? Oculta el lane de Claude (para no
  preguntarte a ti mismo) y expone el resto. ¿Usas Codex u opencode en su lugar? Lo mismo, detectado
  automáticamente desde el handshake de MCP.
- 🧩 **Agrega cualquier CLI — o tu propia API — sin hacer un fork.** Lanes integrados para Claude,
  GPT, Gemini, Mistral, Qwen, Copilot, Grok y opencode. Registra **tu propia CLI desde un archivo
  JSON**, o envuelve **tu propia API** lanzando `curl`. Cero código.
- 🧠 **Síntesis del consejo.** `ask_all` puede hacer que un modelo gratuito resuma en qué *coinciden*
  y en qué *discrepan* los demás — convierte tres opiniones en una sola decisión.
- 🔬 **Flujos de trabajo multimodelo.** `review_diff` y `security_review` reparten revisores
  **diversos por rol** entre el consejo, y luego combinan + deduplican en un único informe ordenado
  por severidad. `debate` hace que los modelos se critiquen y revisen entre sí durante rondas
  limitadas antes de que un juez concluya.
- ✍️ **Solo lectura por defecto, escrituras bajo demanda.** Activa `agent: build` para que cualquier
  lane capaz de hacerlo **edite archivos** de verdad — o elige un `model` específico por llamada,
  incluyendo un **hermano de tu propia familia** (pregúntale a Opus 4.6 desde Claude Code 4.8).
- 🪶 **Respuestas estilo subagente.** Un delegado trabaja en su propio contexto y devuelve un
  resumen; las salidas enormes se vuelcan a un archivo y solo regresa una vista previa, así el
  contexto de tu asistente se mantiene liviano.
- 🔁 **Fallback automático.** `ask_cascade` prueba los lanes del más barato al más fuerte y avanza
  cuando uno topa con cuota/auth/timeout — así un lane caído se degrada con elegancia en lugar de
  fallarte.
- 🩺 **Autoconsciente.** La telemetría local rastrea la salud de cada lane y lo pone en enfriamiento
  tras fallos repetidos de cuota/auth/timeout, para que `ask_all`/`ask_cascade` lo eviten al enrutar.
- 🎯 **Aprende tu stack.** Califica la respuesta de un lane del 1 al 5 con `rate_lane` y `ask_best`
  prefiere los modelos que de verdad ganan en cada tipo de tarea **en tu máquina** — una señal de
  calidad local guardada en sqlite que sobrevive a `/compact` y a los reinicios. No es una tabla de
  clasificación pública; son *tus* resultados.
- 🧱 **Endurecido.** Los timeouts matan todo el árbol de procesos (sin huérfanos quemando cuota), la
  cancelación del host mata al delegado, los secretos se redactan, los errores se clasifican
  (`quota` / `auth` / `timeout`) para que tu asistente sepa qué hacer a continuación. Funciona en
  macOS / Linux / Windows.
- 📐 **Medido, no afirmado.** "Más modelos encuentran más bugs" es *falsable*, así que cli-bridge
  incluye la prueba: `cli-bridge eval` enfrenta a un consejo contra un solo modelo fuerte +
  autoconsistencia con **igual presupuesto de llamadas** sobre un corpus de bugs de razonamiento
  sembrados, puntuado de forma determinista (sin juez LLM). Reporta media ± desv. estándar con una
  protección de "sin diferencia medible" y una tabla de victorias/derrotas por bug — y publica el
  resultado incluso cuando el consejo pierde. Ver
  [BENCHMARKS.md § Calidad](../BENCHMARKS.md#quality--does-a-council-actually-beat-one-strong-model).

### vs. otros MCPs multimodelo

| | cli-bridge | gateways con clave de API | puentes por reutilización de token |
|---|:---:|:---:|:---:|
| A prueba de baneos (lanza la CLI oficial) | ✅ | ➖ (tus claves) | ❌ (riesgo de ToS) |
| Sin claves de API que administrar | ✅ | ❌ | ✅ |
| Usa tus suscripciones existentes (consejo gratuito de $0.00) | ✅ | ❌ | ✅ |
| Tiers de costo por plan + tope diario estricto + enfriamiento | ✅ | ➖ | ❌ |
| Fallback automático (cascade) | ✅ | algunos | ❌ |
| Enrutamiento que **aprende de tus resultados** | ✅ | ❌ | ❌ |
| Agrega cualquier CLI / tu propia API, sin fork | ✅ | ➖ | ❌ |
| Se oculta a sí mismo del host que llama | ✅ | n/a | ➖ |
| Memoria de mesa redonda que sobrevive a un reinicio | ✅ | ➖ (en memoria) | ➖ |
| Escritura agéntica segura (worktree → diff) | ✅ | ➖ | ❌ |
| Incluye un eval de calidad determinista (consejo vs. individual) | ✅ | ❌ | ❌ |

---

## Inicio rápido

### 1. Instalar

```bash
# zero-install run (recommended)
uvx cli-bridge-mcp

# or install it
uv tool install cli-bridge-mcp     # or: pipx install cli-bridge-mcp
```

Solo obtienes un lane para una CLI que **ya instalaste y donde ya iniciaste sesión**. cli-bridge
detecta automáticamente lo que hay en tu `PATH`. Ejecuta la herramienta `doctor` cuando quieras para
ver qué está conectado (`doctor deep` incluso verifica en vivo cada inicio de sesión).

| Lane | CLI | Costo (típico) |
|------|-----|------|
| `ask_claude`   | [Claude Code](https://docs.claude.com/claude-code) | suscripción |
| `ask_gpt`      | [OpenAI Codex](https://github.com/openai/codex) | suscripción |
| `ask_gemini`   | Gemini CLI (o `agy` / Antigravity) | gratis / suscripción |
| `ask_mistral`  | Mistral Vibe | tier gratuito |
| `ask_qwen` ⚗️  | Qwen Code | clave de API con medición (tier OAuth gratuito cerrado en abr. 2026) |
| `ask_copilot` ⚗️ | GitHub Copilot CLI | suscripción (créditos por uso desde 2026-06) |
| `ask_grok` ⚗️  | xAI Grok CLI | suscripción (SuperGrok / X Premium+) |
| `ask_opencode` | gateway de [opencode](https://opencode.ai) (deepseek, qwen, glm, kimi…) | gratis por defecto; algunos modelos usan créditos |

⚗️ = experimental (flags aún no verificados en vivo — por favor reporta si algo se rompe).
La columna de costo = el *plan típico publicado* del proveedor a junio de 2026 ([docs/COSTS.md](../COSTS.md)
tiene límites, fechas de cierre y fuentes) — cli-bridge nunca detecta cuánto te cuesta *a ti* un
lane; declara tu propio plan con `CLI_BRIDGE_<LANE>_COST`.

### El consejo de $0 (sin ninguna suscripción)

¿Sin plan de pago, sin tarjeta? Aún puedes armar un consejo multimodelo real en ~5 minutos con
proveedores que tienen un **tier genuinamente gratuito y con corte estricto** (agotamiento = HTTP
429, una factura es estructuralmente imposible — verificado en junio de 2026, fuentes en
[docs/COSTS.md](../COSTS.md)):

```bash
# 1. Get free API keys (no card): console.groq.com · cloud.cerebras.ai ·
#    a GitHub PAT (models scope) · openrouter.ai/keys
export GROQ_API_KEY=... CEREBRAS_API_KEY=... GITHUB_MODELS_TOKEN=... OPENROUTER_API_KEY=...
# 2. Point cli-bridge at the ready-made lanes
export CLI_BRIDGE_LANES_FILE=/path/to/examples/free-apis.json
```

Eso es **Groq** (llama-3.3-70b, 1k req/día) + **Cerebras** (gpt-oss-120b) + **GitHub Models** (cada
cuenta de GitHub tiene acceso gratuito) + la amplitud de **OpenRouter `:free`** — cuatro voces
independientes para `ask_all`/`consensus`/`debate`, más los modelos gratuitos integrados de opencode
si está instalado. Salvedades: el tier gratuito de Gemini CLI **cierra el 2026-06-18**; los tiers
gratuitos cambian en cuestión de semanas — consulta [docs/COSTS.md](../COSTS.md) para ver qué era
cierto al momento de la verificación.

### 2. Regístralo con tu host

**Claude Code** — un solo comando:

```bash
claude mcp add cli-bridge -- uvx cli-bridge-mcp
```

<details>
<summary><b>Codex</b> (<code>~/.codex/config.toml</code>)</summary>

```toml
[mcp_servers.cli-bridge]
command = "uvx"
args = ["cli-bridge-mcp"]
```
</details>

<details>
<summary><b>opencode</b> / <b>Gemini CLI</b> / otros clientes MCP</summary>

Apunta la configuración MCP de tu cliente al comando `uvx cli-bridge-mcp` sobre stdio. Igual en todas
partes.
</details>

### 3. Úsalo

Simplemente habla con tu asistente:

> *"Pídele a Gemini una segunda opinión sobre esta función."*
> *"Haz que todo el consejo revise mi diff y sintetice dónde discrepan."* (→ `review_diff`)
> *"Haz que GPT piense a fondo sobre esta condición de carrera."* (→ `effort: high`)
> *"Ejecuta una revisión de seguridad sobre mis cambios en stage."* (→ `security_review`)
> *"Haz que los modelos debatan si necesitamos esta abstracción."* (→ `debate`)
> *"Pídele a gpt que implemente esta función."* (→ `agent: build`, edita archivos)
> *"Pídele a Opus 4.6 que revise mi razonamiento."* (modelo hermano, desde Claude Code)
> *"Elige el mejor lane para una revisión profunda — y recuerda que ese lo clavó."* (→ `ask_best` + `rate_lane`; la próxima vez enruta allí primero)

Los hosts que admiten prompts de MCP también exponen `review_diff`, `security_review`, `debate`,
`premortem`, `test_plan`, `apilookup` y `cost_setup` como comandos slash nativos.

---

## Herramientas

| Herramienta | Qué hace |
|------|--------------|
| `ask_<lane>` | Pregúntale a un modelo. Parámetros: `task`, opcional `model`, `effort`, `agent`, `cwd`, `timeout_s`, **`conversation`** (inicia/continúa un hilo de mesa redonda — ver abajo). |
| `ask_all` | Reparte la misma pregunta a todos los lanes gratuitos y no limitados en paralelo. `synthesize: true` agrega un resumen de coincidencias/discrepancias. `include_paid: true` para consultar también lanes limitados/de pago. |
| `ask_cascade` | Pregúntale a un modelo **con fallback automático** — prueba los lanes del más barato al más fuerte, saltando los que están en enfriamiento, avanzando ante cuota/auth/timeout. Devuelve el primer éxito + un rastro de lo que se intentó (tier de costo, latencia, por qué se saltó). |
| `ask_best` | Elige **un lane por modo** (`fast`/`cheap`/`deep`/`code`/`review`/`security`) según costo, salud, latencia medida **y tus propias puntuaciones de `rate_lane`**, y luego lo ejecuta con fallback. Para "solo usa el modelo correcto" — `ask_all` compara, `ask_cascade` es simplemente el más barato primero. |
| `rate_lane` | **Enseña al router.** Califica la respuesta de un lane del 1 al 5 para un tipo de tarea (`mode`) → `ask_best` luego prefiere los lanes que ganan ese modo **en tu máquina**. Guardado en sqlite (sobrevive a `/compact`/reinicio); un piso de dos calificaciones antes de que cualquier lane influya, para que el feedback sea honesto, no ruidoso. Cada respuesta de `ask_best` imprime la llamada exacta. |
| `route_plan` | Muestra el orden que `ask_cascade` probaría, dado tu perfil + los enfriamientos actuales (solo lectura, no ejecuta nada). Pasa `mode` para previsualizar `ask_best` — incluyendo la calificación acumulada de cada lane. |
| `ask_all_async` / `job_status` / `job_result` / `job_cancel` / `jobs_list` | Ejecuta un reparto como un **trabajo en segundo plano** que devuelve un id de trabajo en <1s, para que una ejecución lenta del consejo no tope con el plazo de llamada de herramienta del host. La cancelación mata los grupos de procesos de los delegados. |
| `review_diff` | Revisión de código multimodelo de un diff de git: los lanes revisan en paralelo con **enfoques diferentes** (corrección / seguridad / pruebas / mantenibilidad), cada uno devolviendo hallazgos en JSON; verificaciones previas deterministas (secretos, shell peligroso) los siembran; los hallazgos se **combinan por archivo/línea/título** con confianza basada en acuerdo (single/majority/consensus). `output_format: markdown` (por defecto) o `json`. Parámetros: `cwd`, `base` (por defecto HEAD), `diff`, `include_paid`, `timeout_s`. |
| `security_review` | Revisión **solo de seguridad** consciente de OWASP de un diff de git (inyección / autenticación y control de acceso / secretos y cripto / exposición de datos y SSRF) → hallazgos ordenados por severidad + una sección `residual_risk`. |
| `debate` | Varios modelos responden una pregunta, **ven las respuestas de los demás y revisan** a lo largo de rondas limitadas (por defecto 1, máx. 3), y luego un **juez independiente** (mantenido fuera del debate cuando hay 3+ lanes) escribe el consenso final + el desacuerdo restante. Endurecido a partir del uso en producción: `context_files` inyecta archivos clave en cada prompt de los debatientes (**grounding** — sin ello el consejo solo parafrasea tu brief), un **pase de verificación de hechos** (lane gratuito, activado por defecto) marca los comandos/etiquetas/versiones no verificables del veredicto, las afirmaciones llevan etiquetas de procedencia (`[brief]`/`[own-knowledge]`/`[verified]`), un brief delgado recibe una advertencia del linter, y `steelman: true` hace que un lane argumente *en contra* de un veredicto unánime antes de que el juez vuelva a concluir. `summary_only` descarta las posiciones completas (~60-80 % menos tokens); `dry_run` devuelve un manifiesto de datos previo al vuelo (qué archivos/caracteres van a qué proveedores) antes de enviar nada. Parámetros: `task`, `rounds`, `adversarial`, `context_files`, `fact_check`, `summary_only`, `allow_self_judge`, `steelman`, `dry_run`, `include_paid`, `cwd`, `timeout_s`. |
| `consensus` | El "consejo de LLMs" hecho mejor: cada lane responde a ciegas, luego **clasifica las respuestas anonimizadas** (sin favoritismo propio), los votos se agregan **de forma determinista** (conteo de Borda), y la **respuesta #1 clasificada por los pares se devuelve textualmente** — porque *seleccionar* la mejor respuesta gana a *mezclarlas* (arXiv 2603.20324: la síntesis pierde frente al baseline; la selección gana, g=3.86). `synthesize: true` opta por una mezcla de presidente (el modo más débil). Devuelve la respuesta final + una tabla de clasificación por voto de pares. `dry_run` devuelve un manifiesto de datos previo al vuelo (qué archivos/caracteres van a qué proveedores) sin lanzar nada. Admite grounding con `context_files` y `summary_only`. Parámetros: `task`, `context_files`, `synthesize`, `summary_only`, `dry_run`, `include_paid`, `cwd`, `timeout_s`. |
| `challenge` | Entrega una afirmación a **un lane externo** con un prompt de reevaluación crítica → una revisión escéptica independiente (con una salvaguarda de integridad — no fabricará desacuerdo). Pon a prueba tu propia conclusión antes de actuar. `lane` opcional. |
| `premortem` | Cada lane imagina que el plan **ya falló** y enumera los modos de fallo probables + mitigaciones; combinado en una lista de riesgos priorizada. Ejecútalo antes de construir. |
| `test_plan` | Deriva un **plan de pruebas** priorizado (comportamientos, casos límite, casos concretos) a partir de un diff de git o de una descripción. |
| `commit_msg` | Genera un mensaje de **Conventional Commit** a partir de tu diff en stage (recurre al árbol de trabajo). Solo lectura — emite texto, nunca commitea. `lane`, `cwd` opcionales. |
| `pr_describe` | Genera un **título + descripción de PR** (Summary / Changes / Testing) a partir del diff de la rama + el log de commits frente a una base (por defecto origin/main → main). Solo lectura. `base`, `lane`, `cwd` opcionales. |
| `ask_build_isolated` | **Modo de escritura seguro**: ejecuta un lane capaz de construir en un worktree de git descartable en HEAD y obtén el **diff** para revisar — tu repo real nunca se modifica. |
| `list_models` | Lista los modelos disponibles de un lane (parámetro `lane`) donde la CLI los expone; de lo contrario muestra el modelo por defecto resuelto + cómo elegir uno. (`list_<lane>_models` también existe para lanes con un comando de listado nativo.) |
| `conversations_list` / `conversation_show` | Lista los **hilos de mesa redonda** recientes (recupera un id tras un reinicio de contexto) / muestra la transcripción completa de un hilo, atribuida por lane. |
| `doctor` | Verificación de salud: CLIs instaladas, host detectado, postura de costo/cuota, enfriamientos, valores por defecto. `deep: true` sondea en vivo la autenticación de cada lane gratuito **y verifica los flags de cada lane contra su `--help`** — advierte si una CLI renombró/eliminó un flag del que cli-bridge depende (drift) antes de que el lane falle en silencio. |
| `usage_report` | Estadísticas solo locales: ejecuciones, éxito/latencia por lane, y tokens **estimados** (chars/4) + créditos (`CREDITS_PER_1K` por lane). `since`, `format=text\|json`. |
| `usage_budget` | Ejecuciones de hoy por lane frente a `CLI_BRIDGE_<LANE>_DAILY_LIMIT` + gasto estimado; marca los lanes que superan su límite. |
| `lane_stats` | Salud por lane: ejecuciones, fallos, fallos/timeouts consecutivos, enfriamiento activo. |
| `reset_lane_state` | Limpia los contadores de enfriamiento/fallos de un lane (tras volver a iniciar sesión o reiniciar la cuota). |
| `setup` | Lista los lanes instalados con su costo de plan típico *con fuente* (free/limited/paid — nunca detectado desde tu cuenta), pregunta cuáles pagas realmente, y **recomienda un perfil + tope diario** para confirmar — luego guía al usuario por el proceso. |

También hay una **CLI para humanos** — el mismo motor desde tu terminal o CI:
`cli-bridge init` (detecta CLIs + imprime la conexión de MCP), `doctor`, `ask <lane> <task>`, `ask-all`,
`ask-best --mode`, `review-diff --base origin/main --json`, `bench --lane gemini --prompt … `
(latencia p50/p95/p99), `usage`, `budget`, `jobs`, `setup --write`. Ver
`examples/github-action-pr-review.yml` para una GitHub Action de revisión de PR (runner
autoalojado).

**Solo lectura por defecto; escrituras opcionales.** Un delegado normalmente analiza y responde — tu
host aplica cualquier edición. Pasa `agent: "build"` para dejar que **edite archivos directamente**
(p. ej. *"pídele a gpt que implemente esta función"*): claude → `--permission-mode acceptEdits`, gpt
→ `--sandbox workspace-write`, mistral → `--agent accept-edits`, gemini → `--yolo` (o `agy`
`--dangerously-skip-permissions`), opencode → `--agent build`. Los lanes capaces de construir se
anotan como no-solo-lectura, y una ejecución `build` nunca se sirve desde caché.

**Elige un modelo por llamada** con `model` (p. ej. `model: "claude-opus-4-6"`). Desde dentro de un
host incluso puedes consultar un **modelo hermano de tu propia familia** — `ask_<your-host>` aparece
como una herramienta separada que requiere un `model` explícito, así que desde Claude Code puedes
preguntarle a Opus 4.6 mientras ejecutas 4.8. (El `agy` de Antigravity no tiene flag de modelo por
llamada — usa el que seleccionen sus propios ajustes.)

**Conversaciones de mesa redonda.** Pasa `conversation: "new"` a cualquier `ask_<lane>` para iniciar
un hilo de varios turnos; reutiliza el id devuelto — **incluso en un lane diferente** — para
continuar. Cada lane ve la transcripción compartida con tus propios turnos marcados como "You" y los
demás nombrados, así un consejo puede construir sobre lo dicho por otros en lugar de empezar en frío
cada vez. La transcripción se guarda localmente (sqlite), así que un hilo **sobrevive al reinicio de
contexto del host (`/compact`) y a un reinicio del servidor** — recupera uno con
`conversations_list`, léelo con `conversation_show`. Una ventana deslizante
(`CLI_BRIDGE_CONVO_MAX_CHARS`, por defecto 32000) conserva los turnos más nuevos y descarta los más
viejos, así el costo por turno se mantiene acotado sin importar cuánto dure el hilo.

Para opencode, un `model` vacío le pide a `opencode models` la lista actual de `opencode/*-free` y usa
una (el tier de $0 con límite de tasa), elegida por patrón + ordenamiento — nunca un nombre fijado,
así un modelo gratuito retirado se reemplaza automáticamente. Es **seguro en costos**: un modelo Zen
`opencode/*` sin más factura por token (costo de API) y `opencode-go/*` gasta créditos prepagados, así
que el valor por defecto nunca selecciona en silencio un modelo de pago — pásalos explícitamente
cuando los quieras. Si la búsqueda falla, recurre a una semilla gratuita; define
`CLI_BRIDGE_OPENCODE_MODEL` para fijar tu propio valor por defecto.

`ask_all` mantiene cortas las llamadas por lane (45s por defecto, 60s máx.) para que el host de MCP
reciba una respuesta antes de su propio plazo de llamada de herramienta. Para una respuesta
lenta/profunda, llama a ese lane directamente con un `timeout_s` más largo.

---

## Configuración

Todo son variables de entorno — sin editar código. Ajústalo a **tus** suscripciones:

| Variable | Efecto |
|----------|--------|
| `CLI_BRIDGE_<LANE>_COST` | `free`, `limited` o `paid`. `free` se une a `ask_all`; `limited` es sensible a la cuota y el reparto amplio lo salta; `paid` gasta dinero/créditos y se salta por defecto. |
| `CLI_BRIDGE_<LANE>_ENABLED` | `false` para ocultar un lane aunque su CLI esté instalada. |
| `CLI_BRIDGE_<LANE>_BIN` | Apunta un lane a un binario diferente (p. ej. `CLI_BRIDGE_GEMINI_BIN=agy`). |
| `CLI_BRIDGE_<LANE>_MODEL` | Modelo por defecto para un lane cuando quien llama no pasa uno. |
| `CLI_BRIDGE_PROFILE` | `saver`, `balanced` o `max`. `max` incluye los lanes limitados/de pago en `ask_all` a menos que quien llama sobrescriba `include_paid`. |
| `CLI_BRIDGE_HOST` | Fuerza la identidad del host (qué lane ocultar). Normalmente se detecta automáticamente. |
| `CLI_BRIDGE_LANES_FILE` | Ruta a un archivo JSON que agrega **tus propias** CLIs/APIs como lanes. |
| `CLI_BRIDGE_DISABLED_TOOLS` | Nombres de herramientas separados por comas para ocultar del listado (p. ej. `debate,premortem,test_plan`) — recorta el contexto de esquema que cada host paga por petición. `doctor`/`setup` no se pueden ocultar. |
| `CLI_BRIDGE_ENABLED_TOOLS` | Lista de permitidos para un **modo ligero** de una sola variable: cuando se define, solo se exponen estas herramientas (+ `doctor`/`setup`) (p. ej. `ask_best,ask_all,review_diff`). |
| `CLI_BRIDGE_<LANE>_PRIORITY` | Menor se ejecuta antes en `ask_cascade` (por defecto 50). Fija tu orden preferido. |
| `CLI_BRIDGE_INLINE_MAX_CHARS` | Por encima de esto, una respuesta se vuelca a un archivo en lugar de inundar el contexto (por defecto 12000). |
| `CLI_BRIDGE_TERSE` | `off` / `lite` (por defecto) / `full` / `ultra`. Antepone un preámbulo compacto de estilo de respuesta a los prompts de los delegados (en inglés, razona a fondo internamente, responde de forma concisa, código/JSON intactos) para recortar tanto tu contexto como los tokens de salida del delegado. Nunca se aplica a las herramientas de flujo de trabajo estructuradas. |
| `CLI_BRIDGE_TERSE_MIN_CHARS` | Omite el preámbulo conciso para tareas más cortas que esta cantidad de caracteres (por defecto `0` = nunca omitir). Las tareas diminutas no pueden compensar el costo fijo del preámbulo. |
| `CLI_BRIDGE_GUARD` | `off` / `warn` (por defecto) / `strict`. Escanea la **salida del delegado** en busca de inyección de prompts / envenenamiento de herramientas; `warn` antepone un banner, `strict` retiene el cuerpo. Se ejecuta después de la redacción de secretos. |
| `CLI_BRIDGE_MOCK` | `1` = ejecución en seco: los lanes reportan como instalados y devuelven una respuesta enlatada sin lanzar ninguna CLI. Prueba toda la herramienta con **cero CLIs instaladas**. |
| `CLI_BRIDGE_RETRIES` | Reintentos ante un fallo TRANSITORIO (por defecto 1). Hace que una CLI inestable funcione al primer intento; cuota/auth/no-encontrado/timeout nunca se reintentan. |
| `CLI_BRIDGE_TRACE_DIR` | Si se define, cada delegación escribe aquí un rastro JSON redactado (argv, tiempos, salida) — debug / auditoría reproducible. Desactivado por defecto. |
| `CLI_BRIDGE_MAX_PARALLEL` | Tope de lanzamientos simultáneos de delegados en `ask_all` (por defecto 6). Evita que un consejo amplio (muchos lanes personalizados) deje sin memoria una máquina pequeña o reviente la cuota. |
| `CLI_BRIDGE_DAILY_CREDIT_CAP` | Techo estricto del gasto de pago *estimado* por día UTC. >0 rechaza un lane de pago una vez que la estimación de hoy lo alcanza — hace que "seguro en costos" sea exigible, no solo reportado. Los lanes gratuitos nunca se restringen. |
| `CLI_BRIDGE_ALLOW_LANES` | Lista de permitidos, p. ej. `gemini,gpt`. Vacío = todos. Configuraciones bloqueadas / de equipo: solo se exponen estos lanes. |
| `CLI_BRIDGE_DISABLE_BUILD` | `1` fuerza a cada delegado a solo lectura (plan) aunque quien llama pida `agent: build`. Para máquinas compartidas. |
| `CLI_BRIDGE_OVERFLOW_MAX_FILES` | Tope del número de archivos en el directorio de desbordamiento (por defecto 200); los más viejos por encima se podan para que `/tmp` no crezca sin límite. |
| `CLI_BRIDGE_CONFIG_FILE` | Ruta a un JSON de configuración (por defecto `~/.config/cli-bridge/config.json`). Una alternativa más amigable a las variables de entorno — **el entorno siempre gana**. Ver abajo. |
| `CLI_BRIDGE_CACHE_TTL_S` | `0` = desactivado (por defecto). Cuando `>0`, una llamada idéntica dentro de esta cantidad de segundos devuelve la respuesta en caché en lugar de relanzar la CLI (ahorra cuota/créditos en repeticiones; las ejecuciones build nunca se cachean). |
| `CLI_BRIDGE_<LANE>_CREDITS_PER_1K` | Créditos por cada 1k tokens para un lane, usado por `usage_report`/`usage_budget` para **estimar** el gasto (chars/4). |
| `CLI_BRIDGE_<LANE>_DAILY_LIMIT` | Máximo de ejecuciones/día para un lane; `usage_budget` lo marca cuando se supera. |
| `CLI_BRIDGE_<LANE>_MIN_INTERVAL_S` | Ritmo de lanzamiento anti-ráfaga: segundos mínimos entre lanzamientos de este lane (por defecto `0` = desactivado). Defínelo (p. ej. `2`) cuando un tier gratuito limita la tasa ante llamadas consecutivas — las ráfagas del mismo lane se espacian de forma uniforme, los demás lanes siguen en paralelo. `lane_stats` da pistas cuando un lane muestra el patrón de límite de tasa. |
| `CLI_BRIDGE_KEEP_WORKTREES` | Conserva los worktrees de `ask_build_isolated` en lugar de descartarlos (para inspección). |
| `CLI_BRIDGE_REVIEW_TIMEOUT_S` | Timeout por revisor para `review_diff` / `security_review` (por defecto 180; son deliberadamente más pesados que `ask_all`). |
| `CLI_BRIDGE_OVERFLOW_TTL_H` | Horas antes de que un archivo de desbordamiento volcado se pode (por defecto 24). |
| `CLI_BRIDGE_TELEMETRY` | `off` para desactivar el registro local de ejecuciones / seguimiento de enfriamiento (por defecto activado, solo local a la máquina). |
| `CLI_BRIDGE_STATE_DB` | Ruta a la base de datos sqlite de estado local (por defecto `~/.local/share/cli-bridge/state.sqlite`). |
| `CLI_BRIDGE_STORE_TRANSCRIPTS` | `true` para conservar una vista previa más larga de la tarea en la telemetría (por defecto: solo hash + vista previa de 60 caracteres). |
| `CLI_BRIDGE_LOG` / `_LOG_FILE` | `debug`/`info` para registrar qué se ejecutó y dónde (por defecto: silencioso). |

### Archivo de configuración (en lugar de un muro de variables de entorno)

¿Prefieres un archivo? Coloca `~/.config/cli-bridge/config.json` (o apunta `CLI_BRIDGE_CONFIG_FILE` a
uno). Rellena cualquier variable de entorno que no hayas definido — **el entorno siempre gana**, y los
valores por defecto siguen funcionando sin ningún archivo:

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

### Agrega tu propia CLI (sin fork)

`my-lanes.json`, luego `CLI_BRIDGE_LANES_FILE=/path/to/my-lanes.json`:

```json
[
  {
    "key": "aider", "display": "Aider", "bin": "aider",
    "ask": ["--message", "{task}"], "model_flag": "--model",
    "client_ids": ["aider"], "note": "Aider one-shot via --message."
  }
]
```

Ahora tienes una herramienta `ask_aider`. (Un lane personalizado con una key integrada, p. ej.
`grok`, *sobrescribe* al integrado — útil cuando los flags de tu instalación difieren.)

**El ecosistema más amplio, listo para conectar:** `examples/community-lanes.json` incluye lanes de
mejor esfuerzo para **Aider, Goose, Plandex, Amp, Crush, Amazon Q Developer CLI y Droid (Factory)** —
todos marcados como experimentales y `limited` (mantenidos fuera del reparto amplio hasta que *tú*
declares cuánto te cuestan), y todos cubiertos por la verificación de flag-drift de `doctor deep`, que
valida cada lane contra el propio `--help` de la CLI en *tu* máquina antes de que algo se rompa en
silencio. Claude Code, Codex, Gemini + Antigravity (`agy`), opencode, Qwen Code, Copilot y Grok ya
están integrados. Cualquier otra cosa (Cline, OpenHands, Continue, Roo/Kilo Code, Kimi K2 CLI, …) está
a los mismos 3 renglones de JSON de distancia — y cualquiera de estas CLIs que hable MCP puede sentarse
también del *otro* lado, ejecutando cli-bridge como su servidor.

### Trae tu propia API (sin necesidad de CLI)

Envuelve cualquier endpoint compatible con OpenAI lanzando `curl`. Tu clave permanece en una variable
de entorno, nunca en el archivo. `{task_json}` es el prompt, escapado en JSON:

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

El par `--variable %MY_API_KEY` + `--expand-header` (curl ≥ 8.3) importa la clave *dentro* de curl —
nunca aparece en la lista de procesos. `doctor` advierte si un lane personalizado expande un secreto
`${ENV}` en el argv en su lugar.

(Ver `examples/` para ambos, listos para copiar.)

---

## Cómo funciona

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
              hides the host's own lane · only shows installed, enabled CLIs
              kills the whole process tree on timeout / cancellation
              redacts secrets · classifies errors · spills huge output to a file
```

Sin llamadas de red propias. Sin claves almacenadas. Ejecuta los mismos binarios en los que ya confías,
en tu directorio de trabajo, y te devuelve la respuesta.

### Funciona también en hosts MCP de IDE

cli-bridge es MCP plano sobre stdio, así que cualquier host con capacidad MCP funciona — no solo las
CLIs de terminal. Apunta Cursor / VS Code (Cline, Continue) / Zed al **mismo comando** (`uvx
cli-bridge-mcp`, o `<python> -m cli_bridge`). El propio lane del host se oculta automáticamente; todo
lo demás es idéntico.

### Limitaciones conocidas (lista honesta)

- **El ser a prueba de baneos depende de los ToS de cada proveedor.** cli-bridge solo ejecuta la CLI
  oficial que ejecutarías a mano — pero el uso no interactivo/automatizado no está *garantizado* como
  autorizado y puede cambiar. Usa tus propias cuentas dentro de sus términos; trata "a prueba de
  baneos" como "sin extracción de tokens/claves", no como una garantía general.
- **Los trabajos asíncronos son en proceso.** Un reinicio del servidor marca los trabajos en
  ejecución como `interrupted` — sin reanudación entre reinicios en v1.
- **La protección de inyección es heurística.** Captura patrones de alta señal, no todo; en modo
  `warn` el texto aún llega al host (trata la salida del delegado como datos).
- **Las cifras de tokens/créditos son estimaciones** (chars/4 + tu `CREDITS_PER_1K`), nunca exactas.
- **Lanes de BYO-API (curl):** una clave `${ENV}` se sustituye en el argv, así que puede aparecer en
  la lista de procesos de esta máquina mientras la llamada se ejecuta (nunca se registra — los rastros
  la redactan). Prefiere la propia CLI de un proveedor cuando sea posible; para curl, un archivo de
  cabecera (`curl -H @file`) evita la exposición en el argv.
- **Lanes experimentales** (`qwen`, `copilot`, `grok`): los flags no están verificados en vivo —
  reporta si algo se rompe.
- **Los tiers de costo son valores por defecto con fuente, no detección** — datos de planes de
  proveedores con fecha de junio de 2026 ([docs/COSTS.md](../COSTS.md)); los planes/cuotas cambian,
  `doctor` advierte cuando la instantánea está desactualizada.
- **Host en sandbox:** si tu host ejecuta el servidor en un sandbox estricto (FS de solo lectura / sin
  red), las CLIs lanzadas lo heredan y pueden fallar al intentar alcanzar a sus proveedores.
  cli-bridge expone esto como un error `auth`/`failed` en lugar de quedarse colgado.

---

## Desarrollo

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration (cross-host) tests
```

## Licencia

MIT

---

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../assets/mark-dark.svg">
  <img src="../../assets/mark-light.svg" width="84" alt="cli-bridge">
</picture>

<sub>un lado · conectado a un consejo</sub>

</div>
