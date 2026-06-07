<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../assets/banner-dark.svg">
  <img src="../../assets/banner-light.svg" width="860" alt="Vous → cli-bridge → un conseil de CLI IA en parallèle → une seule revue fusionnée">
</picture>

[English](../../README.md) · **Français** · [简体中文](README.zh-CN.md) · [Español](README.es.md) · [Português (BR)](README.pt-BR.md) · [日本語](README.ja.md) · [Deutsch](README.de.md)

</div>

_Le README en anglais fait foi ; cette traduction peut être en retard sur celui-ci._

# cli-bridge

![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/cli-bridge-mcp)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**Votre assistant IA, mais qui peut appeler un ami.**

`cli-bridge` est un serveur [Model Context Protocol](https://modelcontextprotocol.io) qui
**orchestre les CLI IA que vous avez déjà installées et auxquelles vous êtes déjà connecté** — Claude Code, Codex,
Gemini CLI, opencode, … — depuis l'assistant avec lequel vous discutez. Pas de clés d'API, pas d'extraction
de token, un journal strictement local, un plafond de coût dur, et les écritures se font uniquement sous forme de diffs dans une worktree jetable.
Ça, c'est de la plomberie incontestable ; voici ce que ça débloque :

Coincé sur un bug épineux ? Faites interroger GPT *et* Gemini en parallèle par votre assistant, puis comparez. Besoin d'une
lecture sur 1 M de tokens d'un fichier énorme ? Confiez-la à Gemini. Envie d'un second avis pas cher ? Lancez-le sur un
modèle gratuit. Une seule question, tous les modèles, côte à côte — sans quitter votre terminal.

```
You → Claude:  "ask the council whether this auth logic is safe"
Claude → cli-bridge → [ Gemini ] [ GPT ] [ Mistral ] [ Qwen ] … in parallel
            ← three independent reviews + a synthesis of where they agree & disagree
```

<div align="center">

<img src="../../assets/demo.gif" width="860" alt="Démo de security-review de cli-bridge : un contournement d'authentification commité est détecté indépendamment par deux modèles, fusionné en un seul rapport classé par sévérité, 0 $ sur les lanes gratuites">

_Exécution réelle (vitesse 2,5×) : un contournement d'authentification commité — `security-review` répartit les rôles OWASP sur des modèles
gratuits en parallèle ; deux modèles le signalent **blocker** indépendamment, et `usage` montre les preuves._

</div>

> **Pourquoi c'est différent, en un souffle :** il ne détient jamais de clé d'API et n'extrait jamais de token — il
> pilote les CLI officielles que vous avez **déjà installées et auxquelles vous êtes déjà connecté**. Un conseil sur lanes gratuites coûte
> **0,00 $** (les preuves sont dans `usage_report`) ; les lanes payantes ne s'exécutent jamais qu'à l'intérieur d'un plafond quotidien dur
> que *vous* fixez. Et quand vous lui demandez de *faire* le travail, il édite dans une worktree git jetable et vous rend
> un **diff** — votre dépôt actif n'est jamais touché.

> **Et la partie honnête :** « plus de modèles = mieux » est *fragile* — les gros modèles partagent leurs données d'entraînement,
> donc leurs erreurs sont corrélées. Nous avons mesuré notre propre affirmation centrale (`cli-bridge eval`, livré, sans juge
> LLM) : un conseil diversifié n'a **pas** détecté plus de bugs qu'un seul modèle puissant — il a réduit les fausses
> alertes **d'environ 2×**. Nous publions les chiffres dans les deux cas ([BENCHMARKS.md](../BENCHMARKS.md)), et le
> harnais est livré pour que vous puissiez le faire tourner sur *vos* CLI.

---

## Pourquoi celui-ci

Il existe d'autres MCP « appelle d'autres modèles ». Voici ce qui distingue cli-bridge :

- 🛡️ **Ban-safe par conception.** Il lance la **CLI officielle** de chaque modèle — exactement comme vous le feriez à la
  main. Pas d'extraction de token OAuth, pas de réutilisation de clé d'API, rien qui fasse flaguer un compte. Chaque CLI
  gère sa propre authentification et sa propre facturation.
- 💸 **Des coûts par défaut sourcés, puis *vous* ajustez selon votre forfait.** D'emblée, `ask_all` constitue un
  conseil gratuit et ne touche jamais à votre quota d'abonnement (Claude, GPT) ni à vos crédits payants, sauf si vous le demandez.
  Chaque lane est livrée avec un palier sourcé depuis les forfaits publiés du fournisseur
  ([docs/COSTS.md](../COSTS.md), daté) — **jamais détecté depuis votre compte, et étiqueté comme
  tel** — que vous surchargez selon vos propres abonnements
  (`CLI_BRIDGE_<LANE>_COST=free|limited|paid`) ; sur un gros forfait, marquez-les tous `free`, ou définissez
  `CLI_BRIDGE_PROFILE=max`.
- 🔌 **Fonctionne depuis n'importe quel hôte.** Vous pilotez Claude Code ? Il masque la lane Claude (pas question de vous interroger vous-même)
  et expose le reste. Vous pilotez Codex ou opencode à la place ? Même principe, détecté automatiquement depuis
  le handshake MCP.
- 🧩 **Ajoutez n'importe quelle CLI — ou votre propre API — sans forker.** Lanes intégrées pour Claude, GPT, Gemini,
  Mistral, Qwen, Copilot, Grok et opencode. Enregistrez **votre propre CLI depuis un fichier JSON**, ou encapsulez
  **votre propre API** en lançant `curl`. Zéro code.
- 🧠 **Synthèse du conseil.** `ask_all` peut faire résumer par un modèle gratuit les points sur lesquels les autres sont *d'accord* et
  *en désaccord* — transformez trois opinions en une seule décision.
- 🔬 **Workflows multi-modèles.** `review_diff` et `security_review` répartissent des relecteurs **aux rôles diversifiés**
  sur le conseil, puis fusionnent + dédoublonnent en un seul rapport classé par sévérité. `debate` fait critiquer et réviser les modèles entre eux sur un nombre borné de tours avant qu'un juge ne conclue.
- ✍️ **Lecture seule par défaut, écritures à la demande.** Activez `agent: build` pour qu'une lane capable
  **édite réellement les fichiers** — ou choisissez un `model` spécifique par appel, y compris un **frère de votre propre
  famille** (interrogez Opus 4.6 depuis Claude Code 4.8).
- 🪶 **Retours façon sous-agent.** Un délégué travaille dans son propre contexte et rend un condensé ; les sorties
  énormes débordent vers un fichier et seul un aperçu revient, pour que le contexte de votre assistant reste léger.
- 🔁 **Repli automatique.** `ask_cascade` essaie les lanes du moins cher au plus puissant et passe à la suivante lorsque
  l'une atteint un quota/une erreur d'auth/un timeout — ainsi une lane morte se dégrade en douceur au lieu de vous faire défaut.
- 🩺 **Conscient de lui-même.** La télémétrie locale suit la santé de chaque lane et met une lane en cooldown
  après des échecs répétés de quota/auth/timeout, pour que `ask_all`/`ask_cascade` la contournent.
- 🎯 **Apprend votre stack.** Notez la réponse d'une lane de 1 à 5 avec `rate_lane`, et `ask_best` privilégie les
  modèles qui gagnent vraiment chaque type de tâche **sur votre machine** — un signal de qualité local stocké en
  sqlite qui survit à `/compact` et aux redémarrages. Pas un classement public ; *vos* résultats.
- 🧱 **Durci.** Les timeouts tuent tout l'arbre de processus (pas d'orphelins qui brûlent du quota), l'annulation par l'hôte
  tue le délégué, les secrets sont masqués, les erreurs sont classées
  (`quota` / `auth` / `timeout`) pour que votre assistant sache quoi faire ensuite. Fonctionne sur
  macOS / Linux / Windows.
