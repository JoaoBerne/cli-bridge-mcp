<div align="center">

<img src="../../assets/banner.gif" width="860" alt="cli-bridge — seu assistente toma emprestados os poderes de todas as CLIs de IA que você já tem: leituras de contexto enorme, visão, builds em paralelo, verificações entre fornecedores">

[English](../../README.md) · [Français](README.fr.md) · [简体中文](README.zh-CN.md) · [Español](README.es.md) · **Português (BR)** · [日本語](README.ja.md) · [Deutsch](README.de.md)

</div>

_O README em inglês é a fonte autoritativa; esta tradução pode ficar para trás. Revisão da comunidade é bem-vinda._

# cli-bridge

<!-- Reativar ao tornar público (ambos quebram enquanto o repo é privado / não publicado):
![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/cli-bridge-mcp) -->
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**Seu assistente, com os poderes de todas as CLIs que você já tem.**

> **Sem chaves de API · sem extração de tokens · sem Node · sem daemon · só stdlib + `mcp`.**

O assistente com quem você fala não consegue ler um repo de 2 M de tokens de uma vez, não consegue ver
uma captura de tela, não consegue te entregar uma imagem gerada, e não consegue revisar o próprio
trabalho sem viés. As outras CLIs de IA que você **já instalou e nas quais já fez login** — Claude
Code, Codex, Gemini, opencode, além de modelos locais via Ollama — cada uma faz algo que a sua não faz.
`cli-bridge` é um servidor [Model Context Protocol](https://modelcontextprotocol.io) que permite ao seu
assistente **tomá-las emprestadas**: ele inicia a CLI oficial como subprocesso (exatamente como você
rodaria à mão — sem chaves, sem extração de tokens) e te devolve o resultado.

---

## A demo de 10 segundos

Você está no Claude. O Claude não pode te entregar uma imagem. O Codex pode — ele escreve o código que
gera uma e o executa. Então peça a ele:

```
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png — write a script that renders it, then run it", zone="assets")
→ Codex writes assets/card.png · you get the path back, never a binary blob (artifact-return)
```

Seu assistente acabou de ganhar uma capacidade que não tem. É toda a ideia — agora escale isso para
leituras de contexto gigante, visão, trabalho braçal em paralelo, e verificação independente entre
fornecedores.

_(A lane gera a imagem **via código** — gráficos, diagramas, SVGs, arte procedural — e devolve o
arquivo; não é um modelo texto-para-foto a menos que você aponte um. Por isso o resultado volta como um
caminho, não como um blob.)_

### …e ele delega trabalho real, com segurança

`cli-bridge build <lane> "<tarefa>"` entrega o trabalho a outro modelo rodando num **worktree git
descartável**, e então te devolve um **diff** — seu repo nunca é tocado até você mesmo aplicá-lo.

<p align="center">
<img src="../../assets/demo-borrow.gif" width="860" alt="cli-bridge build: o opencode adiciona uma função num worktree descartável e devolve um diff revisável; o repo real fica limpo">
</p>

---

## Como pensar nisso (o modelo mental)

cli-bridge não é uma funcionalidade, são **quatro alavancas**. Entenda-as e cada ferramenta abaixo se
encaixa:

1. **Tomar emprestado** — alcançar uma capacidade que seu assistente não tem (visão, janela de
   contexto de 1 M de tokens, um arquivo que um agente de código gera, um modelo simplesmente melhor
   *nisto*).
2. **Distribuir** — quando uma assinatura atinge o limite, continue em outra lane que você já paga.
3. **Descarregar** — espalhar trabalho braçal e paralelizável em lanes grátis/baratas enquanto você
   codifica em outro lugar.
4. **Verificar** — ter uma *família de fornecedor diferente* checando o trabalho, porque um modelo não
   enxerga os próprios pontos cegos. É a única coisa que uma ferramenta de um só fornecedor não
   consegue fazer estruturalmente.

---

## O que isso destrava

Cada bloco: uma frase de *quando recorrer a isso*, a chamada exata, e *o que você recebe de volta*.

### Tome emprestadas capacidades que seu assistente não tem
Cada CLI tem um superpoder diferente, e cada uma roda de forma não interativa — então o cli-bridge pode
iniciá-la. Tome emprestada a que falta ao seu host (precisa estar instalada + logada):

| Superpoder | Qual CLI o tem | Tome emprestado quando |
|------------|------------------|----------------|
| **Imagens** | Codex (`gpt-image-2`, **sem chave de API** — via seu plano ChatGPT) | seu host não sabe desenhar |
| **Contexto enorme** | Gemini (janela de 1 M de tokens) | um arquivo/repo não cabe no contexto do seu host |
| **Conhecimento fresco** | Gemini (grounding com Google Search) · Grok (web/X ao vivo) ⚗️ | vencer uma data de corte: *«qual é a API atual de `<lib>`?»* |
| **Visão** | Gemini (`images=[…]`) ⚗️ | analisar uma captura ou um diagrama |
| **Uma segunda opinião grátis** | Gemini (nível diário grátis) · opencode · Ollama (local, 0 $) | uma checagem cruzada a 0 $ |
| **Arquivos gerados** | qualquer lane de build → artifact-return | receber um gráfico / PDF / diagrama **por caminho** |
| **Vídeo** ⚗️ | Gemini (Veo) · Grok (Imagine) — *se a sua CLI instalada o expõe* | você precisa de um clipe gerado |

```
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png", zone="assets")   # Codex image → file by path, no API key
ask_gemini(task="find the bug across ./src — read the files you need", cwd="path/to/repo")         # 1M-token context
ask_gemini(task="what's the current recommended API for <lib>? check the latest docs")            # fresh knowledge (Search grounding)
ask_gemini(task="what's wrong in this UI?", images=["screenshot.png"])                             # vision (experimental)
```

⚗️ = experimental / depende da versão atual da CLI instalada (p. ex. Grok Build está em beta) — verifique com `doctor deep`.

### Nunca pare de trabalhar quando bater num limite
Quando sua assinatura principal satura no meio da tarefa. `ask_cascade` cai para outra lane que você já
paga, pulando qualquer lane em pausa após um erro de cota/auth/timeout.

```
ask_cascade(task="finish wiring this endpoint")   # cheapest→strongest; a cooled-down lane is skipped
ask_best(task="…", mode="deep")                   # let the router pick the most suitable available lane
```

### Descarregue o trabalho braçal — em paralelo, e barato
Quando o trabalho é laborioso mas não difícil (refactors, migrações, cobertura de testes). Espalhe-o,
com journaling para que um restart do servidor retome em vez de recomeçar; delegue um build e continue
trabalhando.

```
batch_run(tasks=[...], dry_run=true)                       # cost envelope first — nothing is spawned
batch_run(tasks=[...], max_calls=20, max_credits=2.0)      # then run under a hard budget (resumable)
ask_build(lane="opencode", task="add the landing page", zone="frontend", mode="direct", async=true)   # delegate, keep building
job_tail(job_id="…")  ·  build_steer(job_id="…", instruction="use Tailwind, not inline CSS")
```

### Quebre a auto-confirmação — o problema de 2026 que um só fornecedor não resolve
Quando você precisa *confiar* num resultado. Um modelo revisando o próprio trabalho (ou o de um irmão)
só confirma os próprios pontos cegos. O cli-bridge coloca uma **família de modelo diferente** na
cadeira do revisor.

```
workflow(preset="jury", task="is this migration safe?", author_lane="gpt")            # cross-family vote, fail-closed
workflow(preset="verify_repair", task="add retry with backoff",
         builder_lane="gpt", verifier_lane="gemini")                                   # A builds, B reviews, loop to green
security_review(base="origin/main")   ·   review_diff(base="origin/main")              # OWASP, severity-ranked
```

### Obtenha uma segunda opinião de verdade
Quando você já chegou a uma conclusão e quer testá-la sob pressão, ou vários modelos lado a lado.

```
challenge(task="I'm dropping the cache layer — here's why: …")                         # one skeptic attacks it
consensus(task="which migration strategy is safest here?")                             # N answer, peer-rank the best
workflow(preset="fanout_compare", task="fix this failing test", lanes=["gpt","gemini","opencode"])
```

---

## A caixa de ferramentas completa

Todas as ferramentas, agrupadas por intenção. Rode `CLI_BRIDGE_LEAN=1` para uma superfície curada de
~12 ferramentas; oculte/mostre qualquer uma com `CLI_BRIDGE_DISABLED_TOOLS` / `CLI_BRIDGE_ENABLED_TOOLS`.

### Consultar (somente leitura)
| Ferramenta | O que faz | Recorra a ela quando |
|------|--------------|-------------------|
| `ask_<lane>` | Perguntar a uma CLI específica — `ask_claude`, `ask_gpt` (Codex), `ask_gemini`, `ask_mistral`, `ask_opencode`, `ask_ollama`, e `ask_qwen`/`ask_grok`/`ask_copilot` quando instaladas. Suporta `role="reviewer\|security\|planner\|devil"`, `conversation` (memória de mesa-redonda), e `images=[…]` no Gemini. | Você quer a força, a persona ou a modalidade de um modelo específico. |
| `ask_all` | A mesma pergunta a cada lane *grátis* em paralelo; devolve cada resposta **mais uma pontuação de discordância**. `synthesize: true` adiciona um resumo de concordância/discordância. | Você quer amplitude rápida + sinal de onde os modelos divergem (= incerteza). |
| `ask_cascade` | Tenta lanes em ordem determinística, para na primeira boa resposta, pula lanes em pausa; escalonamento de confiança opcional. | Você quer resiliência: uma lane no teto/falhando é pulada automaticamente. |
| `ask_best` | Um roteador escolhe a lane mais adequada por `mode` (`fast/cheap/deep/code/review/security`) + suas notas `rate_lane`. | Você não quer escolher lane na mão. |
| `ask_all_async` + `job_status`/`job_result`/`job_cancel`/`jobs_list` | Dispara `ask_all` como job em segundo plano (id em <1 s). | O fan-out é lento e você quer continuar trabalhando. |
| `consensus` | N lanes respondem, depois os pares classificam para **selecionar** a melhor (seleção bate síntese). | Uma única resposta defensável importa mais que uma mistura. |
| `challenge` | Uma lane faz o cético contra uma conclusão que você fornece. | Você quer seu raciocínio atacado antes de se comprometer. |
| `conversations_list` / `conversation_show` | Listar / ler threads de mesa-redonda persistentes (sobrevivem a `/compact` e restarts). | Você quer recuperar ou ler um thread multi-modelo. |

### Construir (escrita opt-in)
| Ferramenta | O que faz | Recorra a ela quando |
|------|--------------|-------------------|
| `ask_build` | Delega um build real. `mode=isolated` (padrão) edita um worktree descartável → **diff**; `mode=direct` escreve numa `zone` declarada (trava por zona + checagem de violação de zona após o turno). `async=true` o roda como job dirigível. Saídas não textuais voltam **por caminho** (artifact-return). | Você quer trabalho *feito*, não só sugerido — com revisão ou sem mãos. |
| `ask_build_isolated` | Alias conveniente de `ask_build` com `mode=isolated` — sempre devolve um diff, nunca toca sua árvore. | Você quer o caminho seguro (diff) pelo nome, sem setar `mode`. |
| `job_tail` | Transmite o log de progresso de um build em andamento (por offset de byte). | Você quer assistir um delegado trabalhar. |
| `build_steer` | Enfileira uma instrução de direção para o próximo turno, ou `interrupt=true` corta o turno atual (arquivos mantidos). | Você precisa corrigir o rumo no meio do build sem reiniciar. |

Builds assíncronos rodam contra uma **Definition-of-Done** executável (`dod_cmd`) — a alegação de
sucesso do delegado é *testada*, não confiada.

### Revisar e verificar
| Ferramenta | O que faz | Recorra a ela quando |
|------|--------------|-------------------|
| `review_diff` | Revisão estruturada de um diff → findings (severidade, arquivo, justificativa), mesclados de forma determinística entre lanes com confiança single/majority/consensus. | Antes de um mudança aterrissar. |
| `security_review` | Passada de segurança orientada a OWASP, classificada por severidade + uma seção `residual_risk`. | A mudança toca auth, tratamento de entradas, segredos. |
| `debate` | Os modelos se criticam por rodadas limitadas, terminando com um rodapé `VOTE` + parada antecipada por convergência; um juiz independente conclui. | Uma decisão genuinamente disputada. |
| `premortem` / `test_plan` | Análise de modos de falha de um plano / um plano de teste priorizado a partir de um diff ou descrição. | Antes de escrever código. |
| `commit_msg` / `pr_describe` | Uma mensagem Conventional-Commit do seu diff em stage / um título+corpo de PR a partir do branch. Somente leitura — emite texto. | Você está prestes a commitar ou abrir uma PR. |
| `workflow(preset=…)` | Pipelines nomeados: `jury` (voto entre famílias k-de-N, fail-closed), `verify_repair` (loop build→revisão→reparo entre modelos), `refine_plan`, `fanout_compare`, `council_review`, `map_review`, `research_verify`. | Você quer um padrão multi-etapas testado em uma chamada. |

### Orquestrar
| Ferramenta | O que faz | Recorra a ela quando |
|------|--------------|-------------------|
| `batch_run` | Fan-out durável e **com journaling** sobre muitas tarefas. `dry_run=true` devolve um envelope de custo (nada é iniciado); `max_calls`/`max_credits` limitam o gasto; `resume_id` reproduz as tarefas concluídas e roda só o resto após um restart. | Trabalho em massa que você quer limitado e à prova de crash. |

### Operar
| Ferramenta | O que faz | Recorra a ela quando |
|------|--------------|-------------------|
| `usage_report` / `usage_budget` | Contabilidade estimada de tokens/créditos (chars/4 — honestamente rotulada como estimativa) + orçamento contra um teto diário. | Você quer ver a conta / pôr um teto. |
| `rate_lane` / `route_plan` | Pontuar uma lane de 1 a 5 para um modo para que `ask_best` aprenda sua stack / pré-visualizar a ordem que uma cascata tentaria. | Você quer que o roteador melhore com o tempo. |
| `lane_stats` / `reset_lane_state` | Saúde por lane, pausas, e o sinal de júri «ganhar o lugar» / zerar os contadores de uma lane. | Uma lane está se comportando mal, ou você quer o relatório de lugares. |
| `set_lane_cost` | Registrar o que uma lane custa *para você* («Codex é grátis no meu plano») — persistido, sem precisar de `setup`. | Você solta um fato de preço de passagem. |
| `doctor` / `setup` | Detectar as CLIs instaladas + caminhos resolvidos; `doctor deep` valida cada lane contra o próprio `--help` na sua máquina. | Primeira execução, ou quando uma lane quebra. |
| `list_models` / `list_<lane>_models` | Listar os modelos de uma lane onde a CLI os expõe. | Você quer escolher um modelo específico. |

Há também uma **CLI humana** (`cli-bridge doctor|ask|ask-all|ask-best|build|review-diff|eval|…`) — o
mesmo motor a partir do seu terminal ou CI (`--json` em tudo). `cli-bridge build <lane> "<tarefa>"`
delega um build real a uma lane num worktree descartável e imprime o **diff** — seu repo nunca é tocado.

---

## O que você realmente ganha ao combiná-las

Um único assistente cujo teto em **cada eixo é o melhor do ecossistema** — não a ferramenta que você
abriu hoje de manhã: codar com o modelo mais forte, ler 1–2 M de tokens quando o seu é curto demais,
responder com conhecimento fresco além de uma data de corte, gerar imagens/vídeo, ver capturas, e cair
para uma lane grátis/local quando você está no teto — espalhado pelas assinaturas que você já paga.

A propriedade emergente **que nenhuma CLI sozinha tem: controle real entre fornecedores** — um
*fornecedor diferente* na cadeira do revisor. Subagentes da mesma família (os do Claude Code, os do
Grok) só conseguem se auto-confirmar.

A costura honesta: isto une **capacidades, não mente** — spawns sem estado (sem memória compartilhada),
latência/custo de spawn, qualidade desigual, e o host sempre dirige. É **orquestração, não fusão**:
você rege especialistas, não ganha um único cérebro com todos os poderes.

→ Forças e limites por CLI (datado, muda rápido): **[docs/COMPARISON.md](../COMPARISON.md)**.

## Por que cli-bridge (e não outro MCP de «chamar outros modelos»)

- 🛡️ **Ban-safe por design.** Ele inicia a **CLI oficial** de cada modelo, exatamente como você à mão —
  sem extração de token OAuth, sem reuso de chave de API. Cada CLI cuida da própria auth e cobrança.
- 💸 **Padrões cost-safe que você ajusta ao seu plano.** De fábrica, `ask_all` / `ask_cascade` montam
  um conselho *grátis* e nunca tocam cota paga a menos que você peça. Cada lane traz um tier sourced
  dos planos publicados do fornecedor (datados em [docs/COSTS.md](../COSTS.md), **nunca detectados da
  sua conta**); sobrescreva por lane com `CLI_BRIDGE_<LANE>_COST=free|limited|paid`.
- 🔌 **Funciona de qualquer host.** Claude Code, Codex, opencode, Cursor, VS Code (Cline/Continue),
  Zed — qualquer coisa que fale MCP por stdio. A lane do próprio host fica fora do fan-out; oculte-a
  com `CLI_BRIDGE_HIDE_HOST=1`. Até um **modelo local pode ser o host** — veja
  [`examples/local-first-host.md`](../../examples/local-first-host.md).
- 🧭 **A vantagem entre fornecedores é o moat.** Verificação independente significa um *fornecedor
  diferente* na cadeira do revisor — o escasso à medida que a IA escreve uma fatia maior do código, e
  exatamente o que uma ferramenta de um só fornecedor não pode oferecer.

---

## Como funciona

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
       keeps the host's own lane out of fan-out · only shows installed, enabled CLIs
       kills the whole process tree on timeout/cancellation · redacts secrets
       classifies errors (auth/limit/failed) · spills huge output to a file
```

Sem chamadas de rede próprias. Sem chaves armazenadas. Ele roda os mesmos binários em que você já
confia, no seu diretório de trabalho, e te devolve a resposta.

<div align="center">

<img src="../../assets/demo.gif" width="860" alt="demo cli-bridge security-review: um bypass de autorização commitado é pego por um conselho entre fornecedores, mesclado num relatório classificado por severidade, 0 $ nas lanes grátis">

_Run real (velocidade 2,2×): a alavanca Verificar — `security-review` espalha papéis OWASP por modelos
grátis em paralelo (aqui claude/gpt/opencode/ollama); eles sinalizam um bypass de auth commitado como
**blocker**, e `usage` mostra os recibos._

</div>

---

## Escrever código com segurança: dois modos

As escritas são contidas, de dois jeitos — **você escolhe** com revisão ou sem mãos:

- **`isolated` (padrão).** Edita num worktree git descartável e devolve um **diff**. Sua árvore de
  trabalho nunca é tocada.
- **`direct`.** Escreve arquivos reais, **mas só dentro de uma `zone` que você declara**, atrás de uma
  trava por zona com checagem de violação de zona pós-turno. Você em `backend/`, um delegado em
  `frontend/`, ao mesmo tempo — nenhum pode rabiscar o repo inteiro; o desfazer é limitado à zona,
  nunca um reset global.

A reentrada de delegados é limitada em profundidade (`CLI_BRIDGE_MAX_DEPTH`, padrão 1) para que um
delegado mal configurado não consiga fork-bomb no conselho.

---

## Início rápido (≈5 min)

```bash
# Run it (no install):
uvx cli-bridge-mcp
# or:  python -m cli_bridge

# Point your MCP host at that same command, then:
cli-bridge doctor        # see which CLIs are detected + their resolved paths
```

### Lanes

**Integradas:** Claude Code, Codex, Gemini (+ Antigravity `agy`), opencode, **Ollama (modelos locais,
0 $, offline)**, Qwen Code, Copilot, Grok.

**Runtimes locais** além do Ollama — **LM Studio · MLX · llama.cpp** — vêm como receitas sem código:
aponte `CLI_BRIDGE_LANES_FILE` para [`examples/lmstudio.lane.json`](../../examples/lmstudio.lane.json),
[`mlx.lane.json`](../../examples/mlx.lane.json), ou [`llamacpp.lane.json`](../../examples/llamacpp.lane.json).
(Vários runtimes locais dos *mesmos* pesos abertos dão respostas correlacionadas — a verdadeira
diversidade de conselho vem de fornecedores distintos, não de um segundo runtime local.)

**Lanes da comunidade** (`examples/community-lanes.json`, experimentais + `limited` até você declarar o
custo): Aider, Goose, Plandex, Amp, Crush, Amazon Q Developer CLI, Droid.

**Qualquer outra coisa são ~3 linhas de JSON.** Adicione uma lane personalizada, ou embrulhe qualquer
endpoint compatível com OpenAI iniciando `curl` (a chave fica dentro do curl, nunca no argv). Veja
[`examples/`](../../examples/) para receitas.

---

## A parte honesta

«Mais modelos = melhor» é *frágil* — modelos grandes compartilham dados de treino, então seus erros
são correlacionados. Medimos nossa própria alegação central (`cli-bridge eval`, sem juiz LLM): um
conselho diverso **não** pegou mais bugs do que um único modelo forte — ele cortou os falsos alarmes
**~2×**. Mesma taxa de detecção, muito menos ruído — que é exatamente o que mantém um revisor confiável
em vez de ignorado. **Precisão é o produto, não recall.** O harness é entregue, então você pode
confirmar nas *suas* CLIs — números num sentido ou no outro em [docs/BENCHMARKS.md](../BENCHMARKS.md).

---

## Limitações conhecidas

- **Ban-safe = sem extração de token/chave**, não uma garantia geral — o uso não interativo da CLI de
  um fornecedor não é formalmente sancionado em todo lugar e pode mudar. Use suas próprias contas
  dentro dos termos delas.
- **Jobs assíncronos são in-process** — um restart do servidor marca os jobs em andamento como
  `interrupted`. `batch_run` / `workflow` são a exceção: fazem journaling de cada tarefa e retomam via
  `resume_id`.
- **O guard anti-injeção é heurístico** — pega padrões de alto sinal, não tudo; trate a saída de um
  delegado como dado, não como instruções.
- **Os números de tokens/créditos são estimativas** (chars/4 + seu `CREDITS_PER_1K`), nunca exatos.
- **Os tiers de custo são padrões sourced, não detecção** — fatos de plano são datados; `doctor` avisa
  quando o snapshot está velho.
- **Experimental** (`qwen`, `copilot`, `grok`, lanes da comunidade, Gemini `images=`): as flags não
  são verificadas ao vivo — `doctor deep` as confere contra o `--help` de cada CLI na sua máquina.

---

## Roadmap

Veja [`CHANGELOG.md`](../../CHANGELOG.md) para o histórico entregue. Atualmente **explorando (não
entregue)**: um modo de verificação com **oráculo independente** (uma lane de outra família escreve os
testes a partir da *spec*, cega à implementação, para que o teste pegue o bug em vez de espelhá-lo) e
um **failover mais fino diante de limites**. As grandes ideias de «bus» entre agentes (spawn
recursivo, estado compartilhado, protocolo de fio) são posicionadas honestamente como uma *direção*,
nunca vendidas como um protocolo entregue — veja [docs/ARCHITECTURE.md](../ARCHITECTURE.md).

---

## Referências

As decisões de design acima não são achismos — cada uma corresponde a um achado da literatura. Cada
entrada foi verificada contra a fonte (autores + local de publicação), porque uma ferramenta que vende
«verificação honesta entre fornecedores» deveria acertar nas próprias citações.

| Artigo | ID | O que sustenta aqui |
|-------|----|--------------------|
| Du et al. — *Improving Factuality and Reasoning via Multiagent Debate* | [2305.14325](https://arxiv.org/abs/2305.14325) | `debate`: modelos se criticando batem um modelo sozinho |
| ReConcile — *Round-Table Conference Improves Reasoning* | [2309.13007](https://arxiv.org/abs/2309.13007) | convergência do `debate` + consenso ponderado por confiança |
| Mixture-of-Agents | [2406.04692](https://arxiv.org/abs/2406.04692) | agregação em camadas entre modelos diversos (e seus limites) |
| Chain-of-Agents | [2406.02818](https://arxiv.org/abs/2406.02818) | pipelines multi-agente especializados por papel |
| CriticGPT — *LLM Critics Help Catch LLM Bugs* | [2407.00215](https://arxiv.org/abs/2407.00215) | `review_diff` / `security_review`: um crítico LLM pega bugs que humanos passam batido |
| Perez et al. — *Discovering Language Model Behaviors* (bajulação) | [2212.09251](https://arxiv.org/abs/2212.09251) | por que um juiz da mesma família é fraco → `jury` entre fornecedores + anonimização de pares |
| Wynn, Satija & Hadfield — *Talk Isn't Always Cheap* | [2509.05396](https://arxiv.org/abs/2509.05396) | modos de falha do debate → veredictos fail-closed, rodadas limitadas |
| CONSENSAGENT — *Consensus via Sycophancy Mitigation* (Findings of ACL 2025) | [ACL 2025](https://aclanthology.org/2025.findings-acl.1141/) | bajulação em consenso → «ganhar o lugar» / pares anonimizados |
| Maryanskyy — *When Agents Disagree: The Selection Bottleneck* | [2603.20324](https://arxiv.org/abs/2603.20324) | `consensus`: **seleção > síntese** (o padrão de voto determinístico entre pares) |

> **Nota de higiene de citação.** *Talk Isn't Always Cheap* (2509.05396) é de **Wynn, Satija &
> Hadfield** — um framework de conselho popular o cita errado como «Xiong et al.». Reverificamos as
> atribuições antes de repeti-las, e sinalizamos porque honestidade é todo o propósito.

## Desenvolvimento

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration (cross-host) tests; no real CLI or network needed
```

## Licença

MIT

---

<div align="center">

<img src="../../assets/mark.gif" width="84" alt="cli-bridge">

<sub>uma margem · ligada a um conselho</sub>

</div>
