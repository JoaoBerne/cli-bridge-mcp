<div align="center">

<img src="../../assets/banner.gif" width="860" alt="cli-bridge — tu asistente toma prestados los poderes de todas las CLI de IA que ya tienes: lecturas de contexto enorme, visión, builds en paralelo, verificaciones entre proveedores">

[English](../../README.md) · [Français](README.fr.md) · [简体中文](README.zh-CN.md) · **Español** · [Português (BR)](README.pt-BR.md) · [日本語](README.ja.md) · [Deutsch](README.de.md)

</div>

_El README en inglés es la fuente autoritativa; esta traducción puede ir por detrás. Revisión de la comunidad bienvenida._

# cli-bridge

![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![status](https://img.shields.io/badge/status-pre--public%20(not%20on%20PyPI)-lightgrey)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**Tu asistente, con los poderes de todas las CLI que ya tienes.**

> **Sin claves API · sin extracción de tokens · sin Node · sin demonio · solo stdlib + `mcp`.**

El asistente con el que hablas no puede leer un repo de 2 M de tokens de una vez, no puede ver una
captura de pantalla, no puede entregarte una imagen generada, y no puede revisar su propio trabajo sin
sesgo. Las otras CLI de IA que **ya instalaste y donde ya iniciaste sesión** — Claude Code, Codex,
Gemini, opencode, además de modelos locales vía Ollama — hacen cada una algo que la tuya no. `cli-bridge`
es un servidor [Model Context Protocol](https://modelcontextprotocol.io) que permite a tu asistente
**tomarlas prestadas**: lanza la CLI oficial como subproceso (exactamente como la ejecutarías a mano —
sin claves, sin extracción de tokens) y te devuelve el resultado.

---

## La demo de 10 segundos

Estás en Claude. Claude no puede darte una imagen. Codex sí — escribe el código que genera una y lo
ejecuta. Así que pídeselo:

```
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png — write a script that renders it, then run it", zone="assets")
→ Codex writes assets/card.png · you get the path back, never a binary blob (artifact-return)
```

Tu asistente acaba de ganar una capacidad que no tiene. Esa es toda la idea — ahora escálalo a
lecturas de contexto gigante, visión, trabajo pesado en paralelo, y verificación independiente entre
proveedores.

_(Codex genera la imagen con **`gpt-image-2`**, un verdadero modelo de texto-a-imagen integrado en el
CLI — descontado de tu plan ChatGPT, sin clave de API aparte (la generación de imágenes requiere un
plan **de pago**; no está en el nivel gratuito). El resultado vuelve como una **ruta**, no como un
blob, porque un binario viaja por artifact-return, no por el canal de texto. Una lane build también
puede *renderizar* gráficos, diagramas o SVG escribiendo código, cuando encaja mejor.)_

### …y delega trabajo real, de forma segura

`cli-bridge build <lane> "<tarea>"` entrega el trabajo a otro modelo que corre en un **worktree git
desechable**, y luego te devuelve un **diff** — tu repo nunca se toca hasta que tú mismo lo apliques.

<p align="center">
<img src="../../assets/demo-borrow.gif" width="860" alt="cli-bridge build: opencode añade una función en un worktree desechable y devuelve un diff revisable; el repo real queda limpio">
</p>

---

## Cómo pensarlo (el modelo mental)

cli-bridge no es una función, son **cuatro palancas**. Entiéndelas y cada herramienta de abajo encaja:

1. **Tomar prestado** — alcanzar una capacidad que tu asistente no tiene (visión, ventana de contexto
   de 1 M de tokens, un archivo que genera un agente de código, un modelo simplemente mejor en *esto*).
2. **Repartir** — cuando una suscripción llega a su límite, sigue en otra lane que ya pagas.
3. **Descargar** — repartir trabajo pesado y paralelizable en lanes gratis/baratas mientras codeas en
   otra cosa.
4. **Verificar** — que una *familia de proveedor diferente* revise el trabajo, porque un modelo no
   detecta sus propios puntos ciegos. Es lo único que una herramienta de un solo proveedor no puede
   hacer estructuralmente.

---

## Qué desbloquea

Cada bloque: una frase de *cuándo recurrir a ello*, la llamada exacta, y *qué obtienes de vuelta*.

### Toma prestadas capacidades que tu asistente no tiene
Cada CLI tiene un superpoder distinto, y cada una corre de forma no interactiva — así que cli-bridge
puede lanzarla. Toma prestada la que le falta a tu host (debe estar instalada + con sesión iniciada):

| Superpoder | Qué CLI lo tiene | Tómalo prestado cuando |
|------------|------------------|----------------|
| **Imágenes** | Codex (`gpt-image-2`, **sin clave API** — plan ChatGPT de pago, no el gratuito) | tu host no sabe dibujar |
| **Contexto enorme** | Gemini (ventana de 1 M de tokens) | un archivo/repo no cabe en el contexto de tu host |
| **Conocimiento fresco** | Gemini (grounding con Google Search) · Grok (web/X en vivo) ⚗️ | vencer una fecha de corte: *«¿cuál es la API actual de `<lib>`?»* |
| **Visión** | Gemini (`images=[…]`) ⚗️ | analizar una captura o un diagrama |
| **Una segunda opinión gratis** | Gemini (nivel diario gratis) · opencode · Ollama (local, 0 $) | un contraste a 0 $ |
| **Archivos generados** | cualquier lane de build → artifact-return | recibir un gráfico / PDF / diagrama **por ruta** |
| **Vídeo** ⚗️ | Gemini (Veo) · Grok (Imagine) — *si tu CLI instalada lo expone* | necesitas un clip generado |

```
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png", zone="assets")   # Codex image → file by path, no API key (paid ChatGPT plan)
ask_gemini(task="find the bug across ./src — read the files you need", cwd="path/to/repo")         # 1M-token context
ask_gemini(task="what's the current recommended API for <lib>? check the latest docs")            # fresh knowledge (Search grounding)
ask_gemini(task="what's wrong in this UI?", images=["screenshot.png"])                             # vision (experimental)
```

⚗️ = experimental / depende de la versión actual de la CLI instalada (p. ej. Grok Build está en beta) — verifica con `doctor deep`.

### Nunca dejes de trabajar cuando llegas a un límite
Cuando tu suscripción principal se satura a media tarea. `ask_cascade` cae a otra lane que ya pagas,
saltando cualquier lane en pausa tras un error de cuota/auth/timeout.

```
ask_cascade(task="finish wiring this endpoint")   # cheapest→strongest; a cooled-down lane is skipped
ask_best(task="…", mode="deep")                   # let the router pick the most suitable available lane
```

### Descarga el trabajo pesado — en paralelo, y barato
Cuando el trabajo es laborioso pero no difícil (refactors, migraciones, cobertura de tests).
Reparte, con journaling para que un reinicio del servidor retome en vez de empezar de cero; delega un
build y sigue trabajando.

```
batch_run(tasks=[...], dry_run=true)                       # cost envelope first — nothing is spawned
batch_run(tasks=[...], max_calls=20, max_credits=2.0)      # then run under a hard budget (resumable)
ask_build(lane="opencode", task="add the landing page", zone="frontend", mode="direct", async=true)   # delegate, keep building
job_tail(job_id="…")  ·  build_steer(job_id="…", instruction="use Tailwind, not inline CSS")
```

### Rompe la auto-confirmación — el problema de 2026 que un solo proveedor no puede resolver
Cuando necesitas *confiar* en un resultado. Un modelo que revisa su propio trabajo (o el de un
hermano) solo confirma sus propios puntos ciegos. cli-bridge pone una **familia de modelo distinta**
en el asiento del revisor.

```
workflow(preset="jury", task="is this migration safe?", author_lane="gpt")            # cross-family vote, fail-closed
workflow(preset="verify_repair", task="add retry with backoff",
         builder_lane="gpt", verifier_lane="gemini")                                   # A builds, B reviews, loop to green
security_review(base="origin/main")   ·   review_diff(base="origin/main")              # OWASP, severity-ranked
```

### Obtén una segunda opinión de verdad
Cuando ya llegaste a una conclusión y quieres ponerla a prueba, o varios modelos en paralelo.

```
challenge(task="I'm dropping the cache layer — here's why: …")                         # one skeptic attacks it
consensus(task="which migration strategy is safest here?")                             # N answer, peer-rank the best
workflow(preset="fanout_compare", task="fix this failing test", lanes=["gpt","gemini","opencode"])
```

---

## La caja de herramientas completa

Todas las herramientas, agrupadas por intención. Ejecuta `CLI_BRIDGE_LEAN=1` para una superficie
curada de ~12 herramientas; oculta/muestra cualquiera con `CLI_BRIDGE_DISABLED_TOOLS` /
`CLI_BRIDGE_ENABLED_TOOLS`.

### Consultar (solo lectura)
| Herramienta | Qué hace | Recurre a ella cuando |
|------|--------------|-------------------|
| `ask_<lane>` | Preguntar a una CLI concreta — `ask_claude`, `ask_gpt` (Codex), `ask_gemini`, `ask_mistral`, `ask_opencode`, `ask_ollama`, y `ask_qwen`/`ask_grok`/`ask_copilot` si están instaladas. Admite `role="reviewer\|security\|planner\|devil"`, `conversation` (memoria de mesa redonda), e `images=[…]` en Gemini. | Quieres la fuerza, la persona o la modalidad de un modelo concreto. |
| `ask_all` | La misma pregunta a cada lane *gratis* en paralelo; devuelve cada respuesta **más una puntuación de desacuerdo**. `synthesize: true` añade un resumen de acuerdo/desacuerdo. | Quieres amplitud rápida + señal de dónde divergen los modelos (= incertidumbre). |
| `ask_cascade` | Prueba lanes en orden determinista, se detiene en la primera buena respuesta, salta lanes en pausa; escalado de confianza opcional. | Quieres resiliencia: una lane con tope/en fallo se salta automáticamente. |
| `ask_best` | Un router elige la lane más adecuada según `mode` (`fast/cheap/deep/code/review/security`) + tus puntuaciones `rate_lane`. | No quieres elegir lane a mano. |
| `ask_all_async` + `job_status`/`job_result`/`job_cancel`/`jobs_list` | Lanza `ask_all` como trabajo en segundo plano (id en <1 s). | El fan-out es lento y quieres seguir trabajando. |
| `consensus` | N lanes responden, luego los pares clasifican para **seleccionar** la mejor (la selección gana a la síntesis). | Una única respuesta defendible importa más que una mezcla. |
| `challenge` | Una lane hace de escéptico contra una conclusión que aportas. | Quieres que ataquen tu razonamiento antes de comprometerte. |
| `conversations_list` / `conversation_show` | Listar / leer hilos de mesa redonda persistentes (sobreviven a `/compact` y reinicios). | Quieres recuperar o leer un hilo multi-modelo. |

### Construir (escritura opt-in)
| Herramienta | Qué hace | Recurre a ella cuando |
|------|--------------|-------------------|
| `ask_build` | Delega un build real. `mode=isolated` (por defecto) edita un worktree desechable → **diff**; `mode=direct` escribe en una `zone` declarada (cerrojo por zona + comprobación de violación de zona tras el turno). `async=true` lo lanza como job dirigible. Las salidas no textuales vuelven **por ruta** (artifact-return). | Quieres trabajo *hecho*, no solo sugerido — con revisión o sin manos. |
| `ask_build_isolated` | Alias cómodo de `ask_build` con `mode=isolated` — siempre devuelve un diff, nunca toca tu árbol. | Quieres la ruta segura (diff) por su nombre, sin fijar `mode`. |
| `job_tail` | Transmite el log de progreso de un build en curso (por offset de byte). | Quieres ver trabajar a un delegado. |
| `build_steer` | Encola una instrucción de dirección para el siguiente turno, o `interrupt=true` corta el turno actual (archivos conservados). | Necesitas corregir el rumbo a mitad de build sin reiniciar. |

Los builds asíncronos corren contra una **Definition-of-Done** ejecutable (`dod_cmd`) — la afirmación
de éxito del delegado se *prueba*, no se cree.

### Revisar y verificar
| Herramienta | Qué hace | Recurre a ella cuando |
|------|--------------|-------------------|
| `review_diff` | Revisión estructurada de un diff → findings (severidad, archivo, justificación), fusionados de forma determinista entre lanes con confianza single/majority/consensus. | Antes de que aterrice un cambio. |
| `security_review` | Pase de seguridad orientado a OWASP, clasificado por severidad + una sección `residual_risk`. | El cambio toca auth, manejo de entradas, secretos. |
| `debate` | Los modelos se critican durante rondas acotadas, terminando con un pie `VOTE` + parada anticipada por convergencia; un juez independiente concluye. | Una decisión genuinamente disputada. |
| `premortem` / `test_plan` | Análisis de modos de fallo de un plan / un plan de test priorizado desde un diff o descripción. | Antes de escribir código. |
| `commit_msg` / `pr_describe` | Un mensaje Conventional-Commit desde tu diff en stage / un título+cuerpo de PR desde la rama. Solo lectura — emite texto. | Estás por commitear o abrir una PR. |
| `workflow(preset=…)` | Pipelines con nombre: `jury` (voto entre familias k-de-N, fail-closed), `verify_repair` (bucle build→revisión→reparación entre modelos), `refine_plan`, `fanout_compare`, `council_review`, `map_review`, `research_verify`. | Quieres un patrón multi-paso probado en una llamada. |

### Orquestar
| Herramienta | Qué hace | Recurre a ella cuando |
|------|--------------|-------------------|
| `batch_run` | Fan-out durable y **con journaling** sobre muchas tareas. `dry_run=true` devuelve un sobre de coste (nada se lanza); `max_calls`/`max_credits` topan el gasto; `resume_id` reproduce las tareas terminadas y solo corre el resto tras un reinicio. | Trabajo en masa que quieres acotado y a prueba de crashes. |

### Operar
| Herramienta | Qué hace | Recurre a ella cuando |
|------|--------------|-------------------|
| `usage_report` / `usage_budget` | Contabilidad estimada de tokens/créditos (chars/4 — honestamente etiquetada como estimación) + presupuesto frente a un tope diario. | Quieres ver la factura / poner un tope. |
| `rate_lane` / `route_plan` | Puntuar una lane de 1 a 5 para un modo para que `ask_best` aprenda tu stack / previsualizar el orden que probaría una cascada. | Quieres que el router mejore con el tiempo. |
| `lane_stats` / `reset_lane_state` | Salud por lane, pausas, y la señal de jurado «ganarse el puesto» / reiniciar los contadores de una lane. | Una lane se porta mal, o quieres el informe de puestos. |
| `set_lane_cost` | Registrar lo que una lane *te* cuesta («Codex es gratis en mi plan») — persistido, sin necesidad de `setup`. | Le sueltas un dato de precio de pasada. |
| `doctor` / `setup` | Detectar las CLI instaladas + rutas resueltas; `doctor deep` valida cada lane contra su propio `--help` en tu máquina. | Primer arranque, o cuando una lane se rompe. |
| `list_models` / `list_<lane>_models` | Listar los modelos de una lane donde la CLI los expone. | Quieres elegir un modelo concreto. |

También hay una **CLI humana** (`cli-bridge doctor|ask|ask-all|ask-best|build|review-diff|eval|…`) — el
mismo motor desde tu terminal o CI (`--json` en todo). `cli-bridge build <lane> "<tarea>"` delega un
build real a una lane en un worktree desechable e imprime el **diff** — tu repo nunca se toca.

---

## Qué obtienes realmente al combinarlas

Un solo asistente cuyo techo en **cada eje es lo mejor del ecosistema** — no la herramienta que abriste
esta mañana: codear con el modelo más fuerte, leer 1–2 M de tokens cuando el tuyo se queda corto,
responder con conocimiento fresco más allá de una fecha de corte, generar imágenes/vídeo, ver
capturas, y caer a una lane gratis/local cuando llegas al tope — repartido entre las suscripciones que
ya pagas.

La propiedad emergente **que ninguna CLI por sí sola tiene: control real entre proveedores** — un
*proveedor distinto* en el asiento del revisor. Los subagentes de la misma familia (los de Claude Code,
los de Grok) solo pueden auto-confirmarse.

La costura honesta: esto une **capacidades, no mente** — spawns sin estado (sin memoria compartida),
latencia/coste de spawn, calidad desigual, y el host siempre lleva el timón. Es **orquestación, no
fusión**: diriges a especialistas, no obtienes un solo cerebro con todos los poderes.

→ Fortalezas y límites por CLI (fechado, cambia rápido): **[docs/COMPARISON.md](../COMPARISON.md)**.

## Por qué cli-bridge (y no otro MCP de «llamar a otros modelos»)

- 🛡️ **Ban-safe por diseño.** Lanza la **CLI oficial** de cada modelo, exactamente como tú a mano —
  sin extracción de token OAuth, sin reutilización de clave API. Cada CLI gestiona su propia auth y
  facturación.
- 💸 **Defaults cost-safe que ajustas a tu plan.** De fábrica, `ask_all` / `ask_cascade` construyen un
  consejo *gratis* y nunca tocan cuota de pago salvo que lo pidas. Cada lane trae un nivel sacado de
  los planes publicados del proveedor (fechados en [docs/COSTS.md](../COSTS.md), **nunca detectados
  desde tu cuenta**); sobrescribe por lane con `CLI_BRIDGE_<LANE>_COST=free|limited|paid`.
- 🔌 **Funciona desde cualquier host.** Claude Code, Codex, opencode, Cursor, VS Code (Cline/Continue),
  Zed — cualquier cosa que hable MCP por stdio. La lane del propio host se mantiene fuera del fan-out;
  ocúltala con `CLI_BRIDGE_HIDE_HOST=1`. Incluso un **modelo local puede ser el host** — ver
  [`examples/local-first-host.md`](../../examples/local-first-host.md).
- 🧭 **El borde entre proveedores es el moat.** La verificación independiente significa un *proveedor
  distinto* en el asiento del revisor — lo escaso a medida que la IA escribe una porción mayor del
  código, y exactamente lo que una herramienta de un solo proveedor no puede ofrecer.

---

## Cómo funciona

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
       keeps the host's own lane out of fan-out · only shows installed, enabled CLIs
       kills the whole process tree on timeout/cancellation · redacts secrets
       classifies errors (auth/limit/failed) · spills huge output to a file
```

Sin llamadas de red propias. Sin claves almacenadas. Ejecuta los mismos binarios en los que ya
confías, en tu directorio de trabajo, y te devuelve la respuesta.

<div align="center">

<img src="../../assets/demo.gif" width="860" alt="demo cli-bridge security-review: un bypass de autorización commiteado lo atrapa un consejo entre proveedores, fusionado en un informe clasificado por severidad, 0 $ en lanes gratis">

_Run real (velocidad 2,2×): la palanca Verificar — `security-review` reparte roles OWASP entre modelos
gratis en paralelo (aquí claude/gpt/opencode/ollama); señalan un bypass de auth commiteado como
**blocker**, y `usage` muestra los recibos._

</div>

---

## Escribir código de forma segura: dos modos

Las escrituras están contenidas, de dos formas — **tú eliges** con revisión o sin manos:

- **`isolated` (por defecto).** Edita en un worktree git desechable y devuelve un **diff**. Tu árbol
  de trabajo nunca se toca.
- **`direct`.** Escribe archivos reales, **pero solo dentro de una `zone` que declaras**, tras un
  cerrojo por zona con comprobación de violación de zona post-turno. Tú en `backend/`, un delegado en
  `frontend/`, a la vez — ninguno puede garabatear todo tu repo; el deshacer está acotado a la zona,
  nunca un reset global.

La re-entrada de delegados está topada en profundidad (`CLI_BRIDGE_MAX_DEPTH`, por defecto 1) para que
un delegado mal configurado no pueda fork-bombear el consejo.

---

## Inicio rápido (≈5 min)

```bash
# Run it (no install) — installs straight from the repo:
uvx --from git+https://github.com/JoaoBerne/cli-bridge-mcp cli-bridge doctor
# or, from a clone:  python -m cli_bridge

# Point your MCP host at that same command, then:
cli-bridge doctor        # see which CLIs are detected + their resolved paths
```

### Lanes

**Integradas:** Claude Code, Codex, Gemini (+ Antigravity `agy`), opencode, **Ollama (modelos locales,
0 $, offline)**, Qwen Code, Copilot, Grok.

**Runtimes locales** más allá de Ollama — **LM Studio · MLX · llama.cpp** — vienen como recetas sin
código: apunta `CLI_BRIDGE_LANES_FILE` a [`examples/lmstudio.lane.json`](../../examples/lmstudio.lane.json),
[`mlx.lane.json`](../../examples/mlx.lane.json), o [`llamacpp.lane.json`](../../examples/llamacpp.lane.json).
(Varios runtimes locales de los *mismos* pesos abiertos dan respuestas correlacionadas — la verdadera
diversidad de consejo viene de proveedores distintos, no de un segundo runtime local.)

**Lanes comunitarias** (`examples/community-lanes.json`, experimentales + `limited` hasta que declares
su coste): Aider, Goose, Plandex, Amp, Crush, Amazon Q Developer CLI, Droid.

**Cualquier otra cosa son ~3 líneas de JSON.** Añade una lane personalizada, o envuelve cualquier
endpoint compatible con OpenAI lanzando `curl` (la clave queda dentro de curl, nunca en argv). Ver
[`examples/`](../../examples/) para recetas.

---

## La parte honesta

«Más modelos = mejor» es *frágil* — los modelos grandes comparten datos de entrenamiento, así que sus
errores están correlacionados. Medimos nuestra propia afirmación central (`cli-bridge eval`, sin juez
LLM): un consejo diverso **no** atrapó más bugs que un solo modelo fuerte — recortó las falsas alarmas
**~2×**. Misma tasa de detección, mucho menos ruido — que es exactamente lo que mantiene a un revisor
digno de confianza en vez de ignorado. **La precisión es el producto, no el recall.** El harness se
entrega, así que puedes confirmarlo en *tus* CLI — números en cualquier sentido en
[docs/BENCHMARKS.md](../BENCHMARKS.md).

---

## Limitaciones conocidas

- **Ban-safe = sin extracción de token/clave**, no una garantía total — el uso no interactivo de la
  CLI de un proveedor no está formalmente sancionado en todas partes y puede cambiar. Usa tus propias
  cuentas dentro de sus términos.
- **Los jobs asíncronos son en-proceso** — un reinicio del servidor marca los jobs en curso como
  `interrupted`. `batch_run` / `workflow` son la excepción: hacen journaling de cada tarea y retoman
  vía `resume_id`.
- **El guard anti-inyección es heurístico** — atrapa patrones de alta señal, no todo; trata la salida
  de un delegado como datos, no como instrucciones.
- **Las cifras de tokens/créditos son estimaciones** (chars/4 + tu `CREDITS_PER_1K`), nunca exactas.
- **Los niveles de coste son defaults sacados de fuentes, no detección** — los datos de plan están
  fechados; `doctor` avisa cuando la instantánea está obsoleta.
- **Experimental** (`qwen`, `copilot`, `grok`, lanes comunitarias, Gemini `images=`): los flags no
  están verificados en vivo — `doctor deep` los comprueba contra el `--help` de cada CLI en tu
  máquina.

---

## Hoja de ruta

Ver [`CHANGELOG.md`](../../CHANGELOG.md) para el historial entregado. Actualmente **explorando (no
entregado)**: un modo de verificación con **oráculo independiente** (una lane de otra familia escribe
los tests desde la *spec*, ciega a la implementación, para que el test atrape el bug en vez de
reflejarlo) y un **failover más fino frente a límites**. Las grandes ideas de «bus» entre agentes
(spawn recursivo, estado compartido, protocolo de cable) se posicionan honestamente como una
*dirección*, nunca se venden como un protocolo entregado — ver [docs/ARCHITECTURE.md](../ARCHITECTURE.md).

---

## Referencias

Las decisiones de diseño de arriba no son corazonadas — cada una corresponde a un hallazgo de la
literatura. Cada entrada se verificó contra su fuente (autores + lugar de publicación), porque una
herramienta que vende «verificación honesta entre proveedores» debería acertar con sus propias citas.

| Artículo | ID | Qué respalda aquí |
|-------|----|--------------------|
| Du et al. — *Improving Factuality and Reasoning via Multiagent Debate* | [2305.14325](https://arxiv.org/abs/2305.14325) | `debate`: modelos que se critican baten a un modelo solo |
| ReConcile — *Round-Table Conference Improves Reasoning* | [2309.13007](https://arxiv.org/abs/2309.13007) | convergencia de `debate` + consenso ponderado por confianza |
| Mixture-of-Agents | [2406.04692](https://arxiv.org/abs/2406.04692) | agregación en capas entre modelos diversos (y sus límites) |
| Chain-of-Agents | [2406.02818](https://arxiv.org/abs/2406.02818) | pipelines multi-agente especializados por rol |
| CriticGPT — *LLM Critics Help Catch LLM Bugs* | [2407.00215](https://arxiv.org/abs/2407.00215) | `review_diff` / `security_review`: un crítico LLM atrapa bugs que los humanos pasan por alto |
| Perez et al. — *Discovering Language Model Behaviors* (adulación) | [2212.09251](https://arxiv.org/abs/2212.09251) | por qué un juez de la misma familia es débil → `jury` entre proveedores + anonimización de pares |
| Wynn, Satija & Hadfield — *Talk Isn't Always Cheap* | [2509.05396](https://arxiv.org/abs/2509.05396) | modos de fallo del debate → veredictos fail-closed, rondas acotadas |
| CONSENSAGENT — *Consensus via Sycophancy Mitigation* (Findings of ACL 2025) | [ACL 2025](https://aclanthology.org/2025.findings-acl.1141/) | adulación en consenso → «ganarse el puesto» / pares anonimizados |
| Maryanskyy — *When Agents Disagree: The Selection Bottleneck* | [2603.20324](https://arxiv.org/abs/2603.20324) | `consensus`: **selección > síntesis** (el default de voto determinista entre pares) |

> **Nota de higiene de citas.** *Talk Isn't Always Cheap* (2509.05396) es de **Wynn, Satija &
> Hadfield** — un framework de consejo popular lo cita mal como «Xiong et al.». Reverificamos las
> atribuciones antes de repetirlas, y lo señalamos porque la honestidad es todo el propósito.

## Desarrollo

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration (cross-host) tests; no real CLI or network needed
```

## Licencia

MIT

---

<div align="center">

<img src="../../assets/mark.gif" width="84" alt="cli-bridge">

<sub>una orilla · conectada a un consejo</sub>

</div>