- 📐 **Mesuré, pas affirmé.** « Plus de modèles trouvent plus de bugs » est *falsifiable*, alors cli-bridge
  livre le test : `cli-bridge eval` oppose un conseil à un seul modèle puissant + auto-cohérence
  à **budget d'appels égal** sur un corpus de bugs de raisonnement injectés, scoré de façon déterministe (sans juge
  LLM). Il rapporte la moyenne ± écart-type avec un garde-fou « aucune différence mesurable » et un tableau gain/perte
  par bug — et publie le résultat même quand le conseil perd. Voir
  [BENCHMARKS.md § Qualité](../BENCHMARKS.md#quality--does-a-council-actually-beat-one-strong-model).

### face aux autres MCP multi-modèles

| | cli-bridge | passerelles à clé d'API | ponts par réutilisation de token |
|---|:---:|:---:|:---:|
| Ban-safe (lance la CLI officielle) | ✅ | ➖ (vos clés) | ❌ (risque CGU) |
| Aucune clé d'API à gérer | ✅ | ❌ | ✅ |
| Utilise vos abonnements existants (conseil gratuit à 0,00 $) | ✅ | ❌ | ✅ |
| Paliers de coût par forfait + plafond quotidien dur + cooldown | ✅ | ➖ | ❌ |
| Repli automatique (cascade) | ✅ | partiel | ❌ |
| Routage qui **apprend de vos résultats** | ✅ | ❌ | ❌ |
| Ajout de n'importe quelle CLI / votre propre API, sans fork | ✅ | ➖ | ❌ |
| Se masque lui-même côté hôte appelant | ✅ | s/o | ➖ |
| Mémoire de table ronde qui survit à un redémarrage | ✅ | ➖ (en mémoire) | ➖ |
| Écriture agentique sûre (worktree → diff) | ✅ | ➖ | ❌ |
| Livre une éval de qualité déterministe (conseil vs modèle unique) | ✅ | ❌ | ❌ |

---

## Démarrage rapide

### 1. Installation

```bash
# zero-install run (recommended)
uvx cli-bridge-mcp

# or install it
uv tool install cli-bridge-mcp     # or: pipx install cli-bridge-mcp
```

Vous n'obtenez une lane pour une CLI que si vous l'avez **déjà installée et que vous y êtes connecté**. cli-bridge détecte automatiquement
ce qui se trouve sur votre `PATH`. Lancez l'outil `doctor` à tout moment pour voir ce qui est branché (`doctor deep`
vérifie même chaque connexion en direct).

