<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../assets/banner-dark.svg">
  <img src="../../assets/banner-light.svg" width="860" alt="Você → cli-bridge → um conselho de CLIs de IA em paralelo → uma revisão consolidada">
</picture>

[English](../../README.md) · [Français](README.fr.md) · [简体中文](README.zh-CN.md) · [Español](README.es.md) · **Português (BR)** · [日本語](README.ja.md) · [Deutsch](README.de.md)

</div>

_O README em inglês é a versão canônica; esta tradução pode estar desatualizada._

# cli-bridge

![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/cli-bridge-mcp)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**Seu assistente de IA, mas que pode ligar para um amigo.**

`cli-bridge` é um servidor [Model Context Protocol](https://modelcontextprotocol.io) que
**orquestra as CLIs de IA que você já instalou e nas quais já fez login** — Claude Code, Codex,
Gemini CLI, opencode, … — a partir de qualquer assistente com o qual você esteja conversando. Sem
chaves de API, sem extração de token, um log apenas local, um teto rígido de custo, e gravações
feitas somente como diffs em worktrees descartáveis. Essa parte é encanamento indiscutível; eis o
que ela desbloqueia:

Travado num bug cabeludo? Faça seu assistente perguntar ao GPT *e* ao Gemini em paralelo e comparar.
Precisa de uma leitura de 1M de tokens de um arquivo enorme? Entregue ao Gemini. Quer uma segunda
opinião barata? Dispare para um modelo gratuito. Uma pergunta, todos os modelos, lado a lado — sem
sair do seu terminal.

```
You → Claude:  "ask the council whether this auth logic is safe"
Claude → cli-bridge → [ Gemini ] [ GPT ] [ Mistral ] [ Qwen ] … in parallel
            ← three independent reviews + a synthesis of where they agree & disagree
```

<div align="center">

<img src="../../assets/demo.gif" width="860" alt="Demo do security-review do cli-bridge: um bypass de autenticação commitado é pego de forma independente por dois modelos, consolidado em um único relatório ordenado por severidade, $0 nas lanes gratuitas">

_Execução real (velocidade 2,5×): um bypass de autenticação commitado — `security-review` distribui
papéis OWASP entre modelos gratuitos em paralelo; dois modelos o marcam como **blocker** de forma
independente, e `usage` mostra os comprovantes._
_Gerado com [vhs](https://github.com/charmbracelet/vhs) — [ver fonte](../demo/)._

</div>

> **Por que é diferente, em um fôlego:** ele nunca guarda uma chave de API e nunca extrai um token —
> ele aciona as CLIs oficiais que você **já instalou e nas quais já fez login**. Um conselho de
> lanes gratuitas custa **$0.00** (os comprovantes estão em `usage_report`); lanes pagas só rodam
> dentro de um teto diário rígido que *você* define. E quando você pede para ele *fazer* o trabalho,
> ele edita em um worktree git descartável e devolve um **diff** — seu repositório ativo nunca é
> tocado.

> **E a parte honesta:** "mais modelos = melhor" é *frágil* — modelos grandes compartilham dados de
> treinamento, então seus erros são correlacionados. Medimos nossa própria afirmação central
> (`cli-bridge eval`, já disponível, sem juiz LLM): um conselho diverso **não** pegou mais bugs do
> que um único modelo forte — ele cortou os alarmes falsos em **~2×**. Publicamos os números de
> qualquer jeito ([BENCHMARKS.md](../BENCHMARKS.md)), e o harness vem incluído para que você possa
> rodá-lo nas *suas* CLIs.

---

## Por que esta

Existem outros MCPs do tipo "chamar outros modelos". Eis o que torna o cli-bridge diferente:

- 🛡️ **Ban-safe por design.** Ele invoca a **CLI oficial** de cada modelo — exatamente como você a
  rodaria à mão. Sem extração de token OAuth, sem reuso de chave de API, nada que deixe contas
  marcadas. Cada CLI cuida da própria autenticação e cobrança.
- 💸 **Padrões de custo com fonte, depois *você* ajusta ao seu plano.** Pronto para uso, `ask_all`
  monta um conselho gratuito e nunca toca na cota da assinatura (Claude, GPT) nem em créditos pagos,
  a menos que você peça. Cada lane vem com um tier obtido dos planos publicados do fornecedor
  ([docs/COSTS.md](../COSTS.md), datado) — **nunca detectado a partir da sua conta, e rotulado como
  tal** — que você sobrescreve conforme as suas próprias assinaturas
  (`CLI_BRIDGE_<LANE>_COST=free|limited|paid`); num plano grande, marque todos como `free`, ou
  defina `CLI_BRIDGE_PROFILE=max`.
- 🔌 **Funciona a partir de qualquer host.** Acionando o Claude Code? Ele esconde a lane do Claude
  (sem perguntar a si mesmo) e expõe as demais. Acionando Codex ou opencode no lugar? Mesma história,
  detectada automaticamente a partir do handshake MCP.
- 🧩 **Adicione qualquer CLI — ou sua própria API — sem fork.** Lanes embutidas para Claude, GPT,
  Gemini, Mistral, Qwen, Copilot, Grok e opencode. Registre **a sua própria CLI a partir de um
  arquivo JSON**, ou envolva **a sua própria API** invocando `curl`. Zero código.
- 🧠 **Síntese do conselho.** `ask_all` pode fazer um modelo gratuito resumir onde os outros
  *concordam* e *discordam* — transforme três opiniões em uma decisão.
- 🔬 **Fluxos multi-modelo.** `review_diff` e `security_review` distribuem revisores **com papéis
  diversos** pelo conselho, depois consolidam + deduplicam em um único relatório ordenado por
  severidade. `debate` faz os modelos criticarem e revisarem uns aos outros ao longo de rodadas
  limitadas antes de um juiz concluir.
- ✍️ **Somente leitura por padrão, gravações sob demanda.** Opte por `agent: build` para fazer
  qualquer lane capaz de fato **editar arquivos** — ou escolha um `model` específico por chamada,
  incluindo um **irmão da sua própria família** (consulte o Opus 4.6 a partir do Claude Code 4.8).
- 🪶 **Retornos no estilo subagente.** Um delegado trabalha no próprio contexto e devolve um resumo;
  saídas enormes transbordam para um arquivo e só uma prévia volta, então o contexto do seu
  assistente permanece enxuto.
- 🔁 **Fallback automático.** `ask_cascade` tenta as lanes do mais barato → mais forte e avança
  quando uma esbarra em cota/auth/timeout — então uma lane morta se degrada com elegância em vez de
  te deixar na mão.
- 🩺 **Autoconsciente.** A telemetria local acompanha a saúde de cada lane e coloca uma lane em
  cooldown após falhas repetidas de cota/auth/timeout, para que `ask_all`/`ask_cascade` a contornem.
- 🎯 **Aprende a sua stack.** Avalie a resposta de uma lane de 1 a 5 com `rate_lane` e `ask_best`
  passa a preferir os modelos que realmente vencem cada tipo de tarefa **na sua máquina** — um sinal
  de qualidade local armazenado em sqlite que sobrevive ao `/compact` e a reinicializações. Não é um
  ranking público; são *os seus* resultados.
- 🧱 **Endurecido.** Timeouts matam toda a árvore de processos (sem órfãos queimando cota), o
  cancelamento pelo host mata o delegado, segredos são redigidos, erros são classificados
  (`quota` / `auth` / `timeout`) para que seu assistente saiba o que fazer em seguida. Funciona em
  macOS / Linux / Windows.
- 📐 **Medido, não afirmado.** "Mais modelos encontram mais bugs" é *falseável*, então o cli-bridge
  inclui o teste: `cli-bridge eval` põe um conselho contra um único modelo forte +
  auto-consistência com **orçamento de chamadas igual** sobre um corpus de bugs de raciocínio
  semeados, pontuados de forma determinística (sem juiz LLM). Ele reporta média ± dp com uma
  salvaguarda de "nenhuma diferença mensurável" e uma tabela de vitórias/derrotas por bug — e
  publica o resultado mesmo quando o conselho perde. Veja
  [BENCHMARKS.md § Qualidade](../BENCHMARKS.md#quality--does-a-council-actually-beat-one-strong-model).

### vs. outros MCPs multi-modelo

| | cli-bridge | gateways com chave de API | bridges por reuso de token |
|---|:---:|:---:|:---:|
| Ban-safe (invoca a CLI oficial) | ✅ | ➖ (suas chaves) | ❌ (risco de ToS) |
| Sem chaves de API para gerenciar | ✅ | ❌ | ✅ |
| Usa suas assinaturas existentes (conselho gratuito de $0.00) | ✅ | ❌ | ✅ |
| Tiers de custo por plano + teto diário rígido + cooldown | ✅ | ➖ | ❌ |
| Fallback automático (cascade) | ✅ | alguns | ❌ |
| Roteamento que **aprende com os seus resultados** | ✅ | ❌ | ❌ |
| Adicione qualquer CLI / sua própria API, sem fork | ✅ | ➖ | ❌ |
| Esconde a si mesmo o host que chama | ✅ | n/a | ➖ |
| Memória de mesa-redonda que sobrevive a um restart | ✅ | ➖ (em memória) | ➖ |
| Gravação agêntica segura (worktree → diff) | ✅ | ➖ | ❌ |
| Inclui uma avaliação de qualidade determinística (conselho vs único) | ✅ | ❌ | ❌ |

---

## Início rápido

### 1. Instalar

```bash
# zero-install run (recommended)
uvx cli-bridge-mcp

# or install it
uv tool install cli-bridge-mcp     # or: pipx install cli-bridge-mcp
```

Você só ganha uma lane para uma CLI que você **já instalou e na qual já fez login**. O cli-bridge
detecta automaticamente o que está no seu `PATH`. Rode a ferramenta `doctor` a qualquer momento para
ver o que está conectado (`doctor deep` até verifica ao vivo cada login).

| Lane | CLI | Custo (típico) |
|------|-----|------|
| `ask_claude`   | [Claude Code](https://docs.claude.com/claude-code) | assinatura |
| `ask_gpt`      | [OpenAI Codex](https://github.com/openai/codex) | assinatura |
| `ask_gemini`   | Gemini CLI (ou `agy` / Antigravity) | gratuito / assinatura |
| `ask_mistral`  | Mistral Vibe | tier gratuito |
| `ask_qwen` ⚗️  | Qwen Code | chave de API tarifada (tier OAuth gratuito encerrado em abr/2026) |
| `ask_copilot` ⚗️ | GitHub Copilot CLI | assinatura (créditos por uso desde 2026-06) |
| `ask_grok` ⚗️  | xAI Grok CLI | assinatura (SuperGrok / X Premium+) |
| `ask_opencode` | gateway [opencode](https://opencode.ai) (deepseek, qwen, glm, kimi…) | gratuito por padrão; alguns modelos usam créditos |

⚗️ = experimental (flags ainda não verificadas ao vivo — por favor, reporte quebras).
A coluna de custo = o *plano publicado típico* do fornecedor em junho de 2026 ([docs/COSTS.md](../COSTS.md)
tem limites, encerramentos e fontes) — o cli-bridge nunca detecta quanto uma lane custa *para você*;
declare o seu próprio plano com `CLI_BRIDGE_<LANE>_COST`.

### O conselho de $0 (sem nenhuma assinatura)

Sem plano pago, sem cartão? Você ainda pode montar um conselho multi-modelo de verdade em ~5 minutos
a partir de provedores com um **tier genuinamente gratuito e de parada rígida** (esgotamento = HTTP
429, uma cobrança é estruturalmente impossível — verificado em junho de 2026, fontes em
[docs/COSTS.md](../COSTS.md)):

```bash
# 1. Get free API keys (no card): console.groq.com · cloud.cerebras.ai ·
#    a GitHub PAT (models scope) · openrouter.ai/keys
export GROQ_API_KEY=... CEREBRAS_API_KEY=... GITHUB_MODELS_TOKEN=... OPENROUTER_API_KEY=...
# 2. Point cli-bridge at the ready-made lanes
export CLI_BRIDGE_LANES_FILE=/path/to/examples/free-apis.json
```

Isso é **Groq** (llama-3.3-70b, 1k req/dia) + **Cerebras** (gpt-oss-120b) + **GitHub Models** (toda
conta GitHub tem acesso gratuito) + a amplitude do **OpenRouter `:free`** — quatro vozes
independentes para `ask_all`/`consensus`/`debate`, mais os modelos gratuitos embutidos do opencode,
se instalado. Ressalvas: o tier gratuito do Gemini CLI **encerra em 2026-06-18**; tiers gratuitos
mudam em questão de semanas — confira [docs/COSTS.md](../COSTS.md) para o que era verdade no momento
da verificação.

### 2. Registre-o no seu host

É um servidor MCP stdio simples (`uvx cli-bridge-mcp`) — funciona em todo cliente MCP, e esconde
automaticamente a lane do host que está chamando (sem perguntar a si mesmo).

**Claude Code** — um comando:

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
<summary><b>VS Code</b> (<code>.vscode/mcp.json</code> ou configurações do usuário)</summary>

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
<summary><b>Warp</b> (Settings → AI → MCP servers)</summary>

```json
{ "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } }
```
</details>

### 3. Use-o

Basta conversar com seu assistente:

> *"Peça uma segunda opinião do Gemini sobre esta função."*
> *"Faça o conselho inteiro revisar meu diff e sintetizar onde discordam."* (→ `review_diff`)
> *"Faça o GPT pensar bem sobre esta condição de corrida."* (→ `effort: high`)
> *"Rode uma revisão de segurança nas minhas alterações em staging."* (→ `security_review`)
> *"Faça os modelos debaterem se precisamos desta abstração."* (→ `debate`)
> *"Peça ao gpt para implementar esta função."* (→ `agent: build`, edita arquivos)
> *"Peça ao Opus 4.6 para conferir meu raciocínio."* (modelo irmão, a partir do Claude Code)
> *"Escolha a melhor lane para uma revisão profunda — e lembre que aquela acertou em cheio."* (→ `ask_best` + `rate_lane`; na próxima vez ele roteia para lá primeiro)

Hosts que suportam prompts MCP também expõem `review_diff`, `security_review`, `debate`,
`premortem`, `test_plan`, `apilookup` e `cost_setup` como slash commands nativos.

---

## Ferramentas

| Ferramenta | O que faz |
|------|--------------|
| `ask_<lane>` | Pergunte a um modelo. Parâmetros: `task`, opcionalmente `model`, `effort`, `agent`, `cwd`, `timeout_s`, **`conversation`** (inicie/continue uma thread de mesa-redonda — veja abaixo). |
| `ask_all` | Distribui a mesma pergunta para toda lane gratuita e não limitada em paralelo. `synthesize: true` adiciona um resumo de concordância/discordância. `include_paid: true` para também consultar lanes limitadas/pagas. |
| `ask_cascade` | Pergunte a um modelo **com fallback automático** — tenta as lanes do mais barato → mais forte, pulando as em cooldown, avançando em caso de cota/auth/timeout. Retorna o primeiro sucesso + um rastro do que foi tentado (tier de custo, latência, por que foi pulado). |
| `ask_best` | Escolhe **uma lane por modo** (`fast`/`cheap`/`deep`/`code`/`review`/`security`) a partir de custo, saúde, latência medida **e suas próprias pontuações de `rate_lane`**, depois a roda com fallback. Para "apenas use o modelo certo" — `ask_all` compara, `ask_cascade` é simplesmente o-mais-barato-primeiro. |
| `rate_lane` | **Ensine o roteador.** Pontue a resposta de uma lane de 1 a 5 para um tipo de tarefa (`mode`) → `ask_best` passa a preferir as lanes que vencem esse modo **na sua máquina**. Armazenado em sqlite (sobrevive ao `/compact`/restart); um piso de duas avaliações antes de qualquer lane influenciar, para que o feedback seja honesto, não ruidoso. Cada resposta do `ask_best` imprime a chamada exata. |
| `route_plan` | Mostra a ordem que `ask_cascade` tentaria, dado o seu perfil + cooldowns atuais (somente leitura, não roda nada). Passe `mode` para pré-visualizar `ask_best` — incluindo a avaliação corrente de cada lane. |
| `ask_all_async` / `job_status` / `job_result` / `job_cancel` / `jobs_list` | Roda um fan-out como um **job em segundo plano** que retorna um id de job em <1s, para que uma execução lenta do conselho não esbarre no prazo de chamada de ferramenta do host. O cancelamento mata os grupos de processo dos delegados. |
| `review_diff` | Revisão de código multi-modelo de um diff git: as lanes revisam em paralelo com **focos diferentes** (correção / segurança / testes / manutenibilidade), cada uma retornando achados em JSON; pré-verificações determinísticas (segredos, shell perigoso) as alimentam; os achados **consolidam por arquivo/linha/título** com confiança baseada em concordância (single/majority/consensus). `output_format: markdown` (padrão) ou `json`. Parâmetros: `cwd`, `base` (padrão HEAD), `diff`, `include_paid`, `timeout_s`. |
| `security_review` | Revisão **apenas de segurança** ciente de OWASP de um diff git (injeção / auth & controle de acesso / segredos & cripto / exposição de dados & SSRF) → achados ordenados por severidade + uma seção `residual_risk`. |
| `debate` | Vários modelos respondem a uma pergunta, **veem as respostas uns dos outros e revisam** ao longo de rodadas limitadas (padrão 1, máx 3), depois um **juiz independente** (mantido fora do debate quando há 3+ lanes) escreve o consenso final + a discordância remanescente. Endurecido pelo uso em produção: `context_files` injeta arquivos-chave em cada prompt de debatedor (**grounding** — sem isso o conselho só parafraseia o seu briefing), uma **passada de fact-check** (lane gratuita, ligada por padrão) sinaliza comandos/tags/versões não verificáveis do veredito, as afirmações carregam tags de proveniência (`[brief]`/`[own-knowledge]`/`[verified]`), um briefing magro recebe um aviso do linter, e `steelman: true` faz uma lane argumentar *contra* um veredito unânime antes de o juiz reconcluir. `summary_only` descarta as posições completas (~60-80 % menos tokens); `dry_run` retorna um manifesto de dados de pré-voo (quais arquivos/chars vão para quais fornecedores) antes de qualquer coisa ser enviada. Parâmetros: `task`, `rounds`, `adversarial`, `context_files`, `fact_check`, `summary_only`, `allow_self_judge`, `steelman`, `dry_run`, `include_paid`, `cwd`, `timeout_s`. |
| `consensus` | O "conselho de LLMs" feito melhor: cada lane responde às cegas, depois **ranqueia as respostas anonimizadas** (sem favorecer a si mesma), os votos são agregados **deterministicamente** (contagem de Borda), e a **resposta nº 1 ranqueada pelos pares é retornada na íntegra** — porque *selecionar* a melhor resposta supera *misturá-las* (arXiv 2603.20324: a síntese preferida em 0/42 tarefas; a seleção vence, Glass's Δ≈2.07). `synthesize: true` opta por uma mistura de presidente (o modo mais fraco). Retorna a resposta final + uma tabela de ranqueamento por voto dos pares. `dry_run` retorna um manifesto de dados de pré-voo (quais arquivos/chars vão para quais fornecedores) sem invocar. Suporta grounding por `context_files` e `summary_only`. Parâmetros: `task`, `context_files`, `synthesize`, `summary_only`, `dry_run`, `include_paid`, `cwd`, `timeout_s`. |
| `challenge` | Entregue uma afirmação a **uma lane externa** com um prompt de reavaliação crítica → uma revisão cética independente (com uma salvaguarda de integridade — ela não vai fabricar discordância). Estresse-teste sua própria conclusão antes de agir. `lane` opcional. |
| `premortem` | Cada lane imagina que o plano **já fracassou** e lista os modos de falha prováveis + mitigações; consolidados em uma lista de riscos priorizada. Rode antes de construir. |
| `test_plan` | Deriva um **plano de testes** priorizado (comportamentos, casos limítrofes, casos concretos) a partir de um diff git ou de uma descrição. |
| `commit_msg` | Gera uma mensagem de **Conventional Commit** a partir do seu diff em staging (recorre à working tree). Somente leitura — emite texto, nunca commita. `lane`, `cwd` opcionais. |
| `pr_describe` | Gera um **título + descrição de PR** (Summary / Changes / Testing) a partir do diff do branch + log de commits vs uma base (padrão origin/main → main). Somente leitura. `base`, `lane`, `cwd` opcionais. |
| `ask_build` | **Encomende um build de verdade.** `mode=isolated` (padrão) edita um worktree descartável e devolve um **diff** — repo intacto. `mode=direct` faz o build direto em um diretório-alvo, protegido por git + um **contrato de zona** (o delegado só escreve dentro de `zone`; gravações fora da zona são detectadas e revertidas; o desfazer é por zona, nunca um reset global) — assim o host pode fazer o build de outras partes do **mesmo repo em paralelo**. `async=true` o torna **dirigível**. `dry_run` pré-visualiza o brief. (`ask_build_isolated` é um alias legado.) |
| `job_tail` / `build_steer` | **Acompanhe e dirija um build como um humano.** `job_tail(job_id, offset)` transmite o log de progresso (por offset de bytes). `build_steer(job_id, instruction, interrupt)` enfileira uma correção para o próximo turno, ou `interrupt=true` corta o turno atual (os arquivos já escritos são mantidos). Uma **Definition of Done** executável opcional (`dod_cmd`, uma lista argv) roda após cada turno — sucesso = pronto, falha = mais um turno com o erro reinjetado. |
| `batch_run` | **Fan-out durável**: roda muitas requisições independentes em paralelo em **uma só chamada** em vez de N (economiza contexto do host + cota). Cada resultado é registrado, então `resume_id` repete as tarefas já concluídas e roda só o restante — **sobrevive a um restart do servidor**. Disponível em `async`. |
| `workflow` | **Workflows multimodelo prontos** sobre o substrato de batch. **`refine_plan`** — deixe o conselho DEMOLIR seu plano sob ângulos distintos (passe `plan_file`; cada lane o lê, nunca recopiado). `council_review` (N lanes respondem a uma pergunta + juiz opcional), `map_review` (revisar vários arquivos em paralelo), `research_verify` (responder e então cruzar de forma adversarial). Todos retomáveis + em `async`. |
| `list_models` | Lista os modelos disponíveis de uma lane (parâmetro `lane`) onde a CLI os expõe; caso contrário, mostra o modelo padrão resolvido + como escolher um. (`list_<lane>_models` também existe para lanes com um comando de listagem nativo.) |
| `conversations_list` / `conversation_show` | Lista as **threads de mesa-redonda** recentes (recupera um id após um reset de contexto) / mostra a transcrição completa de uma thread, atribuída por lane. |
| `doctor` | Verificação de saúde: CLIs instaladas, host detectado, postura de custo/cota, cooldowns, padrões. `deep: true` sonda ao vivo a auth de cada lane gratuita **e verifica as flags de cada lane contra seu `--help`** — avisa se uma CLI renomeou/removeu uma flag da qual o cli-bridge depende (drift) antes de a lane falhar silenciosamente. |
| `usage_report` | Estatísticas apenas locais: execuções, sucesso/latência por lane, e tokens **estimados** (chars/4) + créditos (`CREDITS_PER_1K` por lane). `since`, `format=text\|json`. |
| `usage_budget` | Execuções de hoje por lane vs `CLI_BRIDGE_<LANE>_DAILY_LIMIT` + gasto estimado; sinaliza lanes acima do limite. |
| `lane_stats` | Saúde por lane: execuções, falhas, falhas/timeouts consecutivos, cooldown ativo. |
| `reset_lane_state` | Limpa os contadores de cooldown/falha de uma lane (após re-login ou reset de cota). |
| `setup` | Lista as lanes instaladas com seu custo típico-de-plano *com fonte* (free/limited/paid — nunca detectado a partir da sua conta), pergunta por quais você realmente paga, e **recomenda um perfil + teto diário** para confirmar — depois guia o usuário pelo processo. |

Há também uma **CLI para humanos** — o mesmo motor a partir do seu terminal ou CI:
`cli-bridge init` (detecta CLIs + imprime a configuração MCP), `doctor`, `ask <lane> <task>`,
`ask-all`, `ask-best --mode`, `review-diff --base origin/main --json`,
`bench --lane gemini --prompt … ` (latência p50/p95/p99), `usage`, `budget`, `jobs`,
`setup --write`. Veja `examples/github-action-pr-review.yml` para uma GitHub Action de revisão de PR
(runner auto-hospedado).

**Somente leitura por padrão; gravações opt-in.** Um delegado normalmente analisa e responde — seu
host aplica quaisquer edições. Passe `agent: "build"` para deixá-lo **editar arquivos diretamente**
(ex.: *"peça ao gpt para implementar esta função"*): claude → `--permission-mode acceptEdits`, gpt →
`--sandbox workspace-write`, mistral → `--agent accept-edits`, gemini → `--yolo` (ou `agy`
`--dangerously-skip-permissions`), opencode → `--agent build`. Lanes capazes de build são anotadas
como não-somente-leitura, e uma execução `build` nunca é servida do cache.

### Delegue um build de verdade — supervisionado, no seu repo

`ask_build` transforma um delegado em um colega que entrega um resultado **completo e real**, não só
um diff para copiar. Dois modos:

- **`mode=isolated`** (padrão, o mais seguro) — o delegado edita um worktree git descartável no HEAD;
  você recebe o diff e o aplica. Nada se mexe no seu repo.
- **`mode=direct`** — o delegado escreve **arquivos reais** em `target_dir`, para que você (o host)
  possa fazer o build de outras partes do **mesmo repo em paralelo** (p. ex. *"eu faço o backend,
  o codex faz `frontend/`"*). A segurança é por git + um **contrato de zona**, não por isolamento:
  - o brief diz ao delegado que ele só pode escrever **dentro de `zone`** (um caminho sob
    `target_dir`);
  - todo desfazer é **por zona** (`git checkout -- <zone>` + `git clean -fd <zone>`, nunca um
    `git reset --hard` global), então seu trabalho não commitado fora da zona nunca é tocado;
  - um **lock por zona** deixa zonas disjuntas fazerem build ao mesmo tempo mas bloqueia dois builds
    na mesma zona;
  - após cada turno um **`git status` global** detecta qualquer escrita fora da zona (escape via
    `../`, caminho absoluto, symlink) e **reverte o build** — o scoping do git protege as operações
    de git, não consegue isolar o subprocesso, então essa checagem é obrigatória. Um `target_dir`
    ausente/vazio é criado e inicializado com `git init`.

**Acompanhe e dirija.** Rode com `async=true` para obter um `job_id`, depois:

- `job_tail(job_id, offset)` transmite o progresso do build para você postar resumos por etapa;
- `build_steer(job_id, "use Tailwind, não CSS inline")` enfileira uma correção para o próximo turno;
  `build_steer(job_id, interrupt=true)` corta o turno atual (os arquivos escritos são mantidos);
- passe `dod_cmd` (uma **lista argv**, p. ex. `["npm","run","build"]`, nunca uma string de shell)
  para uma Definition of Done **testada de verdade** após cada turno — sucesso = pronto, falha = mais
  um turno com o erro reinjetado, limitado por `max_fail_retries` (padrão 3) e `max_turns` (12).

A continuidade é o sistema de arquivos (o delegado relê seus próprios arquivos a cada turno); a
transcrição bruta vive na sessão do próprio CLI delegado, enquanto o cli-bridge guarda o log por
etapas para o `job_tail`.

### Teste seu plano sob pressão antes de construir (`workflow refine_plan`)

O cli-bridge é forte em *demolir um plano* antes de você escrever código. `workflow
preset=refine_plan` envia seu plano para várias lanes, cada uma criticando-o sob um **ângulo
distinto** (falhas técnicas e modos de falha / lacunas / sobre-engenharia / sequenciamento), depois
agrupa os achados para você mesclar — ou passe `judge_lane` para uma única lista de patches
deduplicada e ordenada por severidade.

```jsonc
// uma chamada → N CLIs destroem o plano, cada um sob um ângulo diferente
{ "preset": "refine_plan", "plan_file": "docs/plan.md", "judge_lane": "gpt" }
```

Passe **`plan_file`** (um caminho), não o texto: cada lane lê o arquivo do seu próprio diretório de
trabalho, então o plano **nunca é recopiado em N prompts** — o padrão frugal em tokens para toda
revisão de artefatos (`map_review`, `review_diff`, `debate context_files` funcionam igual). Como todo
`workflow`/`batch_run`, é **retomável** (`resume_id` repete as tarefas concluídas após um restart) e
pode rodar em `async`.

**Escolha um modelo por chamada** com `model` (ex.: `model: "claude-opus-4-6"`). De dentro de um
host você pode até consultar um **modelo irmão da sua própria família** — `ask_<your-host>` aparece
como uma ferramenta separada que exige um `model` explícito, então a partir do Claude Code você pode
perguntar ao Opus 4.6 enquanto roda o 4.8. (O `agy` do Antigravity não tem flag de modelo por
chamada — ele usa o que as suas próprias configurações selecionam.)

**Conversas de mesa-redonda.** Passe `conversation: "new"` a qualquer `ask_<lane>` para iniciar uma
thread multi-turno; reutilize o id retornado — **mesmo em uma lane diferente** — para continuar.
Cada lane vê a transcrição compartilhada com os seus próprios turnos marcados como "You" e os outros
nomeados, para que um conselho possa construir sobre o que já foi dito em vez de começar frio toda
vez. A transcrição é armazenada localmente (sqlite), então uma thread **sobrevive ao reset de
contexto do host (`/compact`) e a um restart do servidor** — recupere uma com `conversations_list`,
leia-a com `conversation_show`. Uma janela deslizante (`CLI_BRIDGE_CONVO_MAX_CHARS`, padrão 32000)
mantém os turnos mais novos e descarta os mais antigos, para que o custo por turno permaneça limitado
por quanto tempo a thread rodar.

Para o opencode, um `model` vazio pergunta ao `opencode models` pela lista atual `opencode/*-free` e
usa uma (o tier de $0 com rate-limit), escolhida por padrão + ordenada — nunca um nome fixado, então
um modelo gratuito aposentado é substituído automaticamente. É **cost-safe**: um modelo Zen
`opencode/*` puro cobra por token (custo de API) e `opencode-go/*` gasta créditos pré-pagos, então o
padrão nunca seleciona silenciosamente um modelo pago — passe-os explicitamente quando você os
quiser. Se a busca falhar, ele recorre a uma semente gratuita; defina `CLI_BRIDGE_OPENCODE_MODEL`
para fixar o seu próprio padrão.

`ask_all` mantém as chamadas por lane curtas (45s padrão, 60s máx) para que o host MCP receba uma
resposta antes do seu próprio prazo de chamada de ferramenta. Para uma resposta lenta/profunda,
chame essa lane diretamente com um `timeout_s` maior.

---

## Configuração

Tudo é variável de ambiente — sem edições de código. Ajuste às **suas** assinaturas:

| Variável | Efeito |
|----------|--------|
| `CLI_BRIDGE_<LANE>_COST` | `free`, `limited` ou `paid`. `free` entra no `ask_all`; `limited` é sensível a cota e pulada por fan-out amplo; `paid` gasta dinheiro/créditos e é pulada por padrão. |
| `CLI_BRIDGE_<LANE>_ENABLED` | `false` para esconder uma lane mesmo que sua CLI esteja instalada. |
| `CLI_BRIDGE_<LANE>_BIN` | Aponte uma lane para um binário diferente (ex.: `CLI_BRIDGE_GEMINI_BIN=agy`). |
| `CLI_BRIDGE_<LANE>_MODEL` | Modelo padrão de uma lane quando o chamador não passa um. |
| `CLI_BRIDGE_PROFILE` | `saver`, `balanced` ou `max`. `max` inclui lanes limitadas/pagas no `ask_all` a menos que o chamador sobrescreva `include_paid`. |
| `CLI_BRIDGE_HOST` | Força a identidade do host (qual lane esconder). Normalmente detectada automaticamente. |
| `CLI_BRIDGE_LANES_FILE` | Caminho para um arquivo JSON que adiciona **suas próprias** CLIs/APIs como lanes. |
| `CLI_BRIDGE_DISABLED_TOOLS` | Nomes de ferramentas separados por vírgula a esconder da listagem (ex.: `debate,premortem,test_plan`) — enxuga o contexto de schema que todo host paga por requisição. `doctor`/`setup` não podem ser escondidos. |
| `CLI_BRIDGE_ENABLED_TOOLS` | Allowlist para um **modo enxuto** de uma só env: quando definida, apenas essas ferramentas (+ `doctor`/`setup`) são expostas (ex.: `ask_best,ask_all,review_diff`). |
| `CLI_BRIDGE_<LANE>_PRIORITY` | Menor roda mais cedo no `ask_cascade` (padrão 50). Fixe a sua ordem preferida. |
| `CLI_BRIDGE_INLINE_MAX_CHARS` | Acima disso, uma resposta transborda para um arquivo em vez de inundar o contexto (padrão 12000). |
| `CLI_BRIDGE_TERSE` | `off` / `lite` (padrão) / `full` / `ultra`. Prepende um preâmbulo compacto de estilo de resposta aos prompts dos delegados (em inglês, raciocine internamente por completo, responda de forma concisa, código/JSON intocado) para cortar tanto o seu contexto quanto os tokens de saída do delegado. Nunca aplicado a ferramentas de fluxo estruturado. |
| `CLI_BRIDGE_TERSE_MIN_CHARS` | Pula o preâmbulo terse para tarefas mais curtas que essa quantidade de chars (padrão `0` = nunca pula). Tarefas minúsculas não conseguem compensar o custo fixo do preâmbulo. |
| `CLI_BRIDGE_GUARD` | `off` / `warn` (padrão) / `strict`. Escaneia a **saída do delegado** em busca de prompt-injection / tool-poisoning; `warn` prepende um banner, `strict` retém o corpo. Roda após a redação de segredos. |
| `CLI_BRIDGE_MOCK` | `1` = dry-run: as lanes reportam-se instaladas e retornam uma resposta pré-fabricada sem invocar nenhuma CLI. Experimente a ferramenta inteira com **zero CLIs instaladas**. |
| `CLI_BRIDGE_RETRIES` | Retentativas em uma falha TRANSIENTE (padrão 1). Faz uma CLI instável funcionar de primeira; cota/auth/not-found/timeout nunca são retentadas. |
| `CLI_BRIDGE_TRACE_DIR` | Se definida, cada delegação grava aqui um trace JSON redigido (argv, timing, saída) — debug/auditoria reproduzível. Desligada por padrão. |
| `CLI_BRIDGE_MAX_PARALLEL` | Teto de invocações simultâneas de delegados no `ask_all` (padrão 6). Impede que um conselho amplo (muitas lanes customizadas) cause OOM numa máquina pequena ou estoure a cota. |
| `CLI_BRIDGE_DAILY_CREDIT_CAP` | Teto rígido de gasto pago *estimado* por dia UTC. >0 recusa uma lane paga assim que a estimativa de hoje o atinge — torna o "cost-safe" aplicável, não apenas reportado. Lanes gratuitas nunca são barradas. |
| `CLI_BRIDGE_ALLOW_LANES` | Allowlist, ex.: `gemini,gpt`. Vazia = todas. Setups bloqueados / de equipe: apenas estas lanes são expostas. |
| `CLI_BRIDGE_DISABLE_BUILD` | `1` força todo delegado a somente-leitura (plan) mesmo que um chamador peça `agent: build`. Para máquinas compartilhadas. |
| `CLI_BRIDGE_OVERFLOW_MAX_FILES` | Teto na contagem de arquivos do dir de overflow (padrão 200); os mais antigos além disso são podados para que `/tmp` não cresça sem limite. |
| `CLI_BRIDGE_CONFIG_FILE` | Caminho para um config JSON (padrão `~/.config/cli-bridge/config.json`). Uma alternativa mais amigável às env vars — **a env sempre vence**. Veja abaixo. |
| `CLI_BRIDGE_CACHE_TTL_S` | `0` = off (padrão). Quando `>0`, uma chamada idêntica dentro desse número de segundos retorna a resposta em cache em vez de reinvocar a CLI (economiza cota/créditos em repetições; execuções de build nunca são cacheadas). |
| `CLI_BRIDGE_<LANE>_CREDITS_PER_1K` | Créditos por 1k tokens de uma lane, usado por `usage_report`/`usage_budget` para **estimar** o gasto (chars/4). |
| `CLI_BRIDGE_<LANE>_DAILY_LIMIT` | Máximo de execuções/dia de uma lane; `usage_budget` sinaliza quando excedido. |
| `CLI_BRIDGE_<LANE>_MIN_INTERVAL_S` | Pacing anti-burst de invocação: segundos mínimos entre invocações desta lane (padrão `0` = off). Defina-o (ex.: `2`) quando um tier gratuito aplica rate-limit sob chamadas seguidas — bursts da mesma lane ficam uniformemente espaçados, outras lanes seguem paralelas. `lane_stats` dá dicas quando uma lane mostra o padrão de rate-limit. |
| `CLI_BRIDGE_KEEP_WORKTREES` | Mantém os worktrees do `ask_build_isolated` em vez de descartá-los (para inspeção). |
| `CLI_BRIDGE_REVIEW_TIMEOUT_S` | Timeout por revisor para `review_diff` / `security_review` (padrão 180; estes são deliberadamente mais pesados que `ask_all`). |
| `CLI_BRIDGE_OVERFLOW_TTL_H` | Horas antes de um arquivo de overflow transbordado ser podado (padrão 24). |
| `CLI_BRIDGE_TELEMETRY` | `off` para desabilitar o log de execução local / rastreamento de cooldown (padrão ligado, apenas local à máquina). |
| `CLI_BRIDGE_TRACE_FOOTER` | `off` esconde o rodapé JSON `## Trace` nos relatórios de fluxo — mais agradável para humanos lendo-os num terminal; hosts MCP normalmente o querem (padrão ligado). |
| `CLI_BRIDGE_STATE_DB` | Caminho para o DB de estado sqlite local (padrão `~/.local/share/cli-bridge/state.sqlite`). |
| `CLI_BRIDGE_STORE_TRANSCRIPTS` | `true` para manter uma prévia mais longa da tarefa na telemetria (padrão: apenas hash + prévia de 60 chars). |
| `CLI_BRIDGE_LOG` / `_LOG_FILE` | `debug`/`info` para logar o que rodou onde (padrão: silencioso). |

### Arquivo de configuração (em vez de um muro de env vars)

Prefere um arquivo? Coloque `~/.config/cli-bridge/config.json` (ou aponte `CLI_BRIDGE_CONFIG_FILE`
para um). Ele preenche qualquer env var que você não tenha definido — **o ambiente sempre vence**, e
os padrões ainda funcionam sem arquivo algum:

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

### Adicione a sua própria CLI (sem fork)

`my-lanes.json`, depois `CLI_BRIDGE_LANES_FILE=/path/to/my-lanes.json`:

```json
[
  {
    "key": "aider", "display": "Aider", "bin": "aider",
    "ask": ["--message", "{task}"], "model_flag": "--model",
    "client_ids": ["aider"], "note": "Aider one-shot via --message."
  }
]
```

Agora você tem uma ferramenta `ask_aider`. (Uma lane customizada com uma chave embutida, ex.: `grok`,
*sobrescreve* a embutida — útil quando as flags da sua instalação diferem.)

**O ecossistema mais amplo, pronto para plugar:** `examples/community-lanes.json` traz lanes de
melhor esforço para **Aider, Goose, Plandex, Amp, Crush, Amazon Q Developer CLI e Droid (Factory)** —
todas marcadas como experimentais e `limited` (mantidas fora de fan-out amplo até *você* declarar
quanto custam para você), e todas cobertas pela verificação de drift de flags do `doctor deep`, que
valida cada lane contra o `--help` da própria CLI na *sua* máquina antes que algo quebre
silenciosamente. Claude Code, Codex, Gemini + Antigravity (`agy`), opencode, Qwen Code, Copilot e
Grok já são embutidos. Qualquer outra coisa (Cline, OpenHands, Continue, Roo/Kilo Code, Kimi K2
CLI, …) está a 3 linhas de JSON de distância — e qualquer uma dessas CLIs que fala MCP pode ficar do
*outro* lado também, rodando o cli-bridge como seu servidor.

### Traga a sua própria API (sem CLI necessária)

Envolva qualquer endpoint compatível com OpenAI invocando `curl`. Sua chave fica numa env var, nunca
no arquivo. `{task_json}` é o prompt, com escape JSON:

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

O par `--variable %MY_API_KEY` + `--expand-header` (curl ≥ 8.3) importa a chave *dentro* do curl —
ela nunca aparece na lista de processos. O `doctor` avisa se uma lane customizada expande um segredo
`${ENV}` para o argv em vez disso.

(Veja `examples/` para ambos, prontos para copiar.)

---

## Como funciona

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
              hides the host's own lane · only shows installed, enabled CLIs
              kills the whole process tree on timeout / cancellation
              redacts secrets · classifies errors · spills huge output to a file
```

Nenhuma chamada de rede própria. Nenhuma chave armazenada. Ele roda os mesmos binários em que você já
confia, no seu diretório de trabalho, e devolve a resposta.

### Funciona em hosts MCP de IDE também

O cli-bridge é puro MCP via stdio, então qualquer host capaz de MCP funciona — não apenas CLIs de
terminal. Aponte Cursor / VS Code (Cline, Continue) / Zed para o **mesmo comando** (`uvx
cli-bridge-mcp`, ou `<python> -m cli_bridge`). A própria lane do host é escondida automaticamente;
todo o resto é idêntico.

### Limitações conhecidas (lista honesta)

- **Ban-safe depende dos ToS de cada provedor.** O cli-bridge só roda a CLI oficial que você rodaria
  à mão — mas o uso não-interativo/automatizado não é *garantidamente* sancionado e pode mudar. Use
  suas próprias contas dentro dos termos delas; trate "ban-safe" como "sem extração de token/chave",
  não como uma garantia geral.
- **Jobs assíncronos são in-process.** Um restart do servidor marca os jobs em execução como
  `interrupted`. `batch_run` e `workflow` são a exceção — eles registram cada tarefa, então um
  `resume_id` repete as concluídas e roda só o restante após um restart.
- **Armadilhas de PATH por wrapper de shell.** Se seu shell envolve as CLIs delegadas em uma função
  ou alias (p. ex. uma guarda tipo `_opsec` no `.zshrc`), rodar o cli-bridge *a partir desse shell*
  pode quebrar — mas o cli-bridge lança o **binário diretamente** (sem shell), então não é afetado;
  só importa um wrapper que oculte o binário no `PATH`. `doctor` mostra o caminho resolvido por lane.
- **A guarda de injeção é heurística.** Ela pega padrões de alto sinal, não tudo; no modo `warn` o
  texto ainda chega ao host (trate a saída do delegado como dados).
- **Os números de token/crédito são estimativas** (chars/4 + o seu `CREDITS_PER_1K`), nunca exatos.
- **Lanes BYO-API (curl):** uma chave `${ENV}` é substituída no argv, então ela pode aparecer na
  lista de processos desta máquina enquanto a chamada roda (nunca é logada — os traces a redigem).
  Prefira a CLI própria de um provedor quando possível; para curl, um arquivo de header
  (`curl -H @file`) evita a exposição no argv.
- **Lanes experimentais** (`qwen`, `copilot`, `grok`): as flags não são verificadas ao vivo — reporte
  quebras.
- **Tiers de custo são padrões com fonte, não detecção** — fatos de plano de fornecedor datados de
  junho de 2026 ([docs/COSTS.md](../COSTS.md)); planos/cotas mudam, o `doctor` avisa quando o
  snapshot está desatualizado.
- **Host em sandbox:** se o seu host roda o servidor em um sandbox estrito (FS somente leitura / sem
  rede), as CLIs invocadas o herdam e podem falhar ao alcançar seus provedores. O cli-bridge expõe
  isso como um erro `auth`/`failed` em vez de travar.

---

## Desenvolvimento

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration (cross-host) tests
```

## Licença

MIT

---

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../assets/mark-dark.svg">
  <img src="../../assets/mark-light.svg" width="84" alt="cli-bridge">
</picture>

<sub>um lado · conectado a um conselho</sub>

</div>
