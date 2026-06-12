<div align="center">

<img src="../../assets/banner.gif" width="860" alt="cli-bridge —— 让你的助手借用你已经拥有的每一个 AI CLI 的能力：超大上下文读取、视觉、并行构建、跨厂商校验">

[English](../../README.md) · [Français](README.fr.md) · **简体中文** · [Español](README.es.md) · [Português (BR)](README.pt-BR.md) · [日本語](README.ja.md) · [Deutsch](README.de.md)

</div>

_英文 README 为准；本翻译可能滞后。欢迎社区校对。_

# cli-bridge

![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/cli-bridge-mcp)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-Apache%202.0-green)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**一个 [Model Context Protocol](https://modelcontextprotocol.io) 服务器，让你的 AI 助手调用你已经装好的*其他* AI CLI。**

> **无 API 密钥 · 不抽取令牌 · 无 Node · 无守护进程 · 仅 stdlib + `mcp`。**

### 一句话说清

你在和一个 AI 助手对话。你还安装并登录了其他 CLI —— Claude Code、Codex、Gemini、opencode、Ollama。
**cli-bridge 把它们连起来**：当你的助手遇到自己做不到的事，它会去问另一个 CLI，再把结果交给你。

### 它解决的问题

无论你用哪个助手，它都有硬性限制：无法一次读完 200 万 token 的仓库，无法查看截图，无法给你一张生成的图片，
也无法无偏差地检查自己的工作 —— 但*你机器上的某个其他 CLI 恰好能做到其中每一件事*。cli-bridge 就是它们之间的
桥：把官方 CLI 作为子进程启动（与你手动运行完全相同 —— 无密钥、不抽取令牌），再把答案返回给你的助手。

结果：一个助手，它在每个维度上的上限都是你工具箱里*最好*的那个工具，而不是你恰好打开的那个。

---

## 10 秒演示

你在 Claude 里。Claude 无法给你一张图片。Codex 可以 —— 它会写出渲染图片的代码并运行。所以就让它去做：

```
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png — write a script that renders it, then run it", zone="assets")
→ Codex writes assets/card.png · you get the path back, never a binary blob (artifact-return)
```

你的助手刚刚获得了它本不具备的能力。这就是全部理念 —— 现在把它扩展到超大上下文读取、视觉、并行的体力活，以及
独立的跨厂商验证。

_（Codex 用 **`gpt-image-2`** 生成图片——这是内置于 CLI 的真正文本生成图片模型——计入你的 ChatGPT 套餐额度，
无需单独的 API 密钥（图片生成需要**付费**套餐，免费套餐不可用）。结果以**路径**返回而非 blob，因为二进制通过
artifact-return 传递，而不走文本通道。build lane 在更合适时也可以通过写代码来*渲染*图表、示意图或 SVG。）_

### …并且它能安全地委派真实工作

`cli-bridge build <lane> "<任务>"` 把工作交给在**一次性 git worktree** 中运行的另一个模型，然后给你返回一个
**diff** —— 在你亲自应用之前，你的仓库绝不会被改动。

<p align="center">
<img src="../../assets/demo-borrow.gif" width="860" alt="cli-bridge build：opencode 在一次性 worktree 中添加一个函数并返回可审查的 diff；真实仓库保持干净">
</p>

---

## 你得到什么 —— 四个杠杆

cli-bridge 不是一个功能，而是**四个杠杆**。理解它们，下面的每个工具就各归其位：

1. **借用（Borrow）** —— 触及你助手缺失的能力（视觉、100 万 token 的上下文窗口、编码代理生成的文件、单纯在
   *这件事*上更强的模型）。
2. **分摊（Spread）** —— 当一个订阅触顶时，在你已经付费的另一条 lane 上继续。
3. **卸载（Offload）** —— 把繁琐、可并行的体力活分散到便宜/免费的 lane 上，同时你在别处构建。
4. **验证（Verify）** —— 让一个*不同厂商家族*来检查工作，因为模型看不见自己的盲点。这是单一厂商工具在结构上
   做不到的唯一一件事。

---

## 这能解锁什么

每个区块：一句话说明*何时使用*、确切的调用、以及*你会得到什么*。

### 借用你助手没有的能力
每个 CLI 都有不同的超能力，且每个都能非交互运行 —— 所以 cli-bridge 能启动它。借用你的 host 所缺的那个
（必须已安装 + 已登录）：

| 超能力 | 哪个 CLI 拥有 | 何时借用 |
|------------|------------------|----------------|
| **图像** | Codex（`gpt-image-2`，**无 API 密钥** —— 付费 ChatGPT 套餐，非免费） | 你的 host 不会画图时 |
| **超大上下文** | Gemini（100 万 token 窗口） | 文件/仓库装不进你 host 的上下文时 |
| **新鲜知识** | Gemini（Google 搜索接地）· Grok（实时 web/X）⚗️ | 越过训练截止：*「`<lib>` 当前的 API 是什么？」* |
| **视觉** | Gemini（`images=[…]`）⚗️ | 分析截图或示意图 |
| **免费的第二意见** | Gemini（免费日额）· opencode · Ollama（本地，0 $） | 一次 0 $ 的交叉核对 |
| **生成文件** | 任意构建 lane → artifact-return | **按路径**取回图表/PDF/示意图 |
| **视频** ⚗️ | Gemini（Veo）· Grok（Imagine）—— *若你装的 CLI 暴露它* | 你需要一段生成的片段 |

```
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png", zone="assets")   # Codex image → file by path, no API key (paid ChatGPT plan)
ask_gemini(task="find the bug across ./src — read the files you need", cwd="path/to/repo")         # 1M-token context
ask_gemini(task="what's the current recommended API for <lib>? check the latest docs")            # fresh knowledge (Search grounding)
ask_gemini(task="what's wrong in this UI?", images=["screenshot.png"])                             # vision (experimental)
```

⚗️ = 实验性 / 取决于所装 CLI 的当前构建（例如 Grok Build 处于 beta）—— 用 `doctor deep` 核实。

### 触顶时也别停下工作
当你的主订阅在任务途中耗尽。`ask_cascade` 会回退到你已付费的另一条 lane，跳过任何在配额/鉴权/超时错误后处于
冷却中的 lane。

```
ask_cascade(task="finish wiring this endpoint")   # cheapest→strongest; a cooled-down lane is skipped
ask_best(task="…", mode="deep")                   # let the router pick the most suitable available lane
```

### 卸载体力活 —— 并行且便宜
当工作繁琐但不难（重构、迁移、测试覆盖）。把它扇出，带日志，使服务器重启时能续跑而非从头来；委派一个构建，
继续工作。

```
batch_run(tasks=[...], dry_run=true)                       # cost envelope first — nothing is spawned
batch_run(tasks=[...], max_calls=20, max_credits=2.0)      # then run under a hard budget (resumable)
ask_build(lane="opencode", task="add the landing page", zone="frontend", mode="direct", async=true)   # delegate, keep building
job_tail(job_id="…")  ·  build_steer(job_id="…", instruction="use Tailwind, not inline CSS")
```

### 打破自我确认 —— 单一厂商无法解决的 2026 难题
当你需要*信任*一个结果时。一个模型审查自己的工作（或同门兄弟的工作）只会确认自己的盲点。cli-bridge 把一个
**不同的模型家族**放到审查者的座位上。

```
workflow(preset="jury", task="is this migration safe?", author_lane="gpt")            # cross-family vote, fail-closed
workflow(preset="verify_repair", task="add retry with backoff",
         builder_lane="gpt", verifier_lane="gemini")                                   # A builds, B reviews, loop to green
security_review(base="origin/main")   ·   review_diff(base="origin/main")              # OWASP, severity-ranked
```

### 获得真正的第二意见
当你已得出结论并想给它施压测试，或者想把几个模型并排比较。

```
challenge(task="I'm dropping the cache layer — here's why: …")                         # one skeptic attacks it
consensus(task="which migration strategy is safest here?")                             # N answer, peer-rank the best
workflow(preset="fanout_compare", task="fix this failing test", lanes=["gpt","gemini","opencode"])
```

---

## 工具箱

约 30 个工具，按用途分组（咨询 / 构建 / 校验 / 编排）。**完整参考——每个工具、每个参数：[`docs/TOOLS.md`](../../docs/TOOLS.md)**（或 `cli-bridge --help`）。`CLI_BRIDGE_LEAN=1` 可启用约 12 个工具的精简集。

---

## 把它们组合起来你真正得到什么

一个单一的助手，其在**每个维度上的上限都是生态系统的最佳** —— 而非你今早打开的那个工具：用最强的模型编码、
在自己的上下文太短时读 1–2M token、越过训练截止以新鲜知识作答、生成图像/视频、查看截图，并在触顶时回退到
免费/本地的 lane —— 一切都分摊在你已经付费的订阅之间。

那项**没有任何单一 CLI 拥有的涌现特性：真正的跨厂商控制** —— 在审查者座位上放一个*不同的厂商*。同门子代理
（Claude Code 的、Grok 的）只能自我确认。

诚实的接缝：这统一的是**能力，而非心智** —— 无状态的 spawn（无共享记忆）、spawn 的延迟/成本、参差的质量，
而且 host 始终掌舵。这是**编排，而非融合**：你指挥一群专家，而不会得到一个拥有全部能力的单一大脑。

→ 各 CLI 的强项与局限（带日期，变化很快）：**[docs/COMPARISON.md](../COMPARISON.md)**。

## 为什么选 cli-bridge（而非又一个「调用其他模型」的 MCP）

- 🛡️ **设计上 ban-safe。** 它启动每个模型的**官方 CLI**，与你手动运行完全相同 —— 不抽取 OAuth 令牌、不复用
  API 密钥。每个 CLI 自行处理鉴权与计费。
- 💸 **可按你套餐调校的 cost-safe 默认值。** 开箱即用，`ask_all` / `ask_cascade` 组建一个*免费*评议会，
  除非你要求，否则绝不触碰付费配额。每条 lane 自带一个取自厂商已公布套餐的档位（在
  [docs/COSTS.md](../COSTS.md) 中带日期，**绝不从你的账户检测**）；用
  `CLI_BRIDGE_<LANE>_COST=free|limited|paid` 按 lane 覆盖。
- 🔌 **从任何 host 都能用。** Claude Code、Codex、opencode、Cursor、VS Code（Cline/Continue）、Zed ——
  任何通过 stdio 讲 MCP 的东西。host 自身的 lane 会被排除在扇出之外；用 `CLI_BRIDGE_HIDE_HOST=1` 隐藏它。
  甚至**本地模型也能当 host** —— 见 [`examples/local-first-host.md`](../../examples/local-first-host.md)。
- 🧭 **跨厂商优势就是护城河。** 独立验证意味着在审查者座位上放一个*不同的厂商* —— 随着 AI 写下越来越大比例的
  代码，这是稀缺之物，也正是单一厂商工具无法提供的。

---

## 工作原理

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
       keeps the host's own lane out of fan-out · only shows installed, enabled CLIs
       kills the whole process tree on timeout/cancellation · redacts secrets
       classifies errors (auth/limit/failed) · spills huge output to a file
```

没有自己的网络调用。不存储密钥。它在你的工作目录里运行你已经信任的同样的二进制，并把答案交还给你。

<div align="center">

<img src="../../assets/demo.gif" width="860" alt="cli-bridge security-review 演示：一处提交的授权绕过被一个跨厂商评议会捕获，合并为一份按严重度排序的报告，在免费 lane 上 0 $">

_真实运行（2.2× 速度）：验证杠杆 —— `security-review` 把 OWASP 角色并行扇出到免费模型上（此处为
claude/gpt/opencode/ollama）；它们把一处提交的鉴权绕过标记为 **blocker**，而 `usage` 给出凭据。_

</div>

---

## 安全地写代码：两种模式

写入被以两种方式收束 —— **由你选择** 经审查还是放手不管：

- **`isolated`（默认）。** 在一次性 git worktree 中编辑并返回一个 **diff**。你的工作树绝不会被触碰。
- **`direct`。** 写入真实文件，**但仅在你声明的 `zone` 内**，背后有按区锁与回合后的越区检查。你在 `backend/`、
  一个被委派者在 `frontend/`，同时进行 —— 谁都无法在你整个仓库里乱涂；撤销限定在区内，绝不是全局重置。

被委派者的再入受深度上限约束（`CLI_BRIDGE_MAX_DEPTH`，默认 1），以免配置错误的被委派者把评议会 fork 炸了。

---

## 快速开始（约 5 分钟）

```bash
# Run it (no install) — uvx fetches, runs, discards:
uvx --from cli-bridge-mcp cli-bridge doctor
# or, from a clone:  python -m cli_bridge

# Point your MCP host at that same command, then:
cli-bridge doctor        # see which CLIs are detected + their resolved paths
```

### Lane

**内置：** Claude Code、Codex、Gemini（+ Antigravity `agy`）、opencode、**Ollama（本地模型，0 $，离线）**、
Qwen Code、Copilot、Grok。

**Ollama 之外的本地运行时** —— **LM Studio · MLX · llama.cpp** —— 以零代码配方提供：把
`CLI_BRIDGE_LANES_FILE` 指向 [`examples/lmstudio.lane.json`](../../examples/lmstudio.lane.json)、
[`mlx.lane.json`](../../examples/mlx.lane.json) 或 [`llamacpp.lane.json`](../../examples/llamacpp.lane.json)。
（*相同*开源权重的多个本地运行时给出相关的答案 —— 真正的评议会多样性来自不同的厂商，而非第二个本地运行时。）

**社区 lane**（`examples/community-lanes.json`，实验性 + 在你声明其成本前为 `limited`）：Aider、Goose、
Plandex、Amp、Crush、Amazon Q Developer CLI、Droid。

**其他任何东西都是约 3 行 JSON。** 添加自定义 lane，或通过启动 `curl` 包装任何 OpenAI 兼容端点（密钥留在
curl 内部，绝不进入 argv）。配方见 [`examples/`](../../examples/)。

---

## 诚实的部分

「模型越多越好」是*脆弱*的 —— 大模型共享训练数据，所以它们的错误是相关的。我们测量了自己的核心主张
（`cli-bridge eval`，无 LLM 裁判）：多样的评议会并**没有**比单个强模型抓到更多 bug —— 它把误报削减了
**约 2 倍**。同样的命中率，远更少的噪声 —— 这正是让审查者保持可信而非被无视的东西。**精度才是产品，而非
召回。** 这套测试随附，所以你可以在*你自己的* CLI 上确认 —— 无论结果如何，数字都在
[docs/BENCHMARKS.md](../BENCHMARKS.md)。

---

## 已知局限

- **Ban-safe = 不抽取令牌/密钥**，并非一揽子保证 —— 对某供应商 CLI 的非交互使用并非处处获正式认可，且可能
  变化。在各自条款范围内使用你自己的账户。
- **异步任务在进程内** —— 服务器重启会把运行中的任务标记为 `interrupted`。`batch_run` / `workflow` 是例外：
  它们为每个任务记日志并经 `resume_id` 续跑。
- **注入防护是启发式的** —— 它捕捉高信号模式，并非全部；把被委派者的输出当作数据，而非指令。
- **token/额度数字是估算**（chars/4 + 你的 `CREDITS_PER_1K`），绝不精确。
- **成本档位是有出处的默认值，而非检测** —— 套餐事实带日期；快照过期时 `doctor` 会警告。
- **实验性**（`qwen`、`copilot`、`grok`、社区 lane、Gemini `images=`）：标志未经实时验证 —— `doctor deep`
  会在你的机器上对照每个 CLI 的 `--help` 检查它们。

---

## 路线图

已交付的历史见 [`CHANGELOG.md`](../../CHANGELOG.md)。当前**正在探索（未交付）**：一种**独立预言机**验证模式
（来自另一家族的 lane 从*规格*出发、对实现盲写测试，使测试抓到 bug 而非镜像 bug）以及更精细的**感知上限的
故障转移**。庞大的智能体间「总线」构想（递归 spawn、共享状态、线协议）被诚实地定位为一个*方向*，绝不作为
已交付协议出售 —— 见 [docs/ARCHITECTURE.md](../ARCHITECTURE.md)。

---

## 参考文献

上面的设计选择不是凭感觉 —— 每一条都对应文献中的一个发现。每个条目都对照其来源（作者 + 发表场所）核对过，
因为一个出售「诚实的跨厂商验证」的工具，理应把自己的引用弄对。

| 论文 | ID | 它在此支撑什么 |
|-------|----|--------------------|
| Du et al. — *Improving Factuality and Reasoning via Multiagent Debate* | [2305.14325](https://arxiv.org/abs/2305.14325) | `debate`：互相批评的模型胜过单个模型 |
| ReConcile — *Round-Table Conference Improves Reasoning* | [2309.13007](https://arxiv.org/abs/2309.13007) | `debate` 的收敛 + 置信度加权的共识 |
| Mixture-of-Agents | [2406.04692](https://arxiv.org/abs/2406.04692) | 跨多样模型的分层聚合（及其局限） |
| Chain-of-Agents | [2406.02818](https://arxiv.org/abs/2406.02818) | 按角色专门化的多智能体流水线 |
| CriticGPT — *LLM Critics Help Catch LLM Bugs* | [2407.00215](https://arxiv.org/abs/2407.00215) | `review_diff` / `security_review`：LLM 评审者抓到人类漏掉的 bug |
| Perez et al. — *Discovering Language Model Behaviors*（谄媚） | [2212.09251](https://arxiv.org/abs/2212.09251) | 为何同门裁判弱 → 跨厂商 `jury` + 同侪匿名化 |
| Wynn, Satija & Hadfield — *Talk Isn't Always Cheap* | [2509.05396](https://arxiv.org/abs/2509.05396) | 辩论的失败模式 → fail-closed 裁决、有界回合 |
| CONSENSAGENT — *Consensus via Sycophancy Mitigation*（Findings of ACL 2025） | [ACL 2025](https://aclanthology.org/2025.findings-acl.1141/) | 共识中的谄媚 → 「赢得席位」/ 匿名化同侪 |
| Maryanskyy — *When Agents Disagree: The Selection Bottleneck* | [2603.20324](https://arxiv.org/abs/2603.20324) | `consensus`：**选择 > 综合**（确定性同侪投票的默认） |

> **一条引用卫生说明。** *Talk Isn't Always Cheap*（2509.05396）出自 **Wynn, Satija & Hadfield** ——
> 一个流行的评议会框架把它误引为「Xiong et al.」。我们在重复之前会复核归属，并加以指出，因为诚实就是全部
> 卖点。

## 开发

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration (cross-host) tests; no real CLI or network needed
```

## 许可证

Apache 2.0

---

<div align="center">

<img src="../../assets/mark.gif" width="84" alt="cli-bridge">

<sub>一岸 · 通向一个评议会</sub>

</div>
