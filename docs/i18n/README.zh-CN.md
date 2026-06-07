<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../assets/banner-dark.svg">
  <img src="../../assets/banner-light.svg" width="860" alt="你 → cli-bridge → 一众 AI CLI 并行组成的评审团 → 一份合并后的评审">
</picture>

[English](../../README.md) · [Français](README.fr.md) · **简体中文** · [Español](README.es.md) · [Português (BR)](README.pt-BR.md) · [日本語](README.ja.md) · [Deutsch](README.de.md)

</div>

_英文版 README 为权威版本；本译文可能滞后于英文版。_

# cli-bridge

![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/cli-bridge-mcp)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**你的 AI 助手，但它能「打电话求助朋友」。**

`cli-bridge` 是一个 [Model Context Protocol](https://modelcontextprotocol.io) 服务器，它
**调度你早已安装并登录的那些 AI CLI** —— Claude Code、Codex、
Gemini CLI、opencode…… —— 直接从你正在对话的那个助手里调用。不需要 API key，不做 token
提取，日志只存本地，硬性成本上限，写入只以一次性 worktree 的 diff 形式呈现。
这部分纯粹是无可争议的「管道工程」；下面才是它真正解锁的东西：

被某个棘手的 bug 卡住了？让你的助手同时去问 GPT *和* Gemini，再做对比。需要对一个超大文件做
1M token 的通读？交给 Gemini。想要一个便宜的第二意见？丢给一个免费模型。一个问题，所有模型，
并排呈现 —— 全程不离开你的终端。

```
You → Claude:  "ask the council whether this auth logic is safe"
Claude → cli-bridge → [ Gemini ] [ GPT ] [ Mistral ] [ Qwen ] … in parallel
            ← three independent reviews + a synthesis of where they agree & disagree
```

<div align="center">

<img src="../../assets/demo.gif" width="860" alt="cli-bridge security-review 演示：一处已提交的鉴权绕过被两个模型独立发现，合并成一份按严重程度排序的报告，在免费通道上花费 $0">

_真实运行（2.5 倍速）：一处已提交的鉴权绕过 —— `security-review` 把 OWASP 各角色并行分发到多个免费
模型上；两个模型各自独立把它标为 **blocker**，而 `usage` 把账单凭证摆出来。_
_由 [vhs](https://github.com/charmbracelet/vhs) 生成 —— [查看源码](../demo/)。_

</div>

> **一句话说清它为什么不一样：** 它从不持有任何 API key，也从不提取任何 token —— 它驱动的是你
> **早已安装并登录** 的官方 CLI。一个免费通道评审团的花费是
> **$0.00**（凭证就在 `usage_report` 里）；付费通道只会在 *你* 设定的硬性每日上限内运行。
> 而当你要它真正去 *干活* 时，它会在一个一次性的 git worktree 里编辑，然后把
> **diff** 交还给你 —— 你的实际仓库从不被触碰。

> **再说点实话：**「模型越多越好」其实很 *脆弱* —— 大模型共享训练数据，
> 所以它们的错误是相关的。我们对自己的核心论断做了实测（`cli-bridge eval`，已随附，无 LLM
> 评判员）：一个多元化的评审团并 **没有** 比单个强模型抓到更多 bug —— 它把误报削减了
> **约 2 倍**。无论结果如何我们都照实公布（[BENCHMARKS.md](../BENCHMARKS.md)），而且这套
> 测试框架也一并随附，方便你在 *你自己的* CLI 上跑一遍。

---

## 为什么选这一个

市面上还有其他「调用别的模型」的 MCP。下面是 cli-bridge 的不同之处：

- 🛡️ **设计上就防封号。** 它启动的是每个模型的 **官方 CLI** —— 跟你手动运行的方式一模一样。
  没有 OAuth token 提取，没有 API key 复用，没有任何会让账号被标记的东西。每个 CLI 各自处理
  自己的鉴权与计费。
- 💸 **有来源的成本默认值，然后由 *你* 按自己的套餐微调。** 开箱即用时 `ask_all` 会组建一个
  免费评审团，除非你明确要求，否则绝不动用订阅额度（Claude、GPT）或付费积分。
  每个通道都自带一个来自厂商公开套餐的档位
  （[docs/COSTS.md](../COSTS.md)，附日期）—— **绝不从你的账号检测得来，并且会如实标注** ——
  你可以按自己的订阅情况逐个覆盖
  （`CLI_BRIDGE_<LANE>_COST=free|limited|paid`）；如果你用的是大套餐，把它们全标成 `free`，
  或者设置 `CLI_BRIDGE_PROFILE=max`。
- 🔌 **从任何宿主里都能用。** 在驱动 Claude Code？它会隐藏 Claude 通道（你不会自己问自己），
  并暴露其余的。改成驱动 Codex 或 opencode？同样的逻辑，从 MCP 握手中自动检测。
- 🧩 **接入任何 CLI —— 或你自己的 API —— 无需 fork。** 内置 Claude、GPT、Gemini、
  Mistral、Qwen、Copilot、Grok 和 opencode 的通道。**用一个 JSON 文件注册你自己的 CLI**，或者
  通过启动 `curl` 来包装 **你自己的 API**。零代码。
- 🧠 **评审团综合。** `ask_all` 可以让一个免费模型来归纳其他模型在哪些地方 *一致*、在哪些地方
  *分歧* —— 把三份意见变成一个决定。
- 🔬 **多模型工作流。** `review_diff` 和 `security_review` 把 **角色多元化** 的评审者分发到整个
  评审团，然后合并 + 去重成一份按严重程度排序的报告。`debate` 让模型在有限轮次里相互批评、相互
  修订，最后由一名评判员下结论。
- ✍️ **默认只读，按需写入。** 通过 `agent: build` 选项，让任意有能力的通道真正去 **编辑文件**
  —— 或者逐次调用时挑选某个具体的 `model`，包括 **你自己家族里的兄弟模型**（从 Claude Code 4.8
  里调用 Opus 4.6）。
- 🪶 **子代理式的返回。** 一个被委托的代理在它自己的上下文里干活，然后交回一份摘要；体量巨大的
  输出会溢出到文件，只返回一段预览，这样你的助手上下文就能保持精简。
- 🔁 **自动回退。** `ask_cascade` 按「最便宜 → 最强」的顺序逐个尝试通道，某个通道一旦撞上
  额度/鉴权/超时就跳过继续 —— 这样一个挂掉的通道会优雅降级，而不是直接让你失败。
- 🩺 **自我感知。** 本地遥测跟踪每个通道的健康状况，在反复出现额度/鉴权/超时失败后把通道置入
  冷却，于是 `ask_all`/`ask_cascade` 会绕开它路由。
- 🎯 **学习你的技术栈。** 用 `rate_lane` 给一个通道的答案打 1–5 分，`ask_best` 就会偏向
  那些在 **你这台机器上** 确实赢下每类任务的模型 —— 一个存在 sqlite 里、能挺过 `/compact` 和
  重启的本地质量信号。这不是公开排行榜；是 *你自己的* 结果。
- 🧱 **加固过。** 超时会杀掉整棵进程树（不留下消耗额度的孤儿进程），宿主取消会杀掉被委托方，
  机密会被脱敏，错误会被分类
  （`quota` / `auth` / `timeout`）这样你的助手就知道下一步该怎么办。可在
  macOS / Linux / Windows 上运行。
- 📐 **是实测，不是断言。**「更多模型能找到更多 bug」是可 *证伪* 的，所以 cli-bridge
  随附了那套测试：`cli-bridge eval` 在 **同等调用预算** 下，让一个评审团对阵单个强模型 +
  自一致性，在一个植入了推理 bug 的语料库上较量，按确定性方式打分（无 LLM
  评判员）。它报告均值 ± 标准差，带一个「无可测量差异」的护栏，以及一张逐 bug 的胜负
  表 —— 即便评审团输了也照样公布结果。详见
  [BENCHMARKS.md § 质量](../BENCHMARKS.md#quality--does-a-council-actually-beat-one-strong-model)。

### 对比其他多模型 MCP

| | cli-bridge | API-key 网关 | token 复用桥 |
|---|:---:|:---:|:---:|
| 防封号（启动官方 CLI） | ✅ | ➖（用你的 key） | ❌（违反 ToS 风险） |
| 无需管理 API key | ✅ | ❌ | ✅ |
| 使用你已有的订阅（$0.00 免费评审团） | ✅ | ❌ | ✅ |
| 按套餐分档成本 + 硬性每日上限 + 冷却 | ✅ | ➖ | ❌ |
| 自动回退（级联） | ✅ | 部分 | ❌ |
| **从你的结果中学习** 的路由 | ✅ | ❌ | ❌ |
| 接入任何 CLI / 你自己的 API，无需 fork | ✅ | ➖ | ❌ |
| 自动隐藏调用方宿主 | ✅ | 不适用 | ➖ |
| 能挺过重启的圆桌记忆 | ✅ | ➖（仅内存） | ➖ |
| 安全的代理式写入（worktree → diff） | ✅ | ➖ | ❌ |
| 随附确定性质量评测（评审团 vs 单模型） | ✅ | ❌ | ❌ |

---

## 快速开始

### 1. 安装

```bash
# zero-install run (recommended)
uvx cli-bridge-mcp

# or install it
uv tool install cli-bridge-mcp     # or: pipx install cli-bridge-mcp
```

只有你 **早已安装并登录** 的 CLI 才会得到一个通道。cli-bridge 会自动检测你 `PATH` 上有什么。
任何时候运行 `doctor` 工具都能看到接好了哪些（`doctor deep` 甚至会实时检查每个登录态）。

| 通道 | CLI | 成本（典型） |
|------|-----|------|
| `ask_claude`   | [Claude Code](https://docs.claude.com/claude-code) | 订阅 |
| `ask_gpt`      | [OpenAI Codex](https://github.com/openai/codex) | 订阅 |
| `ask_gemini`   | Gemini CLI（或 `agy` / Antigravity） | 免费 / 订阅 |
| `ask_mistral`  | Mistral Vibe | 免费档 |
| `ask_qwen` ⚗️  | Qwen Code | 按量计费 API key（免费 OAuth 档已于 2026 年 4 月关闭） |
| `ask_copilot` ⚗️ | GitHub Copilot CLI | 订阅（自 2026-06 起按用量计积分） |
| `ask_grok` ⚗️  | xAI Grok CLI | 订阅（SuperGrok / X Premium+） |
| `ask_opencode` | [opencode](https://opencode.ai) 网关（deepseek、qwen、glm、kimi…） | 默认免费；部分模型消耗积分 |

⚗️ = 实验性（参数尚未实测验证 —— 出问题请反馈）。
成本列 = 截至 2026 年 6 月厂商的 *典型公开套餐*（[docs/COSTS.md](../COSTS.md)
列有限额、停服日期和来源）—— cli-bridge 从不检测某个通道对 *你* 的实际花费；请用
`CLI_BRIDGE_<LANE>_COST` 声明你自己的套餐。

### 零成本评审团（完全不需要任何订阅）

没有付费套餐，也没有银行卡？你照样能在约 5 分钟内，从那些拥有 **真正免费、硬性熔断档** 的
提供方组建起一个真正的多模型评审团（额度耗尽 = HTTP 429，结构上不可能产生账单 ——
已于 2026 年 6 月验证，来源见 [docs/COSTS.md](../COSTS.md)）：

```bash
# 1. Get free API keys (no card): console.groq.com · cloud.cerebras.ai ·
#    a GitHub PAT (models scope) · openrouter.ai/keys
export GROQ_API_KEY=... CEREBRAS_API_KEY=... GITHUB_MODELS_TOKEN=... OPENROUTER_API_KEY=...
# 2. Point cli-bridge at the ready-made lanes
export CLI_BRIDGE_LANES_FILE=/path/to/examples/free-apis.json
```

这就是 **Groq**（llama-3.3-70b，每天 1k 次请求）+ **Cerebras**（gpt-oss-120b）+ **GitHub Models**
（每个 GitHub 账号都有免费访问权）+ **OpenRouter `:free`** 的广度 —— 四个独立的
声音供 `ask_all`/`consensus`/`debate` 使用，外加 opencode 内置的免费模型（如已安装）。
注意事项：Gemini CLI 的免费档 **将于 2026-06-18 停服**；免费档动辄数周内更替 —— 请查阅
[docs/COSTS.md](../COSTS.md) 了解验证时点的实际情况。

### 2. 在你的宿主里注册它

它是一个纯粹的 stdio MCP 服务器（`uvx cli-bridge-mcp`）—— 在每一个 MCP 客户端里都能用，而且它会
自动隐藏调用方那个宿主的通道（你不会自己问自己）。

**Claude Code** —— 一条命令：

```bash
claude mcp add cli-bridge -- uvx cli-bridge-mcp
```

[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_cli--bridge-0098FF?logo=githubcopilot&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=cli-bridge&config=%7B%22name%22%3A%22cli-bridge%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22cli-bridge-mcp%22%5D%7D)
[![Install in Cursor](https://img.shields.io/badge/Cursor-Install_cli--bridge-111111?logo=cursor&logoColor=white)](https://cursor.com/en/install-mcp?name=cli-bridge&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJjbGktYnJpZGdlLW1jcCJdfQ==)

<details>
<summary><b>Claude Desktop</b>（<code>claude_desktop_config.json</code>）</summary>

```json
{ "mcpServers": { "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } } }
```
</details>

<details>
<summary><b>Codex</b>（<code>~/.codex/config.toml</code>）</summary>

```toml
[mcp_servers.cli-bridge]
command = "uvx"
args = ["cli-bridge-mcp"]
```
</details>

<details>
<summary><b>Cursor</b>（<code>~/.cursor/mcp.json</code>）</summary>

```json
{ "mcpServers": { "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } } }
```
</details>

<details>
<summary><b>VS Code</b>（<code>.vscode/mcp.json</code> 或用户设置）</summary>

```json
{ "servers": { "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } } }
```
</details>

<details>
<summary><b>Gemini CLI</b>（<code>~/.gemini/settings.json</code>）</summary>

```json
{ "mcpServers": { "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } } }
```
</details>

<details>
<summary><b>opencode</b>（<code>opencode.json</code>）</summary>

```json
{ "mcp": { "cli-bridge": { "type": "local", "command": ["uvx", "cli-bridge-mcp"] } } }
```
</details>

<details>
<summary><b>Windsurf</b>（<code>~/.codeium/windsurf/mcp_config.json</code>）</summary>

```json
{ "mcpServers": { "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } } }
```
</details>

<details>
<summary><b>Warp</b>（Settings → AI → MCP servers）</summary>

```json
{ "cli-bridge": { "command": "uvx", "args": ["cli-bridge-mcp"] } }
```
</details>

### 3. 使用它

直接跟你的助手说话就行：

> *"Ask Gemini for a second opinion on this function."*
> *"Have the whole council review my diff and synthesize where they disagree."*（→ `review_diff`）
> *"Get GPT to think hard about this race condition."*（→ `effort: high`）
> *"Run a security review on my staged changes."*（→ `security_review`）
> *"Make the models debate whether we need this abstraction."*（→ `debate`）
> *"Ask gpt to implement this function."*（→ `agent: build`，会编辑文件）
> *"Ask Opus 4.6 to double-check my reasoning."*（兄弟模型，从 Claude Code 里调用）
> *"Pick the best lane for a deep review — and remember that one nailed it."*（→ `ask_best` + `rate_lane`；下次它会优先路由到那里）

支持 MCP prompts 的宿主还会把 `review_diff`、`security_review`、`debate`、
`premortem`、`test_plan`、`apilookup` 和 `cost_setup` 暴露为原生的斜杠命令。

---

## 工具

| 工具 | 它做什么 |
|------|--------------|
| `ask_<lane>` | 问一个模型。参数：`task`、可选 `model`、`effort`、`agent`、`cwd`、`timeout_s`、**`conversation`**（开启/继续一个圆桌线程 —— 见下文）。 |
| `ask_all` | 把同一个问题并行分发给每个免费、非受限的通道。`synthesize: true` 会附加一份一致/分歧摘要。`include_paid: true` 则也查询受限/付费通道。 |
| `ask_cascade` | 问一个模型 **并自动回退** —— 按「最便宜 → 最强」逐个尝试通道，跳过冷却中的，遇到额度/鉴权/超时就继续下一个。返回第一个成功结果 + 一份尝试轨迹（成本档、延迟、为何跳过）。 |
| `ask_best` | 根据成本、健康度、实测延迟 **以及你自己的 `rate_lane` 评分**，**按模式**（`fast`/`cheap`/`deep`/`code`/`review`/`security`）挑选 **一个通道**，然后带回退地运行它。适用于「就给我用对的那个模型」—— `ask_all` 是做对比，`ask_cascade` 则是单纯的最便宜优先。 |
| `rate_lane` | **教会路由器。** 针对某类任务（`mode`）给一个通道的答案打 1–5 分 → `ask_best` 此后就偏向那些在 **你这台机器上** 赢下该模式的通道。存在 sqlite 里（挺过 `/compact`/重启）；任何通道被导向之前需要至少两条评分作为门槛，让反馈诚实而不嘈杂。每个 `ask_best` 答案都会打印出确切的调用。 |
| `route_plan` | 给定你的 profile + 当前冷却状态，显示 `ask_cascade` 会以什么顺序尝试（只读，什么都不运行）。传入 `mode` 可预览 `ask_best` —— 包括每个通道当前的滚动评分。 |
| `ask_all_async` / `job_status` / `job_result` / `job_cancel` / `jobs_list` | 把一次分发作为 **后台作业** 运行，1 秒内返回一个作业 id，这样一次缓慢的评审团运行就不会撞上宿主的工具调用截止时限。取消会杀掉被委托方的进程组。 |
| `review_diff` | 对一个 git diff 做多模型代码评审：各通道以 **不同侧重点**（正确性 / 安全 / 测试 / 可维护性）并行评审，各自返回 JSON 形式的 findings；确定性预检（机密、危险 shell）为它们打底；findings 会 **按文件/行/标题合并**，并带上基于一致程度的置信度（single/majority/consensus）。`output_format: markdown`（默认）或 `json`。参数：`cwd`、`base`（默认 HEAD）、`diff`、`include_paid`、`timeout_s`。 |
| `security_review` | 对一个 git diff 做带 OWASP 意识的 **纯安全** 评审（注入 / 鉴权与访问控制 / 机密与加密 / 数据暴露与 SSRF）→ 按严重程度排序的 findings + 一个 `residual_risk` 章节。 |
| `debate` | 若干模型回答一个问题，在有限轮次里（默认 1，最多 3）**看到彼此的答案并加以修订**，最后由一名 **独立评判员**（当通道达到 3 个以上时，会被排除在辩论之外）写出最终共识 + 剩余分歧。已从生产实践中加固：`context_files` 把关键文件注入每个辩手的 prompt（**接地** —— 没有它评审团只会复述你的简报），一道 **事实核查** 流程（免费通道，默认开启）会标出裁决中无法验证的命令/标签/版本，主张会带上来源标签（`[brief]`/`[own-knowledge]`/`[verified]`），简报过于单薄会触发 linter 警告，而 `steelman: true` 会让一个通道在评判员重新下结论前，针对一个一致的裁决进行 *反驳*。`summary_only` 去掉完整立场（token 减少约 60-80%）；`dry_run` 在任何东西发出之前返回一份预检数据清单（哪些文件/字符发往哪些厂商）。参数：`task`、`rounds`、`adversarial`、`context_files`、`fact_check`、`summary_only`、`allow_self_judge`、`steelman`、`dry_run`、`include_paid`、`cwd`、`timeout_s`。 |
| `consensus` | 把「LLM 评审团」做得更好：每个通道先盲答，然后 **对匿名化后的答案进行排名**（不偏袒自己），票数按 **确定性方式**（Borda 计数）汇总，并 **原样返回同行排名第一的答案** —— 因为 *选出* 最佳答案胜过把它们 *混合* 在一起（arXiv 2603.20324：综合输给基线；选择则胜出，g=3.86）。`synthesize: true` 可选择启用一种主持人式的混合（较弱的模式）。返回最终答案 + 一张同行投票排名表。`dry_run` 不启动任何进程，返回一份预检数据清单（哪些文件/字符发往哪些厂商）。支持 `context_files` 接地与 `summary_only`。参数：`task`、`context_files`、`synthesize`、`summary_only`、`dry_run`、`include_paid`、`cwd`、`timeout_s`。 |
| `challenge` | 把一个论断交给 **一个外部通道**，配上一段批判性再评估的 prompt → 一份独立的怀疑式评审（带一道诚信护栏 —— 它不会硬造分歧）。在行动前给你自己的结论做压力测试。可选 `lane`。 |
| `premortem` | 每个通道设想该计划 **已经失败**，列出可能的失败模式 + 缓解措施；合并成一份按优先级排序的风险清单。在动手之前跑一遍。 |
| `test_plan` | 从一个 git diff 或一段描述中推导出一份按优先级排序的 **测试计划**（行为、边界情况、具体用例）。 |
| `commit_msg` | 从你已暂存的 diff（回退到工作区）生成一条 **Conventional Commit** 消息。只读 —— 只产出文本，绝不提交。可选 `lane`、`cwd`。 |
| `pr_describe` | 从分支相对某个基（默认 origin/main → main）的 diff + 提交日志，生成一份 **PR 标题 + 描述**（Summary / Changes / Testing）。只读。可选 `base`、`lane`、`cwd`。 |
| `ask_build` | **委托一次真实构建。** `mode=isolated`（默认）在一次性 worktree 里编辑并返回 **diff** —— 仓库不动。`mode=direct` 直接在目标目录里构建，由 git + **区域契约**护航（被委托方只能写入 `zone`；越界写入会被检测并回滚；撤销按区域作用，绝不全局 reset）—— 于是宿主可以**在同一仓库内并行**构建其他部分。`async=true` 让它**可操控**。`dry_run` 预览 brief。（`ask_build_isolated` 是遗留别名。） |
| `job_tail` / `build_steer` | **像人一样跟随并操控一次构建。** `job_tail(job_id, offset)` 流式输出其进度日志（按字节偏移）。`build_steer(job_id, instruction, interrupt)` 为下一轮排入一条修正，或 `interrupt=true` 打断当前轮（已写入的文件保留）。可选的可执行 **Definition of Done**（`dod_cmd`，一个 argv 列表）在每轮后运行 —— 通过 = 完成，失败 = 把错误回灌再来一轮。 |
| `batch_run` | **持久化扇出**：在**一次调用**里并行跑许多独立请求，而非 N 次（节省宿主上下文 + 配额）。每个结果都被记账，因此 `resume_id` 会重放已完成的任务、只跑剩下的 —— **能挺过服务器重启**。支持 `async`。 |
| `workflow` | 基于批处理底座的**开箱即用多模型工作流**。**`refine_plan`** —— 让评审团从不同角度 **拆解** 你的计划（传 `plan_file`；每个通道自己读取，绝不重复抄写）。`council_review`（N 个通道回答一个问题 + 可选裁判）、`map_review`（并行审阅多个文件）、`research_verify`（先回答再对抗式交叉核验）。全部可恢复 + 可 `async`。 |
| `list_models` | 在 CLI 暴露了模型列表的情况下，列出某个通道可用的模型（`lane` 参数）；否则显示解析出的默认模型 + 如何选择一个。（对于自带原生 list 命令的通道，也存在 `list_<lane>_models`。） |
| `conversations_list` / `conversation_show` | 列出最近的 **圆桌线程**（上下文重置后恢复一个 id）/ 显示某个线程的完整记录，按通道归属标注。 |
| `doctor` | 健康检查：已安装的 CLI、检测到的宿主、成本/额度立场、冷却状态、默认值。`deep: true` 会实时探测每个免费通道的鉴权，**并对照各 CLI 的 `--help` 检查每个通道的参数** —— 如果某个 CLI 重命名/移除了 cli-bridge 依赖的参数（漂移），会在通道悄然失败之前发出警告。 |
| `usage_report` | 仅本地的统计：运行次数、每通道的成功率/延迟，以及 **估算的** token 数（字符数/4）+ 积分（每通道 `CREDITS_PER_1K`）。`since`、`format=text\|json`。 |
| `usage_budget` | 今天每个通道的运行次数对比 `CLI_BRIDGE_<LANE>_DAILY_LIMIT` + 估算花费；标出超出限额的通道。 |
| `lane_stats` | 每通道的健康状况：运行次数、失败次数、连续失败/超时次数、当前冷却状态。 |
| `reset_lane_state` | 清除一个通道的冷却/失败计数（在重新登录或额度重置之后）。 |
| `setup` | 列出已安装的通道及其 *有来源的* 典型套餐成本（free/limited/paid —— 绝不从你的账号检测得来），询问你实际为哪些付费，并 **推荐一个 profile + 每日上限** 供你确认 —— 然后引导用户走完整个流程。 |

还有一个 **人用 CLI** —— 同一套引擎，可从你的终端或 CI 里使用：
`cli-bridge init`（检测 CLI + 打印 MCP 接线信息）、`doctor`、`ask <lane> <task>`、`ask-all`、
`ask-best --mode`、`review-diff --base origin/main --json`、`bench --lane gemini --prompt … `
（延迟 p50/p95/p99）、`usage`、`budget`、`jobs`、`setup --write`。PR 评审的 GitHub Action（自托管
runner）见 `examples/github-action-pr-review.yml`。

**默认只读；写入需显式开启。** 被委托方通常做分析并回答 —— 任何编辑由你的宿主来应用。传入
`agent: "build"` 即可让它 **直接编辑文件**（例如 *"ask gpt to
implement this function"*）：claude → `--permission-mode acceptEdits`，gpt → `--sandbox
workspace-write`，mistral → `--agent accept-edits`，gemini → `--yolo`（或 `agy`
`--dangerously-skip-permissions`），opencode → `--agent build`。具备 build 能力的通道会被标注为
非只读，而一次 `build` 运行绝不会从缓存中返回。

### 委托一次真实构建 —— 在你的仓库里、有监督地进行

`ask_build` 把被委托方变成一个交付**完整、真实**结果的队友，而不只是一份供你复制的 diff。两种模式：

- **`mode=isolated`**（默认，最安全）—— 被委托方在位于 HEAD 的一次性 git worktree 里编辑；你拿到 diff
  自己应用。你的仓库纹丝不动。
- **`mode=direct`** —— 被委托方把**真实文件**写入 `target_dir`，于是你（宿主）可以**在同一仓库内并行**
  构建其他部分（例如 *“我做后端，codex 做 `frontend/`”*）。安全靠的是 git + **区域契约**，而非隔离：
  - brief 告诉被委托方只能写入 **`zone` 之内**（`target_dir` 下的一个路径）；
  - 一切撤销都**按区域作用**（`git checkout -- <zone>` + `git clean -fd <zone>`，绝不全局
    `git reset --hard`），所以你在区域外未提交的工作绝不会被动到；
  - **按区域加锁**让互不相交的区域可同时构建，但拒绝对同一区域的两次构建；
  - 每轮之后一次**全局 `git status`** 会检测任何写到区域外的内容（经由 `../`、绝对路径、符号链接的逃逸）
    并**回滚该次构建** —— git 作用域只保护 git 操作，无法把子进程沙箱化，所以这项检查是强制的。缺失/空的
    `target_dir` 会被创建并 `git init`。

**跟随并操控它。** 用 `async=true` 启动以拿到 `job_id`，然后：

- `job_tail(job_id, offset)` 流式输出构建进度，便于你发布逐步小结；
- `build_steer(job_id, "用 Tailwind，别用内联 CSS")` 为下一轮排入一条修正；
  `build_steer(job_id, interrupt=true)` 打断当前轮（已写入的文件保留）；
- 传入 `dod_cmd`（一个 **argv 列表**，例如 `["npm","run","build"]`，绝不是 shell 字符串）即可在每轮后
  对 Definition of Done 进行**真实测试** —— 通过 = 完成，失败 = 把错误回灌再来一轮，受 `max_fail_retries`
  （默认 3）与 `max_turns`（12）限制。

连续性靠的是文件系统（被委托方每轮重新读取自己的文件）；原始对话留在被委托 CLI 自己的会话里，而 cli-bridge
为 `job_tail` 保留逐步日志。

### 在动手构建前给你的计划做压力测试（`workflow refine_plan`）

cli-bridge 很擅长在你写代码之前*拆解一个计划*。`workflow preset=refine_plan` 把你的计划扇出给多个通道，
每个从一个**不同角度**批判它（技术缺陷与失败模式 / 缺口 / 过度工程 / 排序），然后把发现分组供你合并 ——
或传 `judge_lane` 得到一份去重并按严重度排序的补丁清单。

```jsonc
// 一次调用 → N 个 CLI 从不同角度拆解计划
{ "preset": "refine_plan", "plan_file": "docs/plan.md", "judge_lane": "gpt" }
```

传 **`plan_file`**（一个路径），而非正文：每个通道从自己的工作目录读取该文件，所以计划**绝不会被抄进 N 份
prompt** —— 这是所有产物审阅（`map_review`、`review_diff`、`debate context_files` 同理）默认的省 token 做法。
和所有 `workflow`/`batch_run` 一样，它**可恢复**（`resume_id` 在重启后重放已完成的任务）且可 `async` 运行。

**逐次调用挑选模型**，用 `model`（例如 `model: "claude-opus-4-6"`）。从一个宿主内部，你甚至可以
咨询 **你自己家族里的兄弟模型** —— `ask_<your-host>` 会作为一个单独的工具出现，要求必须给出明确的
`model`，于是在运行 4.8 的同时，你可以从 Claude Code 里去问 Opus 4.6。
（Antigravity 的 `agy` 没有逐次调用的模型参数 —— 它用的是它自己设置里选定的那个。）

**圆桌对话。** 给任意 `ask_<lane>` 传入 `conversation: "new"` 即可开启一个多轮
线程；复用返回的 id —— **哪怕是换一个通道** —— 即可继续。每个通道都能看到那份
共享的记录，其中你自己的发言被标为 "You"，其他人则用名字标注，于是一个评审团可以在彼此的基础上
推进，而不是每次都从零开始。这份记录存在本地（sqlite），所以一个
线程能 **挺过宿主的上下文重置（`/compact`）和一次服务器重启** —— 用
`conversations_list` 恢复它，用 `conversation_show` 读它。一个滑动窗口
（`CLI_BRIDGE_CONVO_MAX_CHARS`，默认 32000）会保留最新的几轮、丢弃最旧的，于是无论线程跑多久，
每轮的成本都保持有界。

对于 opencode，一个空的 `model` 会向 `opencode models` 询问当前的 `opencode/*-free` 列表并
从中选用一个（即 $0 的限速档），通过模式匹配 + 排序来选定 —— 绝不固定某个名字，于是一个被下架的
免费模型会被自动替换。它是 **成本安全的**：一个裸的 `opencode/*` Zen 模型是按 token 计费的
（API 成本），而 `opencode-go/*` 会花掉预付积分，所以默认值绝不会悄悄
选中一个付费模型 —— 想用它们就显式传入。如果查询失败，它会回退
到一个免费种子；设置 `CLI_BRIDGE_OPENCODE_MODEL` 来固定你自己的默认值。

`ask_all` 会把每通道的调用保持得很短（默认 45 秒，最长 60 秒），这样 MCP 宿主能在它
自己的工具调用截止时限之前拿到响应。如果想要一个缓慢/深入的答案，就用更长的
`timeout_s` 直接调用那个通道。

---

## 配置

一切都是环境变量 —— 无需改代码。把它调成 **你的** 订阅情况：

| 变量 | 作用 |
|----------|--------|
| `CLI_BRIDGE_<LANE>_COST` | `free`、`limited` 或 `paid`。`free` 会加入 `ask_all`；`limited` 对额度敏感，会被宽泛分发跳过；`paid` 会花钱/花积分，默认被跳过。 |
| `CLI_BRIDGE_<LANE>_ENABLED` | `false` 即使某个 CLI 已安装也隐藏其通道。 |
| `CLI_BRIDGE_<LANE>_BIN` | 把一个通道指向另一个可执行文件（例如 `CLI_BRIDGE_GEMINI_BIN=agy`）。 |
| `CLI_BRIDGE_<LANE>_MODEL` | 调用方未传模型时，某个通道的默认模型。 |
| `CLI_BRIDGE_PROFILE` | `saver`、`balanced` 或 `max`。`max` 会把受限/付费通道纳入 `ask_all`，除非调用方覆盖 `include_paid`。 |
| `CLI_BRIDGE_HOST` | 强制指定宿主身份（决定隐藏哪个通道）。通常是自动检测的。 |
| `CLI_BRIDGE_LANES_FILE` | 一个 JSON 文件的路径，用于把 **你自己的** CLI/API 添加为通道。 |
| `CLI_BRIDGE_DISABLED_TOOLS` | 逗号分隔的工具名，从列表中隐藏（例如 `debate,premortem,test_plan`）—— 削减每个宿主每次请求都要付出的 schema 上下文。`doctor`/`setup` 无法隐藏。 |
| `CLI_BRIDGE_ENABLED_TOOLS` | 单环境 **精简模式** 的白名单：设置后，只暴露这些工具（+ `doctor`/`setup`）（例如 `ask_best,ask_all,review_diff`）。 |
| `CLI_BRIDGE_<LANE>_PRIORITY` | 数值越低，在 `ask_cascade` 里越早运行（默认 50）。固定你偏好的顺序。 |
| `CLI_BRIDGE_INLINE_MAX_CHARS` | 超过这个长度的答案会溢出到文件，而不是淹没上下文（默认 12000）。 |
| `CLI_BRIDGE_TERSE` | `off` / `lite`（默认）/ `full` / `ultra`。在被委托方的 prompt 前面加上一段紧凑的回答风格前导（用英文，内部充分推理，作答简洁，代码/JSON 不动），以削减你的上下文和被委托方的输出 token。绝不应用于结构化的工作流工具。 |
| `CLI_BRIDGE_TERSE_MIN_CHARS` | 对短于这么多字符的任务跳过 terse 前导（默认 `0` = 从不跳过）。极小的任务收不回前导那点固定开销。 |
| `CLI_BRIDGE_GUARD` | `off` / `warn`（默认）/ `strict`。扫描 **被委托方的输出** 中的提示注入 / 工具投毒；`warn` 会在前面加一条横幅，`strict` 则扣下正文。在机密脱敏之后运行。 |
| `CLI_BRIDGE_MOCK` | `1` = 干运行：通道报告为已安装，并返回一个预设答案，不启动任何 CLI。让你在 **一个 CLI 都没装** 的情况下试用整套工具。 |
| `CLI_BRIDGE_RETRIES` | 遇到 TRANSIENT（瞬时）失败时的重试次数（默认 1）。让一个不稳定的 CLI 一次就成功；额度/鉴权/未找到/超时绝不重试。 |
| `CLI_BRIDGE_TRACE_DIR` | 若设置，每次委托都会在此写一份脱敏的 JSON 轨迹（argv、计时、输出）—— 可复现的调试 / 审计。默认关闭。 |
| `CLI_BRIDGE_MAX_PARALLEL` | `ask_all` 里同时启动的被委托方数量上限（默认 6）。防止一个宽泛的评审团（许多自定义通道）把小机器跑到 OOM 或把额度打爆。 |
| `CLI_BRIDGE_DAILY_CREDIT_CAP` | 每个 UTC 日 *估算* 付费花费的硬性上限。>0 时，一旦今日估算撞上它就拒绝付费通道 —— 让「成本安全」可强制执行，而不只是被报告。免费通道从不受限。 |
| `CLI_BRIDGE_ALLOW_LANES` | 白名单，例如 `gemini,gpt`。空 = 全部。封闭/团队配置下：只暴露这些通道。 |
| `CLI_BRIDGE_DISABLE_BUILD` | `1` 强制每个被委托方为只读（plan），即使调用方请求了 `agent: build`。用于共享机器。 |
| `CLI_BRIDGE_OVERFLOW_MAX_FILES` | 溢出目录文件数量上限（默认 200）；超出部分按最旧优先裁剪，使 `/tmp` 不会无限增长。 |
| `CLI_BRIDGE_CONFIG_FILE` | 一个 JSON 配置文件的路径（默认 `~/.config/cli-bridge/config.json`）。比环境变量更友好的替代方案 —— **环境变量总是优先**。见下文。 |
| `CLI_BRIDGE_CACHE_TTL_S` | `0` = 关闭（默认）。当 `>0` 时，在这么多秒内的一次相同调用会返回缓存答案，而不是重新启动 CLI（在重复时节省额度/积分；build 运行从不缓存）。 |
| `CLI_BRIDGE_<LANE>_CREDITS_PER_1K` | 某通道每 1k token 的积分，被 `usage_report`/`usage_budget` 用来 **估算** 花费（字符数/4）。 |
| `CLI_BRIDGE_<LANE>_DAILY_LIMIT` | 某通道每天最大运行次数；`usage_budget` 在超出时标记。 |
| `CLI_BRIDGE_<LANE>_MIN_INTERVAL_S` | 反爆发的启动节流：此通道两次启动之间的最小秒数（默认 `0` = 关闭）。当某个免费档在连续调用下会限速时设置它（例如 `2`）—— 同通道的爆发会被均匀拉开，其他通道仍保持并行。当某个通道呈现出限速模式时，`lane_stats` 会给出提示。 |
| `CLI_BRIDGE_KEEP_WORKTREES` | 保留 `ask_build_isolated` 的 worktree 而不丢弃（便于检查）。 |
| `CLI_BRIDGE_REVIEW_TIMEOUT_S` | `review_diff` / `security_review` 每个评审者的超时（默认 180；这些本就刻意比 `ask_all` 更重）。 |
| `CLI_BRIDGE_OVERFLOW_TTL_H` | 一个已溢出的文件被裁剪前的小时数（默认 24）。 |
| `CLI_BRIDGE_TELEMETRY` | `off` 关闭本地运行日志 / 冷却跟踪（默认开启，仅机器本地）。 |
| `CLI_BRIDGE_TRACE_FOOTER` | `off` 在工作流报告中隐藏 `## Trace` JSON 页脚 —— 对在终端里阅读的人更友好；MCP 宿主通常想要它（默认开启）。 |
| `CLI_BRIDGE_STATE_DB` | 本地 sqlite 状态 DB 的路径（默认 `~/.local/share/cli-bridge/state.sqlite`）。 |
| `CLI_BRIDGE_STORE_TRANSCRIPTS` | `true` 在遥测里保留更长的任务预览（默认：仅 hash + 60 字符预览）。 |
| `CLI_BRIDGE_LOG` / `_LOG_FILE` | `debug`/`info` 记录在哪里运行了什么（默认：静默）。 |

### 配置文件（替代一大堆环境变量）

更喜欢用文件？放一个 `~/.config/cli-bridge/config.json`（或用 `CLI_BRIDGE_CONFIG_FILE` 指向某个）。
它会补上任何你没设的环境变量 —— **环境变量总是优先**，而且即便完全没有文件，默认值依然
有效：

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

### 添加你自己的 CLI（无需 fork）

`my-lanes.json`，然后 `CLI_BRIDGE_LANES_FILE=/path/to/my-lanes.json`：

```json
[
  {
    "key": "aider", "display": "Aider", "bin": "aider",
    "ask": ["--message", "{task}"], "model_flag": "--model",
    "client_ids": ["aider"], "note": "Aider one-shot via --message."
  }
]
```

你现在就有了一个 `ask_aider` 工具。（一个使用内置 key 的自定义通道，例如 `grok`，会 *覆盖*
内置那个 —— 当你安装的版本参数不一样时很方便。）

**更广阔的生态，随时即插即用：** `examples/community-lanes.json` 随附了对
**Aider、Goose、Plandex、Amp、Crush、Amazon Q Developer CLI 和 Droid (Factory)** 的尽力而为的
通道 —— 全部标为实验性且 `limited`（在 *你* 声明它们对你的成本之前，不纳入宽泛分发），并且
全都被 `doctor deep` 的参数漂移检查覆盖，该检查会在任何东西悄然出错之前，在 *你的* 机器上对照
该 CLI 自己的 `--help` 校验每个通道。Claude Code、
Codex、Gemini + Antigravity（`agy`）、opencode、Qwen Code、Copilot 和 Grok 都已经
内置。其他任何东西（Cline、OpenHands、Continue、Roo/Kilo Code、Kimi K2 CLI…）也都只是
同样的 3 行 JSON 之遥 —— 而这些会说 MCP 的 CLI，任何一个也都能坐到 *另一边*，
把 cli-bridge 当作它的服务器来运行。

### 带上你自己的 API（无需任何 CLI）

通过启动 `curl` 来包装任何 OpenAI 兼容的端点。你的 key 留在环境变量里，绝不进文件。
`{task_json}` 是经过 JSON 转义的 prompt：

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

`--variable %MY_API_KEY` + `--expand-header`（curl ≥ 8.3）这一对会在 curl *内部* 导入
key —— 它绝不会出现在进程列表里。如果一个自定义通道把一个 `${ENV}`
机密展开进 argv，`doctor` 会发出警告。

（两种用法都见 `examples/`，可直接复制。）

---

## 工作原理

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
              hides the host's own lane · only shows installed, enabled CLIs
              kills the whole process tree on timeout / cancellation
              redacts secrets · classifies errors · spills huge output to a file
```

它自己不发起任何网络调用。不存储任何 key。它运行的就是你已经信任的那些二进制文件，在你的
工作目录里，然后把答案交回来。

### 在 IDE 的 MCP 宿主里也能用

cli-bridge 是走 stdio 的纯 MCP，所以任何具备 MCP 能力的宿主都能用 —— 不限于终端 CLI。
把 Cursor / VS Code（Cline、Continue）/ Zed 指向 **同一条命令**（`uvx cli-bridge-mcp`，或
`<python> -m cli_bridge`）。宿主自己的通道会被自动隐藏；其余一切都一样。

### 已知限制（实话清单）

- **防封号取决于各提供方的 ToS。** cli-bridge 运行的只是你手动也会运行的官方 CLI ——
  但非交互式/脚本化的用法并不 *保证* 被许可，而且这可能改变。请在各自条款范围内使用
  你自己的账号；把「防封号」理解为「不提取 token/key」，而非一揽子保证。
- **异步作业是进程内的。** 一次服务器重启会把运行中的作业标为 `interrupted`。`batch_run` 和
  `workflow` 是例外 —— 它们为每个任务记账，因此 `resume_id` 会重放已完成的、重启后只跑剩下的。
- **shell 包装器的 PATH 陷阱。** 如果你的 shell 把被委托的 CLI 包进函数或别名里（例如 `.zshrc` 里的
  `_opsec` 守卫），*从那个 shell* 启动 cli-bridge 可能会坏 —— 但 cli-bridge 直接启动**二进制本身**
  （不经过 shell），因此不受影响；只有在 `PATH` 上遮蔽了该二进制的包装器才有影响。`doctor` 会显示每个
  通道解析出的路径。
- **注入护栏是启发式的。** 它能抓到高信号的模式，但抓不全；在
  `warn` 模式下文本仍会到达宿主（把被委托方的输出当作数据看待）。
- **token/积分数字都是估算**（字符数/4 + 你的 `CREDITS_PER_1K`），绝非精确。
- **自带 API（curl）通道：** 一个 `${ENV}` key 会被替换进 argv，所以在调用进行期间它可能出现在这
  台机器的进程列表里（它绝不会被记录 —— 轨迹会脱敏它）。尽量优先用提供方
  自己的 CLI；对于 curl，用 header 文件（`curl -H @file`）可避免 argv 暴露。
- **实验性通道**（`qwen`、`copilot`、`grok`）：参数未经实测验证 —— 出问题请反馈。
- **成本档是有来源的默认值，不是检测得来** —— 厂商套餐事实标注于 2026 年 6 月
  （[docs/COSTS.md](../COSTS.md)）；套餐/额度会更替，当快照过时时 `doctor` 会警告。
- **沙箱化的宿主：** 如果你的宿主在一个严格的沙箱里（只读 FS / 无
  网络）运行该服务器，被启动的 CLI 会继承它，可能无法触及它们的提供方。cli-bridge 会把
  这种情况呈现为 `auth`/`failed` 错误，而不是挂起。

---

## 开发

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration (cross-host) tests
```

## 许可

MIT

---

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../assets/mark-dark.svg">
  <img src="../../assets/mark-light.svg" width="84" alt="cli-bridge">
</picture>

<sub>一端 · 桥接到一个评审团</sub>

</div>
