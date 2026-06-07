<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../assets/banner-dark.svg">
  <img src="../../assets/banner-light.svg" width="860" alt="あなた → cli-bridge → 並列で動く AI CLI の評議会 → 統合された1つのレビュー">
</picture>

[English](../../README.md) · [Français](README.fr.md) · [简体中文](README.zh-CN.md) · [Español](README.es.md) · [Português (BR)](README.pt-BR.md) · **日本語** · [Deutsch](README.de.md)

</div>

_英語版の README が正典です。この翻訳は内容が古くなっている場合があります。_

# cli-bridge

![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/cli-bridge-mcp)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**あなたの AI アシスタントに、いざというとき仲間へ電話をかける力を。**

`cli-bridge` は [Model Context Protocol](https://modelcontextprotocol.io) サーバーで、
**すでにインストール・ログイン済みの AI CLI を束ねて動かします** — Claude Code、Codex、
Gemini CLI、opencode、… を、いま対話しているアシスタントから操作します。API キー不要、トークン
抽出なし、ログはローカル限定、コストには厳格な上限、書き込みは使い捨て worktree の diff のみ。
ここまでは議論の余地のない単なる配管です。その先に開ける世界がこちらです。

厄介なバグで詰まっていますか？アシスタントに GPT *と* Gemini を並列で尋ねさせて比較しましょう。
巨大なファイルを 100 万トークンで読ませたい？ Gemini に渡しましょう。安価なセカンドオピニオンが
欲しい？ 無料モデルに投げましょう。1つの質問を、あらゆるモデルに、横並びで — ターミナルから
離れることなく。

```
You → Claude:  "ask the council whether this auth logic is safe"
Claude → cli-bridge → [ Gemini ] [ GPT ] [ Mistral ] [ Qwen ] … in parallel
            ← three independent reviews + a synthesis of where they agree & disagree
```

<div align="center">

<img src="../../assets/demo.gif" width="860" alt="cli-bridge security-review のデモ: コミット済みの認証バイパスを2つのモデルが独立に検出し、深刻度順の1つのレポートに統合、無料レーンなので $0">

_実際の実行（2.5倍速）: コミットされた認証バイパス — `security-review` が OWASP の役割を無料モデル群へ
並列にファンアウトし、2つのモデルが独立に **blocker** と判定、そして `usage` が証拠を示します。_

</div>

> **何が違うのかを一息で:** API キーを一切保持せず、トークンを一切抽出しません — **すでに
> インストール・ログイン済み**の公式 CLI を動かすだけです。無料レーンの評議会のコストは
> **$0.00**（証拠は `usage_report` にあります）。有料レーンは *あなた* が設定した厳格な日次上限の
> 内側でしか動きません。そして実際に作業を *させる* ときは、使い捨ての git worktree で編集し、
> **diff** を返します — あなたの本番リポジトリには一切触れません。

> **そして正直なところ:** 「モデルが多いほど良い」は *脆い* — 大型モデルは学習データを共有しており、
> 誤りが相関するからです。私たちは自分たちの中心的主張を計測しました（`cli-bridge eval`、出荷済み、
> LLM ジャッジなし）: 多様な評議会は、1つの強力なモデルより多くのバグを捕まえることは **ありませんでした** —
> 偽陽性を **約2倍** 減らしただけです。どちらに転んでも数値は公開しています（[BENCHMARKS.md](../BENCHMARKS.md)）。
> ハーネスも同梱しているので、*あなたの* CLI で自分で実行できます。

---

## なぜこれを選ぶのか

「他のモデルを呼ぶ」MCP は他にもあります。cli-bridge を際立たせているのは次の点です。

- 🛡️ **設計からして ban-safe。** 各モデルの**公式 CLI** を起動します — あなたが手で実行するのと
  まったく同じです。OAuth トークンの抽出も、API キーの使い回しも、アカウントがフラグ付けされる
  ような行為も一切ありません。各 CLI が自身の認証と課金を処理します。
- 💸 **出典付きのコスト初期値、そこから *あなた* がプランに合わせて調整。** 初期状態では `ask_all` は
  無料の評議会を組み、頼まない限りサブスク枠（Claude、GPT）や有料クレジットには一切触れません。
  各レーンには、ベンダー公開プランから出典を取ったティアが付いています
  （[docs/COSTS.md](../COSTS.md)、日付入り） — **あなたのアカウントから検出することは決してなく、
  その旨も明示されています** — それを自分のサブスクに合わせて上書きします
  （`CLI_BRIDGE_<LANE>_COST=free|limited|paid`）。大型プランならすべてを `free` にするか、
  `CLI_BRIDGE_PROFILE=max` を設定しましょう。
- 🔌 **どのホストからでも動く。** Claude Code から操作中？ Claude レーンを隠し（自分自身に尋ねない
  ように）、残りを公開します。代わりに Codex や opencode から操作中？ 同じ要領で、MCP ハンドシェイク
  から自動検出します。
- 🧩 **どんな CLI でも — 自前の API でも — フォークなしで追加。** Claude、GPT、Gemini、Mistral、
  Qwen、Copilot、Grok、opencode の組み込みレーンがあります。**JSON ファイルから自分の CLI を登録** したり、
  `curl` を起動して **自分の API をラップ** したりできます。コード不要。
- 🧠 **評議会の統合。** `ask_all` は無料モデルに、他のモデルがどこで *一致* し *相違* するかを要約させる
  ことができます — 3つの意見を1つの判断に変えます。
- 🔬 **マルチモデルのワークフロー。** `review_diff` と `security_review` は **役割の異なる** レビュアーを
  評議会全体にファンアウトし、深刻度順の1つのレポートにマージ＋重複排除します。`debate` はモデル同士を、
  限られたラウンドの中で互いに批評・修正させ、最後にジャッジが結論を出します。
- ✍️ **既定では読み取り専用、必要なときだけ書き込み。** `agent: build` を選べば、対応可能な任意の
  レーンに実際に **ファイルを編集** させられます — あるいは呼び出しごとに特定の `model` を選べます。
  **自分と同じ系統の兄弟モデル** も含めて（Claude Code 4.8 から Opus 4.6 に尋ねる）。
- 🪶 **サブエージェント風の返答。** 委任先は自身のコンテキストで作業し、ダイジェストを返します。巨大な
  出力はファイルに退避され、プレビューだけが戻るので、アシスタントのコンテキストは軽量なまま保たれます。
- 🔁 **自動フォールバック。** `ask_cascade` はレーンを安い順→強い順に試し、あるレーンが
  クォータ/認証/タイムアウトに当たると次へ進みます — 死んだレーンは、あなたを失敗させる代わりに
  優雅にデグレードします。
- 🩺 **自己認識。** ローカルのテレメトリが各レーンの健全性を追跡し、クォータ/認証/タイムアウトの失敗が
  繰り返されたレーンをクールダウンに入れます。これにより `ask_all`/`ask_cascade` はそれを迂回します。
- 🎯 **あなたのスタックを学習。** `rate_lane` でレーンの回答を1〜5で採点すると、`ask_best` は
  **あなたのマシン上で** 各タスク種別を実際に制したモデルを優先します — sqlite に保存されるローカルの
  品質シグナルで、`/compact` や再起動を生き延びます。公開ランキングではなく、*あなたの* 結果です。
- 🧱 **堅牢化済み。** タイムアウトはプロセスツリー全体を停止し（孤児プロセスがクォータを焼かない）、
  ホストのキャンセルは委任先を停止し、シークレットは伏字化され、エラーは分類されます
  （`quota` / `auth` / `timeout`）。これによりアシスタントは次に何をすべきか分かります。
  macOS / Linux / Windows で動作します。
- 📐 **主張ではなく計測。** 「モデルが多いほどバグを多く見つける」は *反証可能* なので、cli-bridge は
  そのテストを同梱しています: `cli-bridge eval` は、種まきされた推論バグのコーパス上で、評議会と
  「1つの強力なモデル＋自己一貫性」を **同等の呼び出し予算** で対決させ、決定論的に採点します
  （LLM ジャッジなし）。平均 ± 標準偏差を、「有意な差なし」ガードとバグごとの勝敗表とともに報告し —
  評議会が負けたときでも結果を公開します。
  [BENCHMARKS.md § Quality](../BENCHMARKS.md#quality--does-a-council-actually-beat-one-strong-model) を参照。

### 他のマルチモデル MCP との比較

| | cli-bridge | API キーゲートウェイ | トークン再利用ブリッジ |
|---|:---:|:---:|:---:|
| Ban-safe（公式 CLI を起動） | ✅ | ➖（あなたのキー） | ❌（ToS リスク） |
| 管理する API キーなし | ✅ | ❌ | ✅ |
| 既存のサブスクを利用（$0.00 の無料評議会） | ✅ | ❌ | ✅ |
| プラン別コストティア＋厳格な日次上限＋クールダウン | ✅ | ➖ | ❌ |
| 自動フォールバック（cascade） | ✅ | 一部 | ❌ |
| **あなたの結果から学習する**ルーティング | ✅ | ❌ | ❌ |
| 任意の CLI / 自前 API を追加、フォール不要 | ✅ | ➖ | ❌ |
| 呼び出し元ホストを自己的に隠す | ✅ | 該当なし | ➖ |
| 再起動を生き延びる円卓メモリ | ✅ | ➖（インメモリ） | ➖ |
| 安全なエージェント書き込み（worktree → diff） | ✅ | ➖ | ❌ |
| 決定論的な品質評価を同梱（評議会 対 単体） | ✅ | ❌ | ❌ |

---

## クイックスタート

### 1. インストール

```bash
# zero-install run (recommended)
uvx cli-bridge-mcp

# or install it
uv tool install cli-bridge-mcp     # or: pipx install cli-bridge-mcp
```

レーンが使えるのは、**すでにインストール・ログイン済み**の CLI に対してだけです。cli-bridge は
あなたの `PATH` にあるものを自動検出します。`doctor` ツールをいつでも実行すれば、何が結線されて
いるか確認できます（`doctor deep` は各ログインをライブでチェックまでします）。

| Lane | CLI | コスト（典型） |
|------|-----|------|
| `ask_claude`   | [Claude Code](https://docs.claude.com/claude-code) | サブスク |
| `ask_gpt`      | [OpenAI Codex](https://github.com/openai/codex) | サブスク |
| `ask_gemini`   | Gemini CLI（または `agy` / Antigravity） | 無料 / サブスク |
| `ask_mistral`  | Mistral Vibe | 無料ティア |
| `ask_qwen` ⚗️  | Qwen Code | 従量制 API キー（無料 OAuth ティアは 2026年4月終了） |
| `ask_copilot` ⚗️ | GitHub Copilot CLI | サブスク（2026年6月以降は利用量ベースのクレジット） |
| `ask_grok` ⚗️  | xAI Grok CLI | サブスク（SuperGrok / X Premium+） |
| `ask_opencode` | [opencode](https://opencode.ai) ゲートウェイ（deepseek、qwen、glm、kimi…） | 既定で無料；一部モデルはクレジットを消費 |

⚗️ = 実験的（フラグはライブで未検証 — 不具合があれば報告してください）。
コスト列 = 2026年6月時点でのベンダーの *典型的な公開プラン*（[docs/COSTS.md](../COSTS.md) に
上限・終了予定・出典あり） — cli-bridge はレーンが *あなたに* いくらかかるかを決して検出しません。
自分のプランは `CLI_BRIDGE_<LANE>_COST` で宣言してください。

### $0 の評議会（サブスクは一切なし）

有料プランもカードもない？ それでも、**真に無料でハードストップ式のティア** を持つプロバイダーから、
約5分で本物のマルチモデル評議会を組めます（枯渇 = HTTP 429、請求は構造的に不可能 —
2026年6月検証、出典は [docs/COSTS.md](../COSTS.md)）:

```bash
# 1. Get free API keys (no card): console.groq.com · cloud.cerebras.ai ·
#    a GitHub PAT (models scope) · openrouter.ai/keys
export GROQ_API_KEY=... CEREBRAS_API_KEY=... GITHUB_MODELS_TOKEN=... OPENROUTER_API_KEY=...
# 2. Point cli-bridge at the ready-made lanes
export CLI_BRIDGE_LANES_FILE=/path/to/examples/free-apis.json
```

これで **Groq**（llama-3.3-70b、1日1,000リクエスト）＋ **Cerebras**（gpt-oss-120b）＋
**GitHub Models**（すべての GitHub アカウントが無料アクセス可能）＋ **OpenRouter `:free`** の幅広さ —
`ask_all`/`consensus`/`debate` のための4つの独立した声に加え、インストール済みなら opencode の
組み込み無料モデルも使えます。注意: Gemini CLI の無料ティアは **2026-06-18 に終了**。無料ティアは
数週間で入れ替わります — 検証時点で何が真だったかは [docs/COSTS.md](../COSTS.md) を確認してください。

### 2. ホストに登録する

**Claude Code** — コマンド1つ:

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
<summary><b>opencode</b> / <b>Gemini CLI</b> / その他の MCP クライアント</summary>

クライアントの MCP 設定を、stdio 経由のコマンド `uvx cli-bridge-mcp` に向けてください。どこでも同じです。
</details>

### 3. 使う

アシスタントに話しかけるだけ:

> *"Ask Gemini for a second opinion on this function."*
> *"Have the whole council review my diff and synthesize where they disagree."*（→ `review_diff`）
> *"Get GPT to think hard about this race condition."*（→ `effort: high`）
> *"Run a security review on my staged changes."*（→ `security_review`）
> *"Make the models debate whether we need this abstraction."*（→ `debate`）
> *"Ask gpt to implement this function."*（→ `agent: build`、ファイルを編集）
> *"Ask Opus 4.6 to double-check my reasoning."*（兄弟モデル、Claude Code から）
> *"Pick the best lane for a deep review — and remember that one nailed it."*（→ `ask_best` + `rate_lane`；次回はそこへ最初にルーティング）

MCP プロンプトに対応するホストでは、`review_diff`、`security_review`、`debate`、`premortem`、
`test_plan`、`apilookup`、`cost_setup` がネイティブのスラッシュコマンドとしても表示されます。

---

## ツール

| ツール | 何をするか |
|------|--------------|
| `ask_<lane>` | 1つのモデルに尋ねます。パラメータ: `task`、任意の `model`、`effort`、`agent`、`cwd`、`timeout_s`、**`conversation`**（円卓スレッドを開始/継続 — 下記参照）。 |
| `ask_all` | 同じ質問を、無料かつ非 limited のすべてのレーンへ並列にファンアウトします。`synthesize: true` で一致/相違の要約を追加。`include_paid: true` で limited/paid レーンにも問い合わせます。 |
| `ask_cascade` | **自動フォールバック付き** で1つのモデルに尋ねます — レーンを安い順→強い順に試し、クールダウン中のものを飛ばし、クォータ/認証/タイムアウトで次へ進みます。最初の成功と、試行の軌跡（コストティア、レイテンシ、なぜスキップしたか）を返します。 |
| `ask_best` | コスト・健全性・実測レイテンシ **そしてあなた自身の `rate_lane` スコア** から、**モード別に1つのレーンを選び**（`fast`/`cheap`/`deep`/`code`/`review`/`security`）、フォールバック付きで実行します。「ちょうどいいモデルを使って」用 — `ask_all` は比較、`ask_cascade` は素朴な安い順優先です。 |
| `rate_lane` | **ルーターを教育。** タスク種別（`mode`）に対するレーンの回答を1〜5で採点 → `ask_best` は以後、**あなたのマシン上で** そのモードを制するレーンを優先します。sqlite に保存（`/compact`/再起動を生き延びる）。レーンが舵取りを始める前に2件の評価という下限があるので、フィードバックは正直でノイズになりません。`ask_best` の回答はすべて、実際の呼び出しを表示します。 |
| `route_plan` | あなたのプロファイル＋現在のクールダウンを踏まえ、`ask_cascade` が試す順序を表示します（読み取り専用、何も実行しません）。`mode` を渡すと `ask_best` をプレビューできます — 各レーンの現行レーティングも含めて。 |
| `ask_all_async` / `job_status` / `job_result` / `job_cancel` / `jobs_list` | ファンアウトを **バックグラウンドジョブ** として実行し、1秒未満でジョブ ID を返します。これにより、遅い評議会の実行がホストのツール呼び出し締切に当たらずに済みます。キャンセルは委任先のプロセスグループを停止します。 |
| `review_diff` | git diff のマルチモデルコードレビュー: レーンが **異なる観点**（正確性 / セキュリティ / テスト / 保守性）で並列にレビューし、それぞれが JSON の指摘を返します。決定論的な事前チェック（シークレット、危険なシェル）が下地を作り、指摘は **ファイル/行/タイトルでマージ** され、一致度ベースの確信度（single/majority/consensus）が付きます。`output_format: markdown`（既定）または `json`。パラメータ: `cwd`、`base`（既定 HEAD）、`diff`、`include_paid`、`timeout_s`。 |
| `security_review` | git diff の OWASP を踏まえた **セキュリティ専用** レビュー（インジェクション / 認証＆アクセス制御 / シークレット＆暗号 / データ露出＆SSRF）→ 深刻度順の指摘＋ `residual_risk` セクション。 |
| `debate` | 複数のモデルが質問に答え、**互いの回答を見て修正** を、限られたラウンド（既定1、最大3）にわたって行い、その後 **独立したジャッジ**（3レーン以上のときは議論から除外）が最終的なコンセンサス＋残る相違を書きます。本番運用で堅牢化済み: `context_files` は主要ファイルをすべての議論者プロンプトに注入し（**グラウンディング** — これがないと評議会はあなたのブリーフを言い換えるだけ）、**ファクトチェックパス**（無料レーン、既定でオン）が評決の検証不能なコマンド/タグ/バージョンにフラグを立て、主張には出所タグ（`[brief]`/`[own-knowledge]`/`[verified]`）が付き、薄いブリーフには linter 警告が出て、`steelman: true` は満場一致の評決に対し、ジャッジが再結論する前に1つのレーンに *反論* させます。`summary_only` は完全な立場を落とします（トークン約60〜80%削減）。`dry_run` は何かが送られる前に、プリフライトのデータマニフェスト（どのファイル/文字がどのベンダーに渡るか）を返します。パラメータ: `task`、`rounds`、`adversarial`、`context_files`、`fact_check`、`summary_only`、`allow_self_judge`、`steelman`、`dry_run`、`include_paid`、`cwd`、`timeout_s`。 |
| `consensus` | 「LLM 評議会」をより良く: 各レーンがブラインドで回答し、その後 **匿名化された回答をランク付け**（自分びいきなし）、票は **決定論的に**（Borda カウント）集計され、**ピア投票で1位の回答が逐語的に返されます** — *最良の回答を選ぶ* ことは、それらを *混ぜ合わせる* ことに勝るからです（arXiv 2603.20324: 統合はベースラインに負け、選択が勝つ、g=3.86）。`synthesize: true` は議長によるブレンド（より弱いモード）を選びます。最終回答＋ピア投票のランキング表を返します。`dry_run` は起動せずにプリフライトのデータマニフェスト（どのファイル/文字がどのベンダーに渡るか）を返します。`context_files` グラウンディングと `summary_only` に対応。パラメータ: `task`、`context_files`、`synthesize`、`summary_only`、`dry_run`、`include_paid`、`cwd`、`timeout_s`。 |
| `challenge` | ある主張を **1つの外部レーン** に批判的再評価プロンプトとともに渡します → 独立した懐疑的レビュー（誠実性ガードレール付き — 相違を捏造しません）。行動する前に、自分の結論を圧力テストしましょう。任意の `lane`。 |
| `premortem` | 各レーンが計画が **すでに失敗した** と想像し、起こりうる失敗モード＋緩和策を列挙します。優先順位付きのリスクリストにマージされます。構築する前に実行しましょう。 |
| `test_plan` | git diff または説明から、優先順位付きの **テストプラン**（挙動、エッジケース、具体的なケース）を導出します。 |
| `commit_msg` | ステージ済みの diff から **Conventional Commit** メッセージを生成します（ワーキングツリーにフォールバック）。読み取り専用 — テキストを出すだけで、コミットはしません。任意の `lane`、`cwd`。 |
| `pr_describe` | ブランチの diff ＋ベース（既定 origin/main → main）に対するコミットログから、**PR タイトル＋説明**（Summary / Changes / Testing）を生成します。読み取り専用。任意の `base`、`lane`、`cwd`。 |
| `ask_build_isolated` | **安全な書き込みモード**: ビルド可能なレーンを HEAD 地点の使い捨て git worktree で実行し、レビュー用の **diff** を取得します — 実際のリポジトリは決して変更されません。 |
| `list_models` | CLI が公開している場合に、レーンの利用可能なモデルを一覧します（`lane` パラメータ）。そうでない場合は、解決された既定モデル＋選び方を表示します。（ネイティブの list コマンドを持つレーンには `list_<lane>_models` も存在します。） |
| `conversations_list` / `conversation_show` | 最近の **円卓スレッド** を一覧（コンテキストリセット後に ID を回復）／ あるスレッドの完全なトランスクリプトをレーン別の帰属付きで表示します。 |
| `doctor` | ヘルスチェック: インストール済みの CLI、検出されたホスト、コスト/クォータの方針、クールダウン、既定値。`deep: true` は各無料レーンの認証をライブで探り、**各レーンのフラグをその `--help` と照合** します — CLI がフラグを改名/削除して cli-bridge が依存しているものがずれた場合（ドリフト）、レーンが静かに失敗する前に警告します。 |
| `usage_report` | ローカル限定の統計: 実行回数、レーン別の成功/レイテンシ、**推定** トークン数（chars/4）＋クレジット（レーン別 `CREDITS_PER_1K`）。`since`、`format=text\|json`。 |
| `usage_budget` | 今日のレーン別実行回数 対 `CLI_BRIDGE_<LANE>_DAILY_LIMIT` ＋推定支出。上限を超えたレーンにフラグを立てます。 |
| `lane_stats` | レーン別の健全性: 実行回数、失敗、連続失敗/タイムアウト、有効なクールダウン。 |
| `reset_lane_state` | レーンのクールダウン/失敗カウンタをクリアします（再ログインやクォータリセット後に）。 |
| `setup` | インストール済みレーンを、その *出典付きの* 典型プランコスト（free/limited/paid — あなたのアカウントから検出することは決してない）とともに一覧し、実際にどれを支払っているか尋ね、確認用に **プロファイル＋日次上限を推奨** します — そしてユーザーをそのプロセスに沿って案内します。 |

**人間向けの CLI** もあります — ターミナルや CI から使う同じエンジン:
`cli-bridge init`（CLI を検出＋MCP の結線を表示）、`doctor`、`ask <lane> <task>`、`ask-all`、
`ask-best --mode`、`review-diff --base origin/main --json`、`bench --lane gemini --prompt … `
（レイテンシ p50/p95/p99）、`usage`、`budget`、`jobs`、`setup --write`。PR レビュー用の
GitHub Action（セルフホストランナー）は `../../examples/github-action-pr-review.yml` を参照。

**既定では読み取り専用、書き込みはオプトイン。** 委任先は通常、分析して回答します — 編集はホストが
適用します。`agent: "build"` を渡すと **直接ファイルを編集** させられます（例: *"ask gpt to
implement this function"*）: claude → `--permission-mode acceptEdits`、gpt → `--sandbox
workspace-write`、mistral → `--agent accept-edits`、gemini → `--yolo`（または `agy`
`--dangerously-skip-permissions`）、opencode → `--agent build`。ビルド可能なレーンは
非・読み取り専用として注記され、`build` の実行がキャッシュから返されることは決してありません。

**呼び出しごとにモデルを選ぶ** には `model` を使います（例: `model: "claude-opus-4-6"`）。ホストの
内側からは、**自分と同じ系統の兄弟モデル** を相談することすらできます — `ask_<your-host>` は
明示的な `model` を必要とする別ツールとして現れるので、Claude Code から 4.8 を動かしながら
Opus 4.6 に尋ねられます。（Antigravity の `agy` には呼び出しごとのモデルフラグがありません —
自身の設定が選ぶものを使います。）

**円卓の会話。** 任意の `ask_<lane>` に `conversation: "new"` を渡すとマルチターンのスレッドを
開始できます。返された ID を再利用すれば — **別のレーンでも** — 継続できます。各レーンは共有
トランスクリプトを見ます。あなた自身のターンは「You」と印が付き、他は名前付きなので、評議会は
毎回ゼロから始める代わりに互いの上に積み上げられます。トランスクリプトはローカル（sqlite）に
保存されるので、スレッドは **ホストのコンテキストリセット（`/compact`）とサーバー再起動を生き延びます** —
`conversations_list` で回復し、`conversation_show` で読みます。スライディングウィンドウ
（`CLI_BRIDGE_CONVO_MAX_CHARS`、既定 32000）が最新のターンを保ち最古を落とすので、スレッドが
どれだけ長く続いても、ターンあたりのコストは一定に抑えられます。

opencode の場合、空の `model` は `opencode models` に現在の `opencode/*-free` リストを尋ね、
その1つを使います（$0 のレート制限ティア）。パターン＋ソートで選ばれ — 固定名は決して使わないので、
廃止された無料モデルは自動的に置き換えられます。これは **コスト安全** です: 素の `opencode/*` Zen
モデルはトークン単位で課金され（API コスト）、`opencode-go/*` はプリペイドクレジットを使うので、
既定が静かに有料モデルを選ぶことはありません — 必要なときは明示的に渡してください。ルックアップが
失敗した場合は無料のシードにフォールバックします。自分の既定を固定するには
`CLI_BRIDGE_OPENCODE_MODEL` を設定してください。

`ask_all` はレーン別の呼び出しを短く保ちます（既定45秒、最大60秒）。これにより MCP ホストは、
自身のツール呼び出し締切より前に応答を得られます。遅い/深い回答が欲しい場合は、そのレーンを
より長い `timeout_s` で直接呼び出してください。

---

## 設定

すべて環境変数です — コード編集なし。**あなたの** サブスクに合わせて調整してください:

| 変数 | 効果 |
|----------|--------|
| `CLI_BRIDGE_<LANE>_COST` | `free`、`limited`、または `paid`。`free` は `ask_all` に参加；`limited` はクォータに敏感で広域ファンアウトからは飛ばされる；`paid` はお金/クレジットを使い、既定で飛ばされる。 |
| `CLI_BRIDGE_<LANE>_ENABLED` | `false` で、CLI がインストール済みでもレーンを隠す。 |
| `CLI_BRIDGE_<LANE>_BIN` | レーンを別のバイナリに向ける（例: `CLI_BRIDGE_GEMINI_BIN=agy`）。 |
| `CLI_BRIDGE_<LANE>_MODEL` | 呼び出し元がモデルを渡さない場合の、レーンの既定モデル。 |
| `CLI_BRIDGE_PROFILE` | `saver`、`balanced`、または `max`。`max` は、呼び出し元が `include_paid` を上書きしない限り、`ask_all` に limited/paid レーンを含める。 |
| `CLI_BRIDGE_HOST` | ホストの識別を強制する（どのレーンを隠すか）。通常は自動検出。 |
| `CLI_BRIDGE_LANES_FILE` | **自分の** CLI/API をレーンとして追加する JSON ファイルへのパス。 |
| `CLI_BRIDGE_DISABLED_TOOLS` | 一覧から隠すツール名のカンマ区切り（例: `debate,premortem,test_plan`） — すべてのホストがリクエストごとに支払うスキーマのコンテキストを削ります。`doctor`/`setup` は隠せません。 |
| `CLI_BRIDGE_ENABLED_TOOLS` | 環境変数1つの **lean モード** のための許可リスト: 設定すると、これらのツール（＋ `doctor`/`setup`）だけが公開されます（例: `ask_best,ask_all,review_diff`）。 |
| `CLI_BRIDGE_<LANE>_PRIORITY` | 小さいほど `ask_cascade` で早く実行される（既定50）。好みの順序を固定。 |
| `CLI_BRIDGE_INLINE_MAX_CHARS` | これを超えると、回答はコンテキストを溢れさせる代わりにファイルに退避します（既定12000）。 |
| `CLI_BRIDGE_TERSE` | `off` / `lite`（既定）/ `full` / `ultra`。委任先プロンプトの先頭に簡潔な応答スタイルのプリアンブルを付けます（英語、内部で十分に推論し、簡潔に答え、コード/JSON はそのまま）。これによりあなたのコンテキストと委任先の出力トークンの両方を削ります。構造化ワークフローツールには決して適用されません。 |
| `CLI_BRIDGE_TERSE_MIN_CHARS` | この文字数より短いタスクには terse プリアンブルを飛ばします（既定 `0` = 決して飛ばさない）。小さなタスクはプリアンブルの固定オーバーヘッドを取り返せません。 |
| `CLI_BRIDGE_GUARD` | `off` / `warn`（既定）/ `strict`。**委任先の出力** をプロンプトインジェクション / ツールポイズニングについてスキャンします；`warn` はバナーを前置し、`strict` は本文を差し控えます。シークレット伏字化の後に実行されます。 |
| `CLI_BRIDGE_MOCK` | `1` = ドライラン: レーンはインストール済みと報告し、どの CLI も起動せずに定型の回答を返します。**CLI を1つもインストールせずに** ツール全体を試せます。 |
| `CLI_BRIDGE_RETRIES` | TRANSIENT な失敗時のリトライ回数（既定1）。不安定な CLI を初回で動かします；クォータ/認証/not-found/タイムアウトはリトライされません。 |
| `CLI_BRIDGE_TRACE_DIR` | 設定すると、各委任は伏字化された JSON トレース（argv、タイミング、出力）をここに書きます — 再現可能なデバッグ / 監査。既定でオフ。 |
| `CLI_BRIDGE_MAX_PARALLEL` | `ask_all` での同時委任起動数の上限（既定6）。幅広い評議会（多数のカスタムレーン）が小型マシンを OOM させたり、クォータをバーストさせたりするのを防ぎます。 |
| `CLI_BRIDGE_DAILY_CREDIT_CAP` | UTC 日ごとの *推定* 有料支出のハード上限。>0 で、今日の推定がそれに達すると有料レーンを拒否します — 「コスト安全」を報告だけでなく強制可能にします。無料レーンは決してゲートされません。 |
| `CLI_BRIDGE_ALLOW_LANES` | 許可リスト、例: `gemini,gpt`。空 = すべて。ロックダウン / チーム構成: これらのレーンだけが公開されます。 |
| `CLI_BRIDGE_DISABLE_BUILD` | `1` で、呼び出し元が `agent: build` を求めても、すべての委任を読み取り専用（plan）に強制します。共有マシン向け。 |
| `CLI_BRIDGE_OVERFLOW_MAX_FILES` | オーバーフローディレクトリのファイル数上限（既定200）；それを超える最古のものは刈り取られ、`/tmp` が無制限に増えないようにします。 |
| `CLI_BRIDGE_CONFIG_FILE` | JSON 設定へのパス（既定 `~/.config/cli-bridge/config.json`）。環境変数よりも親切な代替手段 — **環境変数が常に勝ちます**。下記参照。 |
| `CLI_BRIDGE_CACHE_TTL_S` | `0` = オフ（既定）。`>0` のとき、この秒数以内の同一呼び出しは、CLI を再起動する代わりにキャッシュされた回答を返します（繰り返しでクォータ/クレジットを節約；ビルド実行は決してキャッシュされません）。 |
| `CLI_BRIDGE_<LANE>_CREDITS_PER_1K` | レーンの1kトークンあたりクレジット。`usage_report`/`usage_budget` が支出を **推定** するのに使います（chars/4）。 |
| `CLI_BRIDGE_<LANE>_DAILY_LIMIT` | レーンの1日あたり最大実行回数；超過すると `usage_budget` がフラグを立てます。 |
| `CLI_BRIDGE_<LANE>_MIN_INTERVAL_S` | バースト防止の起動ペーシング: このレーンの起動間の最小秒数（既定 `0` = オフ）。無料ティアが連続呼び出しでレート制限される場合に設定（例: `2`） — 同一レーンのバーストは均等に間隔が空き、他のレーンは並列のまま。`lane_stats` はレーンがレート制限のパターンを示したときにヒントを出します。 |
| `CLI_BRIDGE_KEEP_WORKTREES` | `ask_build_isolated` の worktree を破棄せず保持します（検査用）。 |
| `CLI_BRIDGE_REVIEW_TIMEOUT_S` | `review_diff` / `security_review` のレビュアー別タイムアウト（既定180；これらは `ask_all` より意図的に重い）。 |
| `CLI_BRIDGE_OVERFLOW_TTL_H` | 退避したオーバーフローファイルが刈り取られるまでの時間（既定24）。 |
| `CLI_BRIDGE_TELEMETRY` | `off` でローカルの実行ログ / クールダウン追跡を無効化（既定オン、マシンローカルのみ）。 |
| `CLI_BRIDGE_STATE_DB` | ローカルの sqlite 状態 DB へのパス（既定 `~/.local/share/cli-bridge/state.sqlite`）。 |
| `CLI_BRIDGE_STORE_TRANSCRIPTS` | `true` で、テレメトリにより長いタスクプレビューを保持します（既定: ハッシュ＋60文字のプレビューのみ）。 |
| `CLI_BRIDGE_LOG` / `_LOG_FILE` | `debug`/`info` で、何がどこで実行されたかをログします（既定: 無音）。 |

### 設定ファイル（環境変数の壁の代わりに）

ファイルの方が好み？ `~/.config/cli-bridge/config.json` を置く（または `CLI_BRIDGE_CONFIG_FILE` で
指す）だけです。あなたが設定していない環境変数を補完します — **環境変数が常に勝ち**、ファイルが
なくても既定値はそのまま機能します:

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

### 自分の CLI を追加する（フォークなし）

`my-lanes.json` を作り、`CLI_BRIDGE_LANES_FILE=/path/to/my-lanes.json`:

```json
[
  {
    "key": "aider", "display": "Aider", "bin": "aider",
    "ask": ["--message", "{task}"], "model_flag": "--model",
    "client_ids": ["aider"], "note": "Aider one-shot via --message."
  }
]
```

これで `ask_aider` ツールが手に入ります。（組み込みキー、例えば `grok` を持つカスタムレーンは
組み込みを *上書き* します — インストール先のフラグが違うときに便利です。）

**プラグインできる広いエコシステム:** `examples/community-lanes.json` は **Aider、Goose、Plandex、
Amp、Crush、Amazon Q Developer CLI、Droid（Factory）** のベストエフォートなレーンを同梱しています —
すべて experimental かつ `limited` と印付け（*あなた* がコストを宣言するまで広域ファンアウトから外す）、
そしてすべて `doctor deep` のフラグドリフトチェックの対象です。これは何かが静かに壊れる前に、
*あなたの* マシン上で各レーンを CLI 自身の `--help` と照合します。Claude Code、Codex、
Gemini ＋ Antigravity（`agy`）、opencode、Qwen Code、Copilot、Grok はすでに組み込み済みです。
それ以外のもの（Cline、OpenHands、Continue、Roo/Kilo Code、Kimi K2 CLI、…）も、同じ3行 JSON で
追加できます — そしてこれらの CLI で MCP を話せるものは、*反対側* に座って cli-bridge を自身の
サーバーとして動かすこともできます。

### 自分の API を持ち込む（CLI 不要）

`curl` を起動して、任意の OpenAI 互換エンドポイントをラップします。キーは環境変数の中に留まり、
ファイルには決して入りません。`{task_json}` は JSON エスケープされたプロンプトです:

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

`--variable %MY_API_KEY` ＋ `--expand-header` のペア（curl ≥ 8.3）はキーを curl の *内側* に
取り込みます — プロセスリストには決して現れません。カスタムレーンが代わりに `${ENV}` シークレットを
argv に展開している場合、`doctor` が警告します。

（両方とも `../../examples/` に、コピーできる形で用意してあります。）

---

## 仕組み

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
              hides the host's own lane · only shows installed, enabled CLIs
              kills the whole process tree on timeout / cancellation
              redacts secrets · classifies errors · spills huge output to a file
```

自前のネットワーク呼び出しはありません。キーも保存しません。あなたがすでに信頼している同じバイナリを、
あなたの作業ディレクトリで実行し、回答を返すだけです。

### IDE の MCP ホストでも動く

cli-bridge は stdio 上の純粋な MCP なので、MCP 対応のどのホストでも動きます — ターミナル CLI に
限りません。Cursor / VS Code（Cline、Continue）/ Zed を **同じコマンド**（`uvx cli-bridge-mcp`、
または `<python> -m cli_bridge`）に向けてください。ホスト自身のレーンは自動的に隠され、それ以外は
すべて同一です。

### 既知の制限（正直なリスト）

- **Ban-safe は各プロバイダーの ToS に依存します。** cli-bridge は、あなたが手で実行する公式 CLI を
  動かすだけです — しかし非対話/スクリプト的な利用が *保証されて* 認可されているわけではなく、変わり
  うります。自分のアカウントを規約の範囲内で使ってください；「ban-safe」は「トークン/キーの抽出なし」と
  捉え、包括的な保証とは捉えないでください。
- **非同期ジョブはインプロセスです。** サーバー再起動は実行中のジョブを `interrupted` と印付けします —
  v1 には再起動をまたぐ再開はありません。
- **インジェクションガードはヒューリスティックです。** シグナルの強いパターンは捕まえますが、すべて
  ではありません；`warn` モードではテキストは依然ホストに届きます（委任先の出力はデータとして扱って
  ください）。
- **トークン/クレジットの数値は推定です**（chars/4 ＋ あなたの `CREDITS_PER_1K`）、決して正確では
  ありません。
- **BYO-API（curl）レーン:** `${ENV}` キーは argv に代入されるので、呼び出しの実行中はこのマシンの
  プロセスリストに現れることがあります（決してログされません — トレースは伏字化します）。可能なときは
  プロバイダー自身の CLI を優先してください；curl では、ヘッダーファイル（`curl -H @file`）が argv
  露出を避けます。
- **実験的なレーン**（`qwen`、`copilot`、`grok`）: フラグはライブで未検証 — 不具合を報告してください。
- **コストティアは出典付きの初期値で、検出ではありません** — ベンダープランの事実は2026年6月付け
  （[docs/COSTS.md](../COSTS.md)）；プラン/クォータは入れ替わり、スナップショットが古いときは `doctor`
  が警告します。
- **サンドボックス化されたホスト:** ホストがサーバーを厳格なサンドボックス（読み取り専用 FS / ネット
  ワークなし）で動かす場合、起動された CLI はそれを継承し、プロバイダーに到達できず失敗することがあり
  ます。cli-bridge はこれをハングではなく `auth`/`failed` エラーとして表面化します。

---

## 開発

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration (cross-host) tests
```

## ライセンス

MIT

---

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../assets/mark-dark.svg">
  <img src="../../assets/mark-light.svg" width="84" alt="cli-bridge">
</picture>

<sub>一方の側 · 評議会へと橋渡しされて</sub>

</div>
