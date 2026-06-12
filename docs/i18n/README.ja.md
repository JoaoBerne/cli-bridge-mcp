<div align="center">

<img src="../../assets/banner.gif" width="860" alt="cli-bridge — あなたのアシスタントが、すでに持っているあらゆる AI CLI の能力を借りる：巨大コンテキストの読み込み、ビジョン、並列ビルド、ベンダー横断のチェック">

[English](../../README.md) · [Français](README.fr.md) · [简体中文](README.zh-CN.md) · [Español](README.es.md) · [Português (BR)](README.pt-BR.md) · **日本語** · [Deutsch](README.de.md)

</div>

_英語版 README が正本です。この翻訳は遅れている場合があります。コミュニティによるレビューを歓迎します。_

# cli-bridge

![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/cli-bridge-mcp)
![stars](https://img.shields.io/github/stars/JoaoBerne/cli-bridge-mcp?style=flat&color=yellow)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-Apache%202.0-green)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**あなたのアシスタントは、開いたその一つのモデル以上にはなれません。** cli-bridge は [Model Context Protocol](https://modelcontextprotocol.io) サーバーで、すでに使っている*他の* AI CLI を借りられるようにします — より大きなコンテキスト、ビジョン、*別ベンダー*からの無料のセカンドオピニオン、あるいはレビュー可能な diff として返ってくる委譲ビルド。

> **API キー不要 · トークン抽出なし · Node 不要 · デーモン不要 · stdlib + `mcp` のみ。**

### ひとことで言うと

あなたは 1 つの AI アシスタントと話しています。他にもインストールしてログイン済みの CLI があります——
Claude Code、Codex、Gemini、opencode、Ollama。**cli-bridge はそれらをつなぎます**。アシスタントが単独では
できないことに出会ったら、他の CLI に依頼し、結果をあなたに届けます。

### 解決する問題

どのアシスタントを使っていても、固い限界があります。200 万トークンのリポジトリを一度に読めない、
スクリーンショットを見られない、生成画像を渡せない、自分の作業をバイアスなく検証できない——しかし
*あなたのマシン上の別の CLI なら、そのどれもができます*。cli-bridge はその橋渡しです。公式 CLI を
サブプロセスとして起動し（手で実行するのとまったく同じ——鍵なし、トークン抽出なし）、答えをアシスタントに
返します。

結果：どの軸でも上限が、たまたま開いたツールではなく、手持ちの*最良の*ツールになるアシスタント。

---

## 10 秒デモ

あなたは Claude の中にいます。Claude は画像を渡せません。Codex はできます——画像を描くコードを書いて実行する
からです。だから頼みましょう：

```
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png — write a script that renders it, then run it", zone="assets")
→ Codex writes assets/card.png · you get the path back, never a binary blob (artifact-return)
```

あなたのアシスタントは、持っていなかった能力を今得ました。それが全体のアイデアです——これを巨大コンテキストの
読み込み、ビジョン、並列の力仕事、独立したベンダー横断の検証へと拡張するのです。

_（Codex は画像を **`gpt-image-2`**——CLI に組み込まれた本物のテキスト→画像モデル——で生成します。ChatGPT
プランの利用枠で計上され、別途 API キーは不要です（画像生成は**有料**プランが必要で、無料プランでは使えません）。
結果は blob ではなく**パス**で返ります。バイナリはテキストチャネルではなく artifact-return を通るからです。
build レーンは、適している場合にコードを書いてチャート・図・SVG を*レンダリング*することもできます。）_

### …そして本物の作業を、安全に委譲する

`cli-bridge build <lane> "<タスク>"` は、**使い捨ての git ワークツリー**で動く別のモデルに作業を渡し、
**diff** を返します——あなたが自分で適用するまで、リポジトリは決して触られません。

<p align="center">
<img src="../../assets/demo-borrow.gif" width="860" alt="cli-bridge build：opencode が使い捨てワークツリーで関数を追加し、レビュー可能な diff を返す。実リポジトリはクリーンなまま">
</p>

---

## 得られるもの——4 つのレバー

cli-bridge は単一機能ではなく、**4 つのレバー**です。これを掴めば、以下のすべてのツールが収まる場所を見つけます：

1. **借りる（Borrow）** — アシスタントに欠けた能力に手を伸ばす（ビジョン、100 万トークンのコンテキスト窓、
   コーディングエージェントが生成するファイル、単に*これ*が得意なモデル）。
2. **分散する（Spread）** — あるサブスクが上限に達したら、すでに支払っている別のレーンで続行する。
3. **オフロードする（Offload）** — 退屈で並列化可能な力仕事を、安価／無料のレーンに振り分け、自分は別の所で作る。
4. **検証する（Verify）** — *別のベンダーファミリー*に作業をチェックさせる。モデルは自分の盲点を捉えられない
   から。これは単一ベンダーのツールが構造的にできない唯一のことです。

---

## これで何が可能になるか

各ブロック：*いつ使うか*の一文、正確な呼び出し、そして*何が返るか*。

### アシスタントが持たない能力を借りる
各 CLI には異なるスーパーパワーがあり、それぞれ非対話モードで動く——だから cli-bridge は起動できます。ホストに
欠けたものを借りましょう（インストール済み＋ログイン済みである必要があります）：

| スーパーパワー | どの CLI が持つか | こんなとき借りる |
|------------|------------------|----------------|
| **画像** | Codex（`gpt-image-2`、**API キー不要**——有料 ChatGPT プラン、無料プラン不可） | ホストが描けないとき |
| **巨大コンテキスト** | Gemini（100 万トークンの窓） | ファイル／リポジトリがホストのコンテキストに収まらないとき |
| **新鮮な知識** | Gemini（Google 検索グラウンディング）· Grok（ライブ web/X）⚗️ | 学習打ち切りを越える：*「`<lib>` の現在の API は？」* |
| **ビジョン** | Gemini（`images=[…]`）⚗️ | スクリーンショットや図を解析する |
| **無料のセカンドオピニオン** | Gemini（無料の日次枠）· opencode · Ollama（ローカル、0 $） | 0 $ のクロスチェック |
| **生成ファイル** | 任意のビルドレーン → artifact-return | チャート／PDF／図を**パスで**受け取る |
| **動画** ⚗️ | Gemini（Veo）· Grok（Imagine）——*インストール済み CLI が公開していれば* | 生成クリップが必要なとき |

```
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png", zone="assets")   # Codex image → file by path, no API key (paid ChatGPT plan)
ask_gemini(task="find the bug across ./src — read the files you need", cwd="path/to/repo")         # 1M-token context
ask_gemini(task="what's the current recommended API for <lib>? check the latest docs")            # fresh knowledge (Search grounding)
ask_gemini(task="what's wrong in this UI?", images=["screenshot.png"])                             # vision (experimental)
```

⚗️ = 実験的／インストール済み CLI の現在のビルドに依存（例：Grok Build はベータ）——`doctor deep` で確認。

### 上限に達しても作業を止めない
メインのサブスクがタスク途中で枯渇したとき。`ask_cascade` は、すでに支払っている別のレーンへフォールバックし、
クォータ／認証／タイムアウトのエラー後にクールダウン中のレーンをスキップします。

```
ask_cascade(task="finish wiring this endpoint")   # cheapest→strongest; a cooled-down lane is skipped
ask_best(task="…", mode="deep")                   # let the router pick the most suitable available lane
```

### 力仕事をオフロード——並列で、安く
作業が退屈だが難しくないとき（リファクタ、マイグレーション、テストカバレッジ）。ジャーナル付きで分散させ、
サーバー再起動時に最初からやり直すのではなく再開できるように。ビルドを委譲して作業を続けましょう。

```
batch_run(tasks=[...], dry_run=true)                       # cost envelope first — nothing is spawned
batch_run(tasks=[...], max_calls=20, max_credits=2.0)      # then run under a hard budget (resumable)
ask_build(lane="opencode", task="add the landing page", zone="frontend", mode="direct", async=true)   # delegate, keep building
job_tail(job_id="…")  ·  build_steer(job_id="…", instruction="use Tailwind, not inline CSS")
```

### 自己確認を打破する——単一ベンダーには解けない 2026 年の問題
結果を*信頼*する必要があるとき。自分の作業（または兄弟の作業）をレビューするモデルは、自分の盲点を確認する
だけです。cli-bridge は**別のモデルファミリー**をレビュアー席に座らせます。

```
workflow(preset="jury", task="is this migration safe?", author_lane="gpt")            # cross-family vote, fail-closed
workflow(preset="verify_repair", task="add retry with backoff",
         builder_lane="gpt", verifier_lane="gemini")                                   # A builds, B reviews, loop to green
security_review(base="origin/main")   ·   review_diff(base="origin/main")              # OWASP, severity-ranked
```

### 本物のセカンドオピニオンを得る
結論に達して、それを圧力テストしたいとき、または複数のモデルを並べて見たいとき。

```
challenge(task="I'm dropping the cache layer — here's why: …")                         # one skeptic attacks it
consensus(task="which migration strategy is safest here?")                             # N answer, peer-rank the best
workflow(preset="fanout_compare", task="fix this failing test", lanes=["gpt","gemini","opencode"])
```

---

## ツールボックス

約 30 のツールを目的別（相談 / ビルド / 検証 / オーケストレーション）に分類。**完全なリファレンス（全ツール・全フラグ）: [`docs/TOOLS.md`](../../docs/TOOLS.md)**（または `cli-bridge --help`）。`CLI_BRIDGE_LEAN=1` で約 12 ツールに絞った構成。

---

## 組み合わせると実際に何が得られるか

**あらゆる軸で天井がエコシステムの最良**となる単一のアシスタント——今朝開いたツールではなく：最強のモデルで
コーディング、自分のが短すぎるとき 1〜2M トークンを読む、学習打ち切りを越えて新鮮な知識で答える、画像／動画を
生成、スクリーンショットを見る、上限のときは無料／ローカルのレーンにフォールバック——すべて、あなたがすでに
支払っているサブスク群に分散して。

**単一の CLI には無い創発的性質：真のベンダー横断の制御**——レビュアー席に*別のベンダー*を。同一ファミリーの
サブエージェント（Claude Code の、Grok の）は自己確認しかできません。

正直な継ぎ目：これは**能力を結合するもので、知性ではない**——ステートレスな spawn（共有メモリなし）、spawn の
レイテンシ／コスト、不均一な品質、そしてホストが常に操縦します。**オーケストレーションであって融合ではない**：
あなたは専門家を指揮するのであって、全能力を持つ単一の脳を得るのではありません。

→ CLI 毎の強み＆限界（日付入り、速く変わる）：**[docs/COMPARISON.md](../COMPARISON.md)**。

## なぜ cli-bridge か（別の「他モデルを呼ぶ」MCP ではなく）

- 🛡️ **設計から ban-safe。** 各モデルの**公式 CLI** を、手で実行するのとまったく同じように起動します——OAuth
  トークン抽出なし、API キー再利用なし。各 CLI が自身の認証と課金を扱います。
- 💸 **プランに合わせて調整できる cost-safe デフォルト。** 標準で `ask_all` / `ask_cascade` は*無料*の
  評議会を組み、頼まない限り有料クォータには決して触れません。各レーンはベンダー公開プラン由来のティアを同梱
  （[docs/COSTS.md](../COSTS.md) に日付入り、**あなたのアカウントから検出しない**）；レーン毎に
  `CLI_BRIDGE_<LANE>_COST=free|limited|paid` で上書き。
- 🔌 **任意のホストから動く。** Claude Code、Codex、opencode、Cursor、VS Code（Cline/Continue）、Zed——
  stdio 上で MCP を話すものなら何でも。ホスト自身のレーンはファンアウトから外され；`CLI_BRIDGE_HIDE_HOST=1`
  で隠せます。**ローカルモデルさえホストになれます**——[`examples/local-first-host.md`](../../examples/local-first-host.md) を参照。
- 🧭 **ベンダー横断の優位が堀。** 独立検証とはレビュアー席に*別のベンダー*を置くこと——AI がコードのより大きな
  割合を書くにつれて希少になるもので、まさに単一ベンダーのツールが提供できないものです。

---

## 仕組み

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
       keeps the host's own lane out of fan-out · only shows installed, enabled CLIs
       kills the whole process tree on timeout/cancellation · redacts secrets
       classifies errors (auth/limit/failed) · spills huge output to a file
```

自前のネットワーク呼び出しなし。鍵の保存なし。あなたがすでに信頼している同じバイナリを、あなたの作業ディレクトリ
で実行し、答えを返します。

<div align="center">

<img src="../../assets/demo.gif" width="860" alt="cli-bridge security-review デモ：コミットされた認可バイパスをベンダー横断の評議会が捕捉し、重大度順の 1 つのレポートにマージ、無料レーンで 0 $">

_実走（2.2 倍速）：検証レバー——`security-review` が OWASP の役割を無料モデルに並列で振り分け（ここでは
claude/gpt/opencode/ollama）；コミットされた認可バイパスを **blocker** として指摘し、`usage` が証跡を示します。_

</div>

---

## コードを安全に書く：2 つのモード

書き込みは 2 通りで封じ込められます——**あなたが選ぶ** レビュー付きかハンズオフか：

- **`isolated`（デフォルト）。** 使い捨ての git ワークツリーで編集し、**diff** を返す。あなたの作業ツリーは
  決して触られません。
- **`direct`。** 実ファイルを書きますが、**あなたが宣言した `zone` の内側だけ**、ゾーン毎ロック＋ターン後の
  ゾーン違反チェックの背後で。あなたが `backend/`、委譲先が `frontend/` を同時に——どちらもリポジトリ全体に
  落書きできません；取り消しはゾーン範囲で、グローバルリセットには決してなりません。

委譲の再入は深さで上限（`CLI_BRIDGE_MAX_DEPTH`、デフォルト 1）——設定ミスの委譲先が評議会を fork-bomb
できないように。

---

## クイックスタート（約 5 分）

```bash
# Run it (no install) — uvx fetches, runs, discards:
uvx --from cli-bridge-mcp cli-bridge doctor
# or, from a clone:  python -m cli_bridge

# Point your MCP host at that same command, then:
cli-bridge doctor        # see which CLIs are detected + their resolved paths
```

### レーン

**内蔵：** Claude Code、Codex、Gemini（＋ Antigravity `agy`）、opencode、**Ollama（ローカルモデル、0 $、
オフライン）**、Qwen Code、Copilot、Grok。

**Ollama 以外のローカルランタイム**——**LM Studio · MLX · llama.cpp**——はコード不要のレシピで同梱：
`CLI_BRIDGE_LANES_FILE` を [`examples/lmstudio.lane.json`](../../examples/lmstudio.lane.json)、
[`mlx.lane.json`](../../examples/mlx.lane.json)、または [`llamacpp.lane.json`](../../examples/llamacpp.lane.json)
に向けます。（*同じ*オープン重みの複数ローカルランタイムは相関した回答を返します——本当の評議会の多様性は
別々のベンダーから来るのであって、2 つ目のローカルランタイムからではありません。）

**コミュニティレーン**（`examples/community-lanes.json`、実験的＋コストを宣言するまで `limited`）：
Aider、Goose、Plandex、Amp、Crush、Amazon Q Developer CLI、Droid。

**それ以外は約 3 行の JSON。** カスタムレーンを追加するか、`curl` を起動して任意の OpenAI 互換エンドポイントを
ラップ（鍵は curl の内側に留まり、argv には決して載りません）。レシピは [`examples/`](../../examples/) を参照。

---

## 正直なところ

「モデルが多い＝良い」は*脆弱*です——大きなモデルは学習データを共有するため、誤りが相関します。私たちは自分の
中心的主張を測定しました（`cli-bridge eval`、LLM 審判なし）：多様な評議会は単一の強いモデルより多くのバグを
捕まえ**ませんでした**——誤検知を**約 2 倍**減らしました。同じ検出率、はるかに少ないノイズ——これこそ、
レビュアーを黙殺されるのでなく信頼に値するものに保つものです。**精度こそが製品で、再現率ではありません。**
ハーネスは同梱されるので、*あなたの* CLI で確認できます——どちらの数字も [docs/BENCHMARKS.md](../BENCHMARKS.md) に。

---

## 既知の制限

- **Ban-safe ＝トークン／鍵を抽出しない**、包括的な保証ではありません——プロバイダー CLI の非対話利用は
  どこでも公式に容認されているわけではなく、変わり得ます。自分のアカウントを各規約の範囲で使ってください。
- **非同期ジョブはインプロセス**——サーバー再起動で実行中ジョブは `interrupted` になります。`batch_run` /
  `workflow` は例外：各タスクをジャーナルし `resume_id` で再開します。
- **インジェクションガードはヒューリスティック**——高シグナルのパターンを捕まえますが、すべてではありません；
  委譲先の出力は命令ではなくデータとして扱ってください。
- **トークン／クレジットの数値は推定**（chars/4 ＋あなたの `CREDITS_PER_1K`）、決して正確ではありません。
- **コストティアは出典付きのデフォルトで、検出ではない**——プランの事実は日付入り；スナップショットが古いと
  `doctor` が警告します。
- **実験的**（`qwen`、`copilot`、`grok`、コミュニティレーン、Gemini `images=`）：フラグはライブ検証
  されていません——`doctor deep` があなたのマシンで各 CLI の `--help` に対して確認します。

---

## ロードマップ

出荷済みの履歴は [`CHANGELOG.md`](../../CHANGELOG.md) を参照。現在**探索中（未出荷）**：**独立オラクル**
検証モード（別ファミリーのレーンが実装に盲目のまま*仕様*からテストを書くので、テストがバグを映すのでなく
捕まえる）と、より細かい**上限を意識したフェイルオーバー**。大きなエージェント間「バス」構想（再帰的 spawn、
共有状態、ワイヤープロトコル）は、出荷済みプロトコルとして売るのでなく、正直に*方向性*として位置づけて
います——[docs/ARCHITECTURE.md](../ARCHITECTURE.md) を参照。

---

## 参考文献

上記の設計判断は雰囲気ではありません——それぞれが文献の知見に対応します。各エントリは出典（著者＋発表の場）
に対して確認しました。「正直なベンダー横断の検証」を売るツールは、自身の引用を正しく扱うべきだからです。

| 論文 | ID | ここで何を裏付けるか |
|-------|----|--------------------|
| Du et al. — *Improving Factuality and Reasoning via Multiagent Debate* | [2305.14325](https://arxiv.org/abs/2305.14325) | `debate`：互いを批評するモデルは単一モデルに勝る |
| ReConcile — *Round-Table Conference Improves Reasoning* | [2309.13007](https://arxiv.org/abs/2309.13007) | `debate` の収束＋確信度加重の合意 |
| Mixture-of-Agents | [2406.04692](https://arxiv.org/abs/2406.04692) | 多様なモデル横断の階層集約（およびその限界） |
| Chain-of-Agents | [2406.02818](https://arxiv.org/abs/2406.02818) | 役割特化のマルチエージェントパイプライン |
| CriticGPT — *LLM Critics Help Catch LLM Bugs* | [2407.00215](https://arxiv.org/abs/2407.00215) | `review_diff` / `security_review`：LLM 批評者が人間の見逃すバグを捕まえる |
| Perez et al. — *Discovering Language Model Behaviors*（追従性） | [2212.09251](https://arxiv.org/abs/2212.09251) | 同一ファミリーの審判が弱い理由 → ベンダー横断 `jury` ＋ピア匿名化 |
| Wynn, Satija & Hadfield — *Talk Isn't Always Cheap* | [2509.05396](https://arxiv.org/abs/2509.05396) | 討論の故障モード → fail-closed 評決、有限ラウンド |
| CONSENSAGENT — *Consensus via Sycophancy Mitigation*（Findings of ACL 2025） | [ACL 2025](https://aclanthology.org/2025.findings-acl.1141/) | 合意における追従性 → 「席を勝ち取る」／匿名化ピア |
| Maryanskyy — *When Agents Disagree: The Selection Bottleneck* | [2603.20324](https://arxiv.org/abs/2603.20324) | `consensus`：**選択 > 統合**（決定論的ピア投票のデフォルト） |

> **引用衛生のメモ。** *Talk Isn't Always Cheap*（2509.05396）は **Wynn, Satija & Hadfield** によるもの——
> 人気の評議会フレームワークがこれを「Xiong et al.」と誤引用しています。私たちは繰り返す前に帰属を二重チェック
> し、正直さがすべての訴求点なので明示します。

## 開発

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration (cross-host) tests; no real CLI or network needed
```

## ライセンス

Apache 2.0

---

<div align="center">

<img src="../../assets/mark.gif" width="84" alt="cli-bridge">

<sub>片岸 · 評議会へと架かる</sub>

</div>
