<div align="center">

<img src="../../assets/banner.gif" width="860" alt="cli-bridge — votre assistant emprunte les pouvoirs de toutes les CLI IA que vous avez déjà : lectures à contexte géant, vision, builds en parallèle, vérifications inter-éditeurs">

[English](../../README.md) · **Français** · [简体中文](README.zh-CN.md) · [Español](README.es.md) · [Português (BR)](README.pt-BR.md) · [日本語](README.ja.md) · [Deutsch](README.de.md)

</div>

_Le README anglais fait foi ; cette traduction peut être en retard sur lui._

# cli-bridge

![CI](https://github.com/JoaoBerne/cli-bridge-mcp/actions/workflows/tests.yml/badge.svg)
![PyPI](https://img.shields.io/pypi/v/cli-bridge-mcp)
![stars](https://img.shields.io/github/stars/JoaoBerne/cli-bridge-mcp?style=flat&color=yellow)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-Apache%202.0-green)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-purple)
![ban--safe](https://img.shields.io/badge/ban--safe-no%20token%20extraction-orange)

**Votre assistant ne vaut que le seul modèle que vous avez ouvert.** cli-bridge est un serveur [Model Context Protocol](https://modelcontextprotocol.io) qui lui permet d'emprunter les *autres* CLI IA que vous avez déjà — un contexte plus grand, la vision, un second avis gratuit d'un *autre éditeur*, ou un build délégué qui revient sous forme de diff relisible.

> **Pas de clés API · pas d'extraction de jetons · pas de Node · pas de démon · stdlib + `mcp` uniquement.**

### En une phrase

Vous parlez à un assistant IA. Vous en avez aussi installé d'autres, où vous êtes déjà connecté —
Claude Code, Codex, Gemini, opencode, Ollama. **cli-bridge les relie** : quand votre assistant a
besoin de quelque chose qu'il ne sait pas faire seul, il le demande à une autre CLI et vous remet le
résultat.

### Le problème que ça résout

Quel que soit votre assistant, il a des limites dures. Il ne peut pas lire un dépôt de 2 M de tokens
d'un coup, ne peut pas voir une capture d'écran, ne peut pas vous fournir une image générée, et ne
peut pas vérifier son propre travail sans biais — alors qu'*une autre CLI sur votre machine sait
faire chacune de ces choses*. cli-bridge est le pont entre elles : il lance la CLI officielle en
sous-processus (exactement comme vous le feriez à la main — pas de clés, pas d'extraction de jetons)
et renvoie la réponse à votre assistant.

Résultat : un assistant dont le plafond sur chaque axe est le *meilleur* outil de votre boîte à
outils, pas celui que vous avez ouvert par hasard.

---

## La démo en 10 secondes

Vous êtes dans Claude. Claude ne peut pas vous fournir une image. Codex, si — il écrit le code qui en
génère une puis l'exécute. Alors demandez-lui :

```
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png — write a script that renders it, then run it", zone="assets")
→ Codex writes assets/card.png · you get the path back, never a binary blob (artifact-return)
```

Votre assistant vient de gagner une capacité qu'il n'a pas. C'est toute l'idée — maintenant
généralisez-la aux lectures à contexte géant, à la vision, au travail de fond en parallèle, et à la
vérification indépendante inter-éditeurs.

_(Codex génère l'image avec **`gpt-image-2`**, un vrai modèle texte-vers-image intégré au CLI —
décompté sur votre forfait ChatGPT, sans clé API distincte (la génération d'images nécessite un forfait
**payant** ; indisponible sur l'offre gratuite). Le résultat revient sous forme de **chemin**, pas de
blob, car un binaire passe par l'artifact-return, pas par le canal texte. Une lane build peut aussi
*rendre* graphiques, diagrammes ou SVG en écrivant du code, quand c'est plus adapté.)_

### …et il délègue du vrai travail, en sûreté

`cli-bridge build <lane> "<tâche>"` confie le travail à un autre modèle qui tourne dans un **worktree
git jetable**, puis vous rend un **diff** — votre dépôt n'est jamais touché tant que vous ne
l'appliquez pas vous-même.

<p align="center">
<img src="../../assets/demo-borrow.gif" width="860" alt="cli-bridge build : opencode ajoute une fonction dans un worktree jetable et renvoie un diff relisible ; le vrai dépôt reste propre">
</p>

---

## Ce que vous gagnez — les quatre leviers

cli-bridge n'est pas une fonctionnalité, ce sont **quatre leviers**. Comprenez-les et chaque outil
ci-dessous trouve sa place :

1. **Emprunter** — atteindre une capacité que votre assistant n'a pas (vision, fenêtre de contexte
   d'1 M de tokens, un fichier généré par un agent de code, un modèle simplement meilleur pour *ça*).
2. **Répartir** — quand un abonnement atteint sa limite, continuer sur une autre lane que vous payez
   déjà.
3. **Décharger** — répartir le travail de fond laborieux et parallélisable sur des lanes
   gratuites/bon marché pendant que vous codez ailleurs.
4. **Vérifier** — faire contrôler le travail par une *famille d'éditeur différente*, parce qu'un
   modèle ne voit pas ses propres angles morts. C'est la seule chose qu'un outil mono-éditeur ne peut
   structurellement pas faire.

---

## Ce que ça débloque

Chaque bloc : une phrase sur *quand on y a recours*, l'appel exact, et *ce qu'on récupère*.

### Emprunter des capacités que votre assistant n'a pas
Chaque CLI a un super-pouvoir différent, et chacune tourne en mode non interactif — donc cli-bridge
peut la lancer. Empruntez celle qui manque à votre hôte (elle doit être installée + connectée) :

| Super-pouvoir | Quelle CLI l'a | À emprunter quand |
|------------|------------------|----------------|
| **Images** | Codex (`gpt-image-2`, **sans clé API** — forfait ChatGPT payant, pas l'offre gratuite) | votre hôte ne sait pas dessiner |
| **Contexte géant** | Gemini (fenêtre d'1 M de tokens) | un fichier/dépôt ne tient pas dans le contexte de votre hôte |
| **Connaissance fraîche** | Gemini (ancrage Google Search) · Grok (web/X en direct) ⚗️ | battre une date de coupure : *« quelle est l'API actuelle de `<lib>` ? »* |
| **Vision** | Gemini (`images=[…]`) ⚗️ | analyser une capture ou un diagramme |
| **Un deuxième avis gratuit** | Gemini (palier quotidien gratuit) · opencode · Ollama (local, 0 $) | un contre-contrôle à 0 $ |
| **Fichiers générés** | toute lane de build → artifact-return | récupérer un graphe / PDF / diagramme **par chemin** |
| **Vidéo** ⚗️ | Gemini (Veo) · Grok (Imagine) — *si votre CLI installée l'expose* | il vous faut un clip généré |

```
ask_build(lane="gpt", task="generate a 1200×630 social card to assets/card.png", zone="assets")   # Codex image → file by path, no API key (paid ChatGPT plan)
ask_gemini(task="find the bug across ./src — read the files you need", cwd="path/to/repo")         # 1M-token context
ask_gemini(task="what's the current recommended API for <lib>? check the latest docs")            # fresh knowledge (Search grounding)
ask_gemini(task="what's wrong in this UI?", images=["screenshot.png"])                             # vision (experimental)
```

⚗️ = expérimental / dépend de la version actuelle de la CLI installée (p. ex. Grok Build est en bêta) — à vérifier avec `doctor deep`.

### Ne jamais s'arrêter quand vous touchez une limite
Quand votre abonnement principal sature en plein travail. `ask_cascade` bascule sur une autre lane
que vous payez déjà, en sautant toute lane mise en pause après une erreur de quota/auth/timeout.

```
ask_cascade(task="finish wiring this endpoint")   # cheapest→strongest; a cooled-down lane is skipped
ask_best(task="…", mode="deep")                   # let the router pick the most suitable available lane
```

### Décharger le travail de fond — en parallèle, et pas cher
Quand le travail est laborieux mais pas difficile (refactos, migrations, couverture de tests).
Éclatez-le, journalisé pour qu'un redémarrage du serveur reprenne au lieu de tout recommencer ;
déléguez un build et continuez à travailler.

```
batch_run(tasks=[...], dry_run=true)                       # cost envelope first — nothing is spawned
batch_run(tasks=[...], max_calls=20, max_credits=2.0)      # then run under a hard budget (resumable)
ask_build(lane="opencode", task="add the landing page", zone="frontend", mode="direct", async=true)   # delegate, keep building
job_tail(job_id="…")  ·  build_steer(job_id="…", instruction="use Tailwind, not inline CSS")
```

### Briser l'auto-confirmation — le problème 2026 qu'un seul éditeur ne peut pas résoudre
Quand vous avez besoin de *faire confiance* à un résultat. Un modèle qui relit son propre travail (ou
celui d'un frère) ne fait que confirmer ses propres angles morts. cli-bridge met une **famille de
modèle différente** dans le siège du relecteur.

```
workflow(preset="jury", task="is this migration safe?", author_lane="gpt")            # cross-family vote, fail-closed
workflow(preset="verify_repair", task="add retry with backoff",
         builder_lane="gpt", verifier_lane="gemini")                                   # A builds, B reviews, loop to green
security_review(base="origin/main")   ·   review_diff(base="origin/main")              # OWASP, severity-ranked
```

### Obtenir un vrai deuxième avis
Quand vous êtes arrivé à une conclusion et voulez la mettre à l'épreuve, ou plusieurs modèles côte à
côte.

```
challenge(task="I'm dropping the cache layer — here's why: …")                         # one skeptic attacks it
consensus(task="which migration strategy is safest here?")                             # N answer, peer-rank the best
workflow(preset="fanout_compare", task="fix this failing test", lanes=["gpt","gemini","opencode"])
```

---

## La boîte à outils

~30 outils, groupés par intention (consulter / construire / vérifier / orchestrer). **Référence complète — chaque outil, chaque flag : [`docs/TOOLS.md`](../../docs/TOOLS.md)** (ou `cli-bridge --help`). `CLI_BRIDGE_LEAN=1` pour une surface réduite (~12 outils).

---

## Ce que vous obtenez vraiment en les combinant

Un seul assistant dont le plafond sur **chaque axe est le meilleur de l'écosystème** — pas l'outil que
vous avez ouvert ce matin : coder avec le modèle le plus fort, lire 1–2 M de tokens quand le vôtre est
trop court, répondre avec une connaissance fraîche au-delà d'une date de coupure, générer
images/vidéos, voir des captures, et retomber sur une lane gratuite/locale quand vous êtes plafonné —
réparti sur les abonnements que vous payez déjà.

La propriété émergente **qu'aucune CLI seule n'a : un vrai contrôle inter-éditeurs** — un *éditeur
différent* dans le siège du relecteur. Les sous-agents de même famille (ceux de Claude Code, de Grok)
ne peuvent que s'auto-confirmer.

La couture honnête : ceci unit des **capacités, pas un esprit** — des spawns sans état (pas de mémoire
partagée), de la latence/du coût de spawn, une qualité inégale, et l'hôte garde toujours la barre.
C'est de l'**orchestration, pas de la fusion** : vous dirigez des spécialistes, vous n'obtenez pas un
seul cerveau doté de tous les pouvoirs.

→ Forces & limites par CLI (datées, ça bouge vite) : **[docs/COMPARISON.md](../COMPARISON.md)**.

## Pourquoi cli-bridge (et pas un autre MCP « appeler d'autres modèles »)

- 🛡️ **Ban-safe par conception.** Il lance la **CLI officielle** de chaque modèle, exactement comme
  vous à la main — pas d'extraction de jeton OAuth, pas de réutilisation de clé API. Chaque CLI gère
  sa propre auth et facturation.
- 💸 **Des défauts cost-safe que vous accordez à votre forfait.** D'origine, `ask_all` / `ask_cascade`
  bâtissent un conseil *gratuit* et ne touchent jamais au quota payant sauf demande. Chaque lane
  embarque un palier sourcé des forfaits publiés de l'éditeur (datés dans
  [docs/COSTS.md](../COSTS.md), **jamais détecté depuis votre compte**) ; surchargez par lane avec
  `CLI_BRIDGE_<LANE>_COST=free|limited|paid`.
- 🔌 **Marche depuis n'importe quel hôte.** Claude Code, Codex, opencode, Cursor, VS Code
  (Cline/Continue), Zed — tout ce qui parle MCP sur stdio. La lane de l'hôte est tenue hors fan-out ;
  masquez-la avec `CLI_BRIDGE_HIDE_HOST=1`. Même un **modèle local peut être l'hôte** — voir
  [`examples/local-first-host.md`](../../examples/local-first-host.md).
- 🧭 **L'avantage inter-éditeurs est le moat.** La vérification indépendante, c'est un *éditeur
  différent* dans le siège du relecteur — la chose rare à mesure que l'IA écrit une part croissante du
  code, et précisément ce qu'un outil mono-éditeur ne peut offrir.

---

## Comment ça marche

```
host (Claude/Codex/…) ──MCP──> cli-bridge ──spawn──> official CLI ──> model
                                    │
       keeps the host's own lane out of fan-out · only shows installed, enabled CLIs
       kills the whole process tree on timeout/cancellation · redacts secrets
       classifies errors (auth/limit/failed) · spills huge output to a file
```

Aucun appel réseau propre. Aucune clé stockée. Il lance les mêmes binaires que vous utilisez déjà,
dans votre répertoire de travail, et vous rend la réponse.

<div align="center">

<img src="../../assets/demo.gif" width="860" alt="démo cli-bridge security-review : un contournement d'autorisation committé est attrapé par un conseil inter-éditeurs, fusionné en un rapport classé par sévérité, 0 $ sur les lanes gratuites">

_Run réel (vitesse 2,2×) : le levier Vérifier — `security-review` éclate les rôles OWASP sur des
modèles gratuits en parallèle (ici claude/gpt/opencode/ollama) ; ils signalent un contournement d'auth
committé en **blocker**, et `usage` montre les reçus._

</div>

---

## Écrire du code en sûreté : deux modes

Les écritures sont contenues, de deux façons — **vous choisissez** sous revue ou en mains libres :

- **`isolated` (défaut).** Édite dans un worktree git jetable et rend un **diff**. Votre arbre de
  travail n'est jamais touché.
- **`direct`.** Écrit de vrais fichiers, **mais uniquement dans une `zone` que vous déclarez**,
  derrière un verrou par zone avec un contrôle de violation de zone après le tour. Vous dans
  `backend/`, un délégué dans `frontend/`, en même temps — aucun ne peut gribouiller tout votre
  dépôt ; l'annulation est limitée à la zone, jamais un reset global.

La ré-entrée des délégués est plafonnée en profondeur (`CLI_BRIDGE_MAX_DEPTH`, défaut 1) pour qu'un
délégué mal configuré ne puisse pas fork-bomber le conseil.

---

## Démarrage rapide (≈5 min)

```bash
# Run it (no install) — uvx fetches, runs, discards:
uvx --from cli-bridge-mcp cli-bridge doctor
# or, from a clone:  python -m cli_bridge

# Point your MCP host at that same command, then:
cli-bridge doctor        # see which CLIs are detected + their resolved paths
```

### Lanes

**Intégrées :** Claude Code, Codex, Gemini (+ Antigravity `agy`), opencode, **Ollama (modèles locaux,
0 $, offline)**, Qwen Code, Copilot, Grok.

**Runtimes locaux** au-delà d'Ollama — **LM Studio · MLX · llama.cpp** — fournis en recettes
sans code : pointez `CLI_BRIDGE_LANES_FILE` vers [`examples/lmstudio.lane.json`](../../examples/lmstudio.lane.json),
[`mlx.lane.json`](../../examples/mlx.lane.json), ou [`llamacpp.lane.json`](../../examples/llamacpp.lane.json).
(Plusieurs runtimes locaux des *mêmes* poids ouverts donnent des réponses corrélées — la vraie
diversité de conseil vient d'éditeurs distincts, pas d'un second runtime local.)

**Lanes communautaires** (`examples/community-lanes.json`, expérimentales + `limited` jusqu'à ce que
vous déclariez leur coût) : Aider, Goose, Plandex, Amp, Crush, Amazon Q Developer CLI, Droid.

**Tout le reste, c'est ~3 lignes de JSON.** Ajoutez une lane personnalisée, ou enveloppez n'importe
quel endpoint compatible OpenAI en lançant `curl` (la clé reste dans curl, jamais dans argv). Voir
[`examples/`](../../examples/) pour les recettes.

---

## La partie honnête

« Plus de modèles = mieux » est *fragile* — les gros modèles partagent leurs données d'entraînement,
donc leurs erreurs sont corrélées. Nous avons mesuré notre propre affirmation centrale
(`cli-bridge eval`, sans juge LLM) : un conseil diversifié n'a **pas** attrapé plus de bugs qu'un seul
modèle fort — il a coupé les fausses alertes **~2×**. Même taux de détection, bien moins de bruit — ce
qui est exactement ce qui garde un relecteur digne de confiance plutôt qu'ignoré. **La précision est
le produit, pas le rappel.** Le harnais est livré, vous pouvez donc le confirmer sur *vos* CLI —
chiffres dans un sens comme dans l'autre dans [docs/BENCHMARKS.md](../BENCHMARKS.md).

---

## Limitations connues

- **Ban-safe = pas d'extraction de jeton/clé**, pas une garantie générale — l'usage non interactif de
  la CLI d'un fournisseur n'est pas formellement sanctionné partout et peut changer. Utilisez vos
  propres comptes dans le respect de leurs conditions.
- **Les jobs asynchrones sont en-process** — un redémarrage du serveur marque les jobs en cours
  `interrupted`. `batch_run` / `workflow` font exception : ils journalisent chaque tâche et reprennent
  via `resume_id`.
- **Le garde anti-injection est heuristique** — il attrape les motifs à fort signal, pas tout ;
  traitez la sortie d'un délégué comme de la donnée, pas des instructions.
- **Les chiffres de tokens/crédits sont des estimations** (chars/4 + votre `CREDITS_PER_1K`), jamais
  exacts.
- **Les paliers de coût sont des défauts sourcés, pas de la détection** — les faits de forfait sont
  datés ; `doctor` prévient quand l'instantané est périmé.
- **Expérimental** (`qwen`, `copilot`, `grok`, lanes communautaires, Gemini `images=`) : les flags ne
  sont pas vérifiés en live — `doctor deep` les contrôle contre le `--help` de chaque CLI sur votre
  machine.

---

## Feuille de route

Voir [`CHANGELOG.md`](../../CHANGELOG.md) pour l'historique livré. Actuellement **en exploration (non
livré)** : un mode de vérification à **oracle indépendant** (une lane d'une autre famille écrit les
tests depuis la *spec*, aveugle à l'implémentation, pour que le test attrape le bug au lieu de le
refléter) et un **failover plus fin face aux limites**. Les grandes idées de « bus » inter-agents
(spawn récursif, état partagé, protocole filaire) sont positionnées honnêtement comme une *direction*,
jamais vendues comme un protocole livré — voir [docs/ARCHITECTURE.md](../ARCHITECTURE.md).

---

## Références

Les choix de conception ci-dessus ne sont pas des intuitions — chacun correspond à un résultat de la
littérature. Chaque entrée a été vérifiée contre sa source (auteurs + lieu de publication), parce
qu'un outil qui vend de la « vérification inter-éditeurs honnête » se doit d'avoir ses propres
citations justes.

| Article | ID | Ce qu'il étaye ici |
|-------|----|--------------------|
| Du et al. — *Improving Factuality and Reasoning via Multiagent Debate* | [2305.14325](https://arxiv.org/abs/2305.14325) | `debate` : des modèles qui se critiquent battent un modèle seul |
| ReConcile — *Round-Table Conference Improves Reasoning* | [2309.13007](https://arxiv.org/abs/2309.13007) | convergence de `debate` + consensus pondéré par la confiance |
| Mixture-of-Agents | [2406.04692](https://arxiv.org/abs/2406.04692) | agrégation en couches sur des modèles diversifiés (et ses limites) |
| Chain-of-Agents | [2406.02818](https://arxiv.org/abs/2406.02818) | pipelines multi-agents spécialisés par rôle |
| CriticGPT — *LLM Critics Help Catch LLM Bugs* | [2407.00215](https://arxiv.org/abs/2407.00215) | `review_diff` / `security_review` : un critique LLM attrape des bugs que les humains ratent |
| Perez et al. — *Discovering Language Model Behaviors* (sycophantie) | [2212.09251](https://arxiv.org/abs/2212.09251) | pourquoi un juge de même famille est faible → `jury` inter-éditeurs + anonymisation des pairs |
| Wynn, Satija & Hadfield — *Talk Isn't Always Cheap* | [2509.05396](https://arxiv.org/abs/2509.05396) | modes de défaillance du débat → verdicts fail-closed, tours bornés |
| CONSENSAGENT — *Consensus via Sycophancy Mitigation* (Findings of ACL 2025) | [ACL 2025](https://aclanthology.org/2025.findings-acl.1141/) | sycophantie en consensus → « gagner sa place » / pairs anonymisés |
| Maryanskyy — *When Agents Disagree: The Selection Bottleneck* | [2603.20324](https://arxiv.org/abs/2603.20324) | `consensus` : **sélection > synthèse** (le défaut de vote déterministe entre pairs) |

> **Note d'hygiène de citation.** *Talk Isn't Always Cheap* (2509.05396) est de **Wynn, Satija &
> Hadfield** — un framework de conseil populaire le mé-cite comme « Xiong et al. ». Nous
> revérifions les attributions avant de les répéter, et le signalons parce que l'honnêteté est tout le
> propos.

## Développement

```bash
uv venv && uv pip install -e . pytest pytest-asyncio
pytest -q          # unit + integration (cross-host) tests; no real CLI or network needed
```

## Licence

Apache 2.0

---

<div align="center">

<img src="../../assets/mark.gif" width="84" alt="cli-bridge">

<sub>une rive · reliée à un conseil</sub>

</div>