| Lane | CLI | Coût (typique) |
|------|-----|------|
| `ask_claude`   | [Claude Code](https://docs.claude.com/claude-code) | abonnement |
| `ask_gpt`      | [OpenAI Codex](https://github.com/openai/codex) | abonnement |
| `ask_gemini`   | Gemini CLI (ou `agy` / Antigravity) | gratuit / abonnement |
| `ask_mistral`  | Mistral Vibe | palier gratuit |
| `ask_qwen` ⚗️  | Qwen Code | clé d'API à l'usage (palier OAuth gratuit fermé en avril 2026) |
| `ask_copilot` ⚗️ | GitHub Copilot CLI | abonnement (crédits à l'usage depuis 2026-06) |
| `ask_grok` ⚗️  | xAI Grok CLI | abonnement (SuperGrok / X Premium+) |
| `ask_opencode` | passerelle [opencode](https://opencode.ai) (deepseek, qwen, glm, kimi…) | gratuit par défaut ; certains modèles consomment des crédits |

⚗️ = expérimental (flags pas encore vérifiés en direct — merci de signaler les ruptures).
Colonne Coût = le *forfait typique publié* du fournisseur en date de juin 2026 ([docs/COSTS.md](../COSTS.md)
détaille limites, fins de service et sources) — cli-bridge ne détecte jamais ce qu'une lane vous coûte *à vous* ; déclarez votre
propre forfait avec `CLI_BRIDGE_<LANE>_COST`.

### Le conseil à 0 $ (aucun abonnement)

Pas de forfait payant, pas de carte ? Vous pouvez quand même assembler un vrai conseil multi-modèles en ~5 minutes à partir de
fournisseurs offrant un **palier réellement gratuit à arrêt net** (épuisement = HTTP 429, une facture est
structurellement impossible — vérifié en juin 2026, sources dans [docs/COSTS.md](../COSTS.md)) :

```bash
# 1. Get free API keys (no card): console.groq.com · cloud.cerebras.ai ·
#    a GitHub PAT (models scope) · openrouter.ai/keys
export GROQ_API_KEY=... CEREBRAS_API_KEY=... GITHUB_MODELS_TOKEN=... OPENROUTER_API_KEY=...
# 2. Point cli-bridge at the ready-made lanes
export CLI_BRIDGE_LANES_FILE=/path/to/examples/free-apis.json
```

Ça fait **Groq** (llama-3.3-70b, 1 k req/jour) + **Cerebras** (gpt-oss-120b) + **GitHub Models**
(chaque compte GitHub a un accès gratuit) + l'étendue d'**OpenRouter `:free`** — quatre voix indépendantes
pour `ask_all`/`consensus`/`debate`, plus les modèles gratuits intégrés d'opencode s'il est installé.
Réserves : le palier gratuit de Gemini CLI **prend fin le 2026-06-18** ; les paliers gratuits évoluent en quelques semaines — consultez
[docs/COSTS.md](../COSTS.md) pour savoir ce qui était vrai au moment de la vérification.

### 2. Enregistrez-le auprès de votre hôte

**Claude Code** — une seule commande :

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
<summary><b>opencode</b> / <b>Gemini CLI</b> / autres clients MCP</summary>

Pointez la config MCP de votre client vers la commande `uvx cli-bridge-mcp` via stdio. Pareil partout.
</details>

### 3. Utilisez-le

Parlez simplement à votre assistant :

> *« Demande un second avis à Gemini sur cette fonction. »*
> *« Fais relire mon diff par tout le conseil et synthétise leurs désaccords. »* (→ `review_diff`)
> *« Fais réfléchir GPT à fond sur cette race condition. »* (→ `effort: high`)
> *« Lance une revue de sécurité sur mes changements indexés. »* (→ `security_review`)
> *« Fais débattre les modèles pour savoir si on a besoin de cette abstraction. »* (→ `debate`)
> *« Demande à gpt d'implémenter cette fonction. »* (→ `agent: build`, édite les fichiers)
> *« Demande à Opus 4.6 de revérifier mon raisonnement. »* (modèle frère, depuis Claude Code)
> *« Choisis la meilleure lane pour une revue approfondie — et retiens que celle-là a assuré. »* (→ `ask_best` + `rate_lane` ; la prochaine fois il route vers elle en priorité)

Les hôtes qui prennent en charge les prompts MCP exposent aussi `review_diff`, `security_review`, `debate`,
`premortem`, `test_plan`, `apilookup` et `cost_setup` comme commandes slash natives.

---

## Outils

| Outil | Ce qu'il fait |
|------|--------------|
| `ask_<lane>` | Interroge un seul modèle. Params : `task`, optionnels `model`, `effort`, `agent`, `cwd`, `timeout_s`, **`conversation`** (démarre/continue un fil de table ronde — voir plus bas). |
| `ask_all` | Diffuse la même question à chaque lane gratuite et non limitée en parallèle. `synthesize: true` ajoute un résumé des accords/désaccords. `include_paid: true` pour interroger aussi les lanes limitées/payantes. |
| `ask_cascade` | Interroge un seul modèle **avec repli automatique** — essaie les lanes du moins cher au plus puissant, saute celles en cooldown, passe à la suivante en cas de quota/auth/timeout. Renvoie le premier succès + une trace de ce qui a été tenté (palier de coût, latence, raison du saut). |
| `ask_best` | Choisit **une seule lane selon le mode** (`fast`/`cheap`/`deep`/`code`/`review`/`security`) à partir du coût, de la santé, de la latence mesurée **et de vos propres scores `rate_lane`**, puis l'exécute avec repli. Pour « utilise juste le bon modèle » — `ask_all` compare, `ask_cascade` fait simplement le moins cher d'abord. |
| `rate_lane` | **Apprenez au routeur.** Notez la réponse d'une lane de 1 à 5 pour un type de tâche (`mode`) → `ask_best` privilégie ensuite les lanes qui gagnent ce mode **sur votre machine**. Stocké en sqlite (survit à `/compact`/redémarrage) ; un seuil de deux notes avant qu'une lane n'oriente quoi que ce soit, pour que le feedback soit honnête, pas bruité. Chaque réponse `ask_best` affiche l'appel exact. |
| `route_plan` | Affiche l'ordre que `ask_cascade` essaierait, selon votre profil + les cooldowns actuels (lecture seule, n'exécute rien). Passez `mode` pour prévisualiser `ask_best` — y compris la note courante de chaque lane. |
| `ask_all_async` / `job_status` / `job_result` / `job_cancel` / `jobs_list` | Lance une diffusion comme **job en arrière-plan** qui renvoie un identifiant de job en <1 s, pour qu'une exécution lente du conseil ne dépasse pas l'échéance d'appel d'outil de l'hôte. L'annulation tue les groupes de processus des délégués. |
| `review_diff` | Revue de code multi-modèles d'un diff git : les lanes relisent en parallèle avec **des focus différents** (correctness / sécurité / tests / maintenabilité), chacune renvoyant des findings JSON ; des pré-vérifications déterministes (secrets, shell dangereux) les amorcent ; les findings **fusionnent par fichier/ligne/titre** avec une confiance fondée sur l'accord (single/majority/consensus). `output_format: markdown` (défaut) ou `json`. Params : `cwd`, `base` (défaut HEAD), `diff`, `include_paid`, `timeout_s`. |
| `security_review` | Revue **uniquement sécurité** d'un diff git, sensibilisée OWASP (injection / auth & contrôle d'accès / secrets & crypto / exposition de données & SSRF) → findings classés par sévérité + une section `residual_risk`. |
| `debate` | Plusieurs modèles répondent à une question, **voient les réponses des autres et révisent** sur un nombre borné de tours (défaut 1, max 3), puis un **juge indépendant** (tenu à l'écart du débat quand 3 lanes ou plus) rédige le consensus final + le désaccord restant. Durci par l'usage en production : `context_files` injecte les fichiers clés dans chaque prompt de débatteur (**ancrage** — sans lui le conseil ne fait que paraphraser votre brief), une **passe de fact-check** (lane gratuite, activée par défaut) signale les commandes/tags/versions invérifiables du verdict, les affirmations portent des tags de provenance (`[brief]`/`[own-knowledge]`/`[verified]`), un brief trop maigre reçoit un avertissement du linter, et `steelman: true` fait défendre par une lane la position *contre* un verdict unanime avant que le juge ne reconclue. `summary_only` supprime les positions complètes (~60-80 % de tokens en moins) ; `dry_run` renvoie un manifeste de données de préflight (quels fichiers/caractères vont à quels fournisseurs) avant tout envoi. Params : `task`, `rounds`, `adversarial`, `context_files`, `fact_check`, `summary_only`, `allow_self_judge`, `steelman`, `dry_run`, `include_paid`, `cwd`, `timeout_s`. |
| `consensus` | Le « conseil LLM » en mieux : chaque lane répond à l'aveugle, puis **classe les réponses anonymisées** (pas d'auto-favoritisme), les votes sont agrégés **de façon déterministe** (méthode Borda), et la **réponse classée #1 par les pairs est renvoyée telle quelle** — parce que *sélectionner* la meilleure réponse bat le fait de les *mélanger* (arXiv 2603.20324 : la synthèse perd face à la baseline ; la sélection gagne, g=3,86). `synthesize: true` opte pour un mélange par un président de séance (le mode plus faible). Renvoie la réponse finale + un tableau de classement par vote des pairs. `dry_run` renvoie un manifeste de données de préflight (quels fichiers/caractères vont à quels fournisseurs) sans rien lancer. Prend en charge l'ancrage `context_files` et `summary_only`. Params : `task`, `context_files`, `synthesize`, `summary_only`, `dry_run`, `include_paid`, `cwd`, `timeout_s`. |
| `challenge` | Confie une affirmation à **une seule lane extérieure** avec un prompt de réévaluation critique → une revue sceptique indépendante (avec un garde-fou d'intégrité — elle ne fabriquera pas de désaccord). Mettez votre propre conclusion à l'épreuve avant d'agir. `lane` optionnel. |
| `premortem` | Chaque lane imagine que le plan **a déjà échoué** et liste les modes de défaillance probables + les mitigations ; le tout fusionné en une liste de risques priorisée. Lancez-le avant de construire. |
| `test_plan` | Dérive un **plan de test** priorisé (comportements, cas limites, cas concrets) à partir d'un diff git ou d'une description. |
| `commit_msg` | Génère un message **Conventional Commit** à partir de votre diff indexé (se rabat sur la working tree). Lecture seule — produit du texte, ne commite jamais. `lane`, `cwd` optionnels. |
| `pr_describe` | Génère un **titre + description de PR** (Summary / Changes / Testing) à partir du diff de la branche + du log de commits face à une base (défaut origin/main → main). Lecture seule. `base`, `lane`, `cwd` optionnels. |
| `ask_build_isolated` | **Mode écriture sûr** : exécute une lane capable de build dans une worktree git jetable au niveau de HEAD et renvoie le **diff** à relire — votre vrai dépôt n'est jamais modifié. |
| `list_models` | Liste les modèles disponibles d'une lane (param `lane`) là où la CLI les expose ; sinon affiche le modèle par défaut résolu + comment en choisir un. (`list_<lane>_models` existe aussi pour les lanes ayant une commande de liste native.) |
| `conversations_list` / `conversation_show` | Liste les **fils de table ronde** récents (récupérer un id après une réinitialisation de contexte) / affiche la transcription complète d'un fil, attribuée par lane. |
| `doctor` | Bilan de santé : CLI installées, hôte détecté, posture coût/quota, cooldowns, valeurs par défaut. `deep: true` sonde en direct l'auth de chaque lane gratuite **et vérifie les flags de chaque lane face à son `--help`** — avertit si une CLI a renommé/supprimé un flag dont cli-bridge dépend (dérive) avant que la lane n'échoue silencieusement. |
| `usage_report` | Stats strictement locales : exécutions, succès/latence par lane, et tokens **estimés** (chars/4) + crédits (`CREDITS_PER_1K` par lane). `since`, `format=text\|json`. |
| `usage_budget` | Exécutions du jour par lane face à `CLI_BRIDGE_<LANE>_DAILY_LIMIT` + dépense estimée ; signale les lanes au-delà de leur limite. |
| `lane_stats` | Santé par lane : exécutions, échecs, échecs/timeouts consécutifs, cooldown actif. |
| `reset_lane_state` | Réinitialise les compteurs de cooldown/échecs d'une lane (après une reconnexion ou un reset de quota). |
| `setup` | Liste les lanes installées avec leur coût de forfait typique *sourcé* (free/limited/paid — jamais détecté depuis votre compte), demande lesquelles vous payez réellement, et **recommande un profil + un plafond quotidien** à confirmer — puis guide l'utilisateur pas à pas. |

Il existe aussi une **CLI humaine** — le même moteur depuis votre terminal ou votre CI :
`cli-bridge init` (détecte les CLI + affiche le câblage MCP), `doctor`, `ask <lane> <task>`, `ask-all`,
`ask-best --mode`, `review-diff --base origin/main --json`, `bench --lane gemini --prompt … `
(latence p50/p95/p99), `usage`, `budget`, `jobs`, `setup --write`. Voir
`examples/github-action-pr-review.yml` pour une GitHub Action de revue de PR (runner auto-hébergé).

**Lecture seule par défaut ; écritures sur opt-in.** Un délégué analyse et répond normalement — c'est votre hôte
qui applique les éventuelles éditions. Passez `agent: "build"` pour le laisser **éditer les fichiers directement** (par ex. *« demande à gpt d'implémenter
cette fonction »*) : claude → `--permission-mode acceptEdits`, gpt → `--sandbox
workspace-write`, mistral → `--agent accept-edits`, gemini → `--yolo` (ou `agy`
`--dangerously-skip-permissions`), opencode → `--agent build`. Les lanes capables de build sont annotées
non-lecture-seule, et une exécution `build` n'est jamais servie depuis le cache.

**Choisissez un modèle par appel** avec `model` (par ex. `model: "claude-opus-4-6"`). Depuis l'intérieur d'un hôte, vous pouvez
même consulter un **modèle frère de votre propre famille** — `ask_<your-host>` apparaît comme un outil séparé qui exige un
`model` explicite, donc depuis Claude Code vous pouvez interroger Opus 4.6 tout en faisant tourner 4.8.
(Le `agy` d'Antigravity n'a pas de flag de modèle par appel — il utilise ce que ses propres réglages sélectionnent.)

**Conversations de table ronde.** Passez `conversation: "new"` à n'importe quel `ask_<lane>` pour démarrer un fil
multi-tours ; réutilisez l'id renvoyé — **même sur une autre lane** — pour continuer. Chaque lane voit la
transcription partagée avec vos propres tours marqués « You » et les autres nommés, pour qu'un conseil puisse rebondir
les uns sur les autres au lieu de repartir de zéro à chaque fois. La transcription est stockée localement (sqlite), donc un
fil **survit à la réinitialisation de contexte de l'hôte (`/compact`) et à un redémarrage du serveur** — récupérez-en un avec
`conversations_list`, lisez-le avec `conversation_show`. Une fenêtre glissante
(`CLI_BRIDGE_CONVO_MAX_CHARS`, défaut 32000) garde les tours les plus récents et écarte les plus anciens, pour que le
coût par tour reste borné quelle que soit la durée du fil.

Pour opencode, un `model` vide demande à `opencode models` la liste `opencode/*-free` actuelle et en
utilise un (le palier à 0 $ avec limitation de débit), choisi par motif + trié — jamais un nom figé, donc un
modèle gratuit retiré est remplacé automatiquement. C'est **cost-safe** : un modèle Zen `opencode/*` nu facture
au token (coût d'API) et `opencode-go/*` dépense des crédits prépayés, donc le défaut ne sélectionne jamais silencieusement
un modèle payant — passez-les explicitement quand vous les voulez. Si la recherche échoue, il se rabat
sur une graine gratuite ; définissez `CLI_BRIDGE_OPENCODE_MODEL` pour figer votre propre défaut.

`ask_all` garde les appels par lane courts (45 s par défaut, 60 s max) pour que l'hôte MCP obtienne une réponse avant
sa propre échéance d'appel d'outil. Pour une réponse lente/approfondie, appelez cette lane directement avec un
`timeout_s` plus long.

---

## Configuration

Tout passe par des variables d'environnement — aucune édition de code. Ajustez-la à **vos** abonnements :

| Variable | Effet |
|----------|--------|
| `CLI_BRIDGE_<LANE>_COST` | `free`, `limited` ou `paid`. `free` rejoint `ask_all` ; `limited` est sensible au quota et sauté par la diffusion large ; `paid` dépense de l'argent/des crédits et est sauté par défaut. |
| `CLI_BRIDGE_<LANE>_ENABLED` | `false` pour masquer une lane même si sa CLI est installée. |
| `CLI_BRIDGE_<LANE>_BIN` | Pointe une lane vers un autre binaire (par ex. `CLI_BRIDGE_GEMINI_BIN=agy`). |
| `CLI_BRIDGE_<LANE>_MODEL` | Modèle par défaut d'une lane quand l'appelant n'en passe pas. |
| `CLI_BRIDGE_PROFILE` | `saver`, `balanced` ou `max`. `max` inclut les lanes limitées/payantes dans `ask_all` sauf si l'appelant surcharge `include_paid`. |
| `CLI_BRIDGE_HOST` | Force l'identité de l'hôte (quelle lane masquer). Normalement auto-détectée. |
| `CLI_BRIDGE_LANES_FILE` | Chemin vers un fichier JSON ajoutant **vos propres** CLI/API comme lanes. |
| `CLI_BRIDGE_DISABLED_TOOLS` | Noms d'outils séparés par des virgules à masquer du listing (par ex. `debate,premortem,test_plan`) — réduit le contexte de schéma que chaque hôte paie à chaque requête. `doctor`/`setup` ne peuvent pas être masqués. |
| `CLI_BRIDGE_ENABLED_TOOLS` | Liste d'autorisation pour un **mode allégé** en une seule variable : quand défini, seuls ces outils (+ `doctor`/`setup`) sont exposés (par ex. `ask_best,ask_all,review_diff`). |
| `CLI_BRIDGE_<LANE>_PRIORITY` | Plus bas s'exécute plus tôt dans `ask_cascade` (défaut 50). Figez votre ordre préféré. |
| `CLI_BRIDGE_INLINE_MAX_CHARS` | Au-delà, une réponse déborde vers un fichier au lieu d'inonder le contexte (défaut 12000). |
| `CLI_BRIDGE_TERSE` | `off` / `lite` (défaut) / `full` / `ultra`. Préfixe un préambule de style de réponse compact aux prompts de délégué (anglais, raisonner pleinement en interne, répondre laconiquement, code/JSON intacts) pour réduire à la fois votre contexte et les tokens de sortie du délégué. Jamais appliqué aux outils de workflow structurés. |
| `CLI_BRIDGE_TERSE_MIN_CHARS` | Saute le préambule laconique pour les tâches plus courtes que ce nombre de caractères (défaut `0` = ne jamais sauter). Les minuscules tâches ne peuvent pas rentabiliser le surcoût fixe du préambule. |
| `CLI_BRIDGE_GUARD` | `off` / `warn` (défaut) / `strict`. Scanne la **sortie du délégué** à la recherche d'injection de prompt / d'empoisonnement d'outil ; `warn` préfixe une bannière, `strict` retient le corps. S'exécute après le masquage des secrets. |
| `CLI_BRIDGE_MOCK` | `1` = dry-run : les lanes se déclarent installées et renvoient une réponse en boîte sans lancer aucune CLI. Essayez tout l'outil avec **zéro CLI installée**. |
| `CLI_BRIDGE_RETRIES` | Réessais sur un échec TRANSITOIRE (défaut 1). Fait fonctionner une CLI instable du premier coup ; quota/auth/not-found/timeout ne sont jamais réessayés. |
| `CLI_BRIDGE_TRACE_DIR` | Si défini, chaque délégation écrit ici une trace JSON masquée (argv, timing, sortie) — debug / audit reproductible. Désactivé par défaut. |
| `CLI_BRIDGE_MAX_PARALLEL` | Plafond sur les lancements simultanés de délégués dans `ask_all` (défaut 6). Empêche un large conseil (beaucoup de lanes personnalisées) de faire un OOM sur une petite machine ou d'exploser le quota. |
| `CLI_BRIDGE_DAILY_CREDIT_CAP` | Plafond dur sur la dépense payante *estimée* par jour UTC. >0 refuse une lane payante une fois que l'estimation du jour l'atteint — rend le « cost-safe » applicable, pas seulement rapporté. Les lanes gratuites ne sont jamais bloquées. |
| `CLI_BRIDGE_ALLOW_LANES` | Liste d'autorisation, par ex. `gemini,gpt`. Vide = toutes. Configurations verrouillées / d'équipe : seules ces lanes sont exposées. |
| `CLI_BRIDGE_DISABLE_BUILD` | `1` force chaque délégué en lecture seule (plan) même si un appelant demande `agent: build`. Pour les machines partagées. |
| `CLI_BRIDGE_OVERFLOW_MAX_FILES` | Plafond sur le nombre de fichiers du répertoire de débordement (défaut 200) ; les plus anciens au-delà sont élagués pour que `/tmp` ne croisse pas sans limite. |
| `CLI_BRIDGE_CONFIG_FILE` | Chemin vers une config JSON (défaut `~/.config/cli-bridge/config.json`). Une alternative plus conviviale aux variables d'env — **l'env l'emporte toujours**. Voir plus bas. |
| `CLI_BRIDGE_CACHE_TTL_S` | `0` = désactivé (défaut). Quand `>0`, un appel identique dans ce nombre de secondes renvoie la réponse mise en cache au lieu de relancer la CLI (économise quota/crédits sur les répétitions ; les exécutions de build ne sont jamais mises en cache). |
| `CLI_BRIDGE_<LANE>_CREDITS_PER_1K` | Crédits par 1 k tokens pour une lane, utilisé par `usage_report`/`usage_budget` pour **estimer** la dépense (chars/4). |
| `CLI_BRIDGE_<LANE>_DAILY_LIMIT` | Exécutions max/jour pour une lane ; `usage_budget` signale en cas de dépassement. |
| `CLI_BRIDGE_<LANE>_MIN_INTERVAL_S` | Cadençage anti-rafale des lancements : secondes minimales entre deux lancements de cette lane (défaut `0` = désactivé). Définissez-le (par ex. `2`) quand un palier gratuit limite le débit sous des appels consécutifs — les rafales sur une même lane sont espacées régulièrement, les autres lanes restent en parallèle. `lane_stats` le suggère quand une lane montre le schéma de limitation de débit. |
| `CLI_BRIDGE_KEEP_WORKTREES` | Conserve les worktrees de `ask_build_isolated` au lieu de les jeter (pour inspection). |
| `CLI_BRIDGE_REVIEW_TIMEOUT_S` | Timeout par relecteur pour `review_diff` / `security_review` (défaut 180 ; ceux-ci sont délibérément plus lourds que `ask_all`). |
| `CLI_BRIDGE_OVERFLOW_TTL_H` | Heures avant qu'un fichier de débordement déversé ne soit élagué (défaut 24). |
| `CLI_BRIDGE_TELEMETRY` | `off` pour désactiver le journal local des exécutions / le suivi des cooldowns (activé par défaut, strictement local à la machine). |
| `CLI_BRIDGE_STATE_DB` | Chemin vers la base sqlite d'état locale (défaut `~/.local/share/cli-bridge/state.sqlite`). |
| `CLI_BRIDGE_STORE_TRANSCRIPTS` | `true` pour conserver un aperçu de tâche plus long dans la télémétrie (défaut : hash + aperçu de 60 caractères seulement). |
| `CLI_BRIDGE_LOG` / `_LOG_FILE` | `debug`/`info` pour journaliser ce qui s'est exécuté où (défaut : silencieux). |

### Fichier de config (à la place d'un mur de variables d'env)

Vous préférez un fichier ? Déposez `~/.config/cli-bridge/config.json` (ou pointez `CLI_BRIDGE_CONFIG_FILE` vers un).
Il complète toute variable d'env que vous n'avez pas définie — **l'environnement l'emporte toujours**, et les défauts fonctionnent encore
sans aucun fichier :

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

### Ajoutez votre propre CLI (sans fork)

`my-lanes.json`, puis `CLI_BRIDGE_LANES_FILE=/path/to/my-lanes.json` :

```json
[
  {
    "key": "aider", "display": "Aider", "bin": "aider",
    "ask": ["--message", "{task}"], "model_flag": "--model",
    "client_ids": ["aider"], "note": "Aider one-shot via --message."
  }
]
```

Vous disposez maintenant d'un outil `ask_aider`. (Une lane personnalisée avec une clé intégrée, par ex. `grok`, *surcharge*
l'intégrée — pratique quand les flags de votre installation diffèrent.)

**L'écosystème plus large, prêt à brancher :** `examples/community-lanes.json` livre des lanes
au mieux pour **Aider, Goose, Plandex, Amp, Crush, Amazon Q Developer CLI et Droid (Factory)** —
toutes marquées expérimentales et `limited` (tenues hors de la diffusion large jusqu'à ce que *vous* déclariez ce qu'elles
vous coûtent), et toutes couvertes par la vérification de dérive de flags de `doctor deep`, qui valide chaque lane
face au `--help` propre de la CLI sur *votre* machine avant que quoi que ce soit ne casse silencieusement. Claude Code,
Codex, Gemini + Antigravity (`agy`), opencode, Qwen Code, Copilot et Grok sont déjà
intégrés. Tout le reste (Cline, OpenHands, Continue, Roo/Kilo Code, Kimi K2 CLI, …) est à
3 lignes de JSON — et n'importe laquelle de ces CLI qui parle MCP peut aussi se placer de l'*autre* côté,
en faisant tourner cli-bridge comme serveur.

### Apportez votre propre API (aucune CLI nécessaire)

Encapsulez n'importe quel endpoint compatible OpenAI en lançant `curl`. Votre clé reste dans une variable d'env, jamais dans le
fichier. `{task_json}` est le prompt, échappé en JSON :

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

La paire `--variable %MY_API_KEY` + `--expand-header` (curl ≥ 8.3) importe la clé *à l'intérieur* de
curl — elle n'apparaît jamais dans la liste des processus. `doctor` avertit si une lane personnalisée déploie plutôt un secret
`${ENV}` dans l'argv.

(Voir `examples/` pour les deux, prêts à copier.)

---

## Comment ça marche

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
              hides the host's own lane · only shows installed, enabled CLIs
              kills the whole process tree on timeout / cancellation
              redacts secrets · classifies errors · spills huge output to a file
```

Aucun appel réseau propre. Aucune clé stockée. Il exécute les mêmes binaires en lesquels vous avez déjà confiance, dans votre
répertoire de travail, et vous rend la réponse.

### Fonctionne aussi dans les hôtes MCP des IDE

cli-bridge est du MCP pur via stdio, donc n'importe quel hôte compatible MCP fonctionne — pas seulement les CLI de terminal.
Pointez Cursor / VS Code (Cline, Continue) / Zed vers la **même commande** (`uvx cli-bridge-mcp`, ou
`<python> -m cli_bridge`). La lane propre de l'hôte est auto-masquée ; tout le reste est identique.

### Limitations connues (liste honnête)

- **Le « ban-safe » dépend des CGU de chaque fournisseur.** cli-bridge n'exécute que la CLI officielle que vous lanceriez
  à la main — mais l'usage non interactif/scripté n'est pas *garanti* autorisé et peut changer. Utilisez
  vos propres comptes dans le respect de leurs conditions ; considérez « ban-safe » comme « pas d'extraction de token/clé », pas comme une
  garantie globale.
- **Les jobs async sont in-process.** Un redémarrage du serveur marque les jobs en cours comme `interrupted` — pas de
  reprise inter-redémarrage en v1.
- **Le garde-fou anti-injection est heuristique.** Il attrape les motifs à fort signal, pas tout ; en
  mode `warn` le texte atteint quand même l'hôte (traitez la sortie du délégué comme des données).
- **Les chiffres de tokens/crédits sont des estimations** (chars/4 + votre `CREDITS_PER_1K`), jamais exacts.
- **Lanes BYO-API (curl) :** une clé `${ENV}` est substituée dans l'argv, donc elle peut apparaître dans la liste des
  processus de cette machine pendant l'appel (elle n'est jamais journalisée — les traces la masquent). Préférez la
  CLI propre d'un fournisseur quand c'est possible ; pour curl, un fichier d'en-têtes (`curl -H @file`) évite l'exposition dans l'argv.
- **Lanes expérimentales** (`qwen`, `copilot`, `grok`) : les flags ne sont pas vérifiés en direct — signalez les ruptures.
- **Les paliers de coût sont des défauts sourcés, pas de la détection** — faits de forfaits fournisseurs datés de juin 2026
  ([docs/COSTS.md](../COSTS.md)) ; les forfaits/quotas évoluent, `doctor` avertit quand l'instantané est périmé.
- **Hôte en sandbox :** si votre hôte exécute le serveur dans une sandbox stricte (FS en lecture seule / pas de
  réseau), les CLI lancées en héritent et peuvent échouer à atteindre leurs fournisseurs. cli-bridge fait remonter
  cela comme une erreur `auth`/`failed` plutôt que de rester bloqué.

---

## Développement

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration (cross-host) tests
```

## Licence

MIT

---

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../assets/mark-dark.svg">
  <img src="../../assets/mark-light.svg" width="84" alt="cli-bridge">
</picture>

<sub>une rive · reliée à un conseil</sub>

</div>
