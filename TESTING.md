# Tester cli-bridge avant publication

Le repo n'est **pas publié** (ni GitHub ni PyPI). On teste l'installation **locale**, puis tu
décides de publier. `uvx cli-bridge-mcp` ne marchera qu'APRÈS publication PyPI — pour l'instant on
lance le serveur depuis le dossier local.

Commande locale du serveur (ce qu'on met dans chaque host) :

```
/path/to/cli-bridge/.venv/bin/python -m cli_bridge
```

---

## 1. Smoke test direct (sans host) — déjà vérifié, refais-le si tu veux

```bash
cd /path/to/cli-bridge
.venv/bin/python -m pytest -q          # 33 tests
```

---

## 2. Tester DANS Claude Code (host = claude, lane claude cachée)

```bash
claude mcp add cli-bridge -- /path/to/cli-bridge/.venv/bin/python -m cli_bridge
```

Puis, dans Claude Code :
- `doctor deep` → doit lister gpt/gemini/mistral/opencode installés, **claude caché**, + probe auth live.
- `ask_gemini "dis bonjour"` → réponse Gemini.
- `ask_all "Python est typé dynamiquement ? oui/non" synthesize=true` → 3 réponses + synthèse.

Retirer après test : `claude mcp remove cli-bridge`

---

## 3. Tester DANS Codex (host = codex, lane gpt cachée)

⚠️ Ton `~/.codex/config.toml` a `disable_mcp = true` (ligne ~16). Il faut le mettre à `false`
(ou retirer la ligne), sinon Codex ignore tous les MCP.

Ajout via CLI :
```bash
codex mcp add cli-bridge -- /path/to/cli-bridge/.venv/bin/python -m cli_bridge
```
ou à la main dans `~/.codex/config.toml` :
```toml
[mcp_servers.cli-bridge]
command = "/path/to/cli-bridge/.venv/bin/python"
args = ["-m", "cli_bridge"]
```

Vérif : `codex mcp list` doit montrer `cli-bridge`. Puis lance codex et demande-lui :
- « appelle l'outil doctor » → doit montrer **gpt caché** (c'est l'hôte), les autres exposés.
- « appelle ask_gemini avec task='dis bonjour' » → réponse.
- « appelle ask_all avec task=... » → fan-out.

**Codex te dira ce qui marche / casse.** Note : Codex tourne souvent en sandbox read-only — si une
lane échoue avec une erreur réseau/écriture, c'est le sandbox de Codex, pas cli-bridge (voir la
section Limitation du README).

---

## 4. Tester DANS opencode (host = opencode, lane opencode cachée)

Édite `~/.config/opencode/opencode.json`, ajoute sous `"mcp"` (à côté de `garmin`) :
```json
"cli-bridge": {
  "type": "local",
  "command": [
    "/path/to/cli-bridge/.venv/bin/python",
    "-m", "cli_bridge"
  ],
  "enabled": true
}
```

Lance opencode et demande-lui d'appeler `doctor` → **opencode caché**, gpt/gemini/mistral/claude
exposés. Puis `ask_gpt`, `ask_all`, etc.

---

## 5. Ce qu'on VEUT confirmer host par host

| Host | Lane qui doit être CACHÉE | Lanes exposées attendues |
|------|---------------------------|--------------------------|
| Claude Code | `ask_claude` | gpt, gemini, mistral, opencode (+ ask_all, doctor) |
| Codex | `ask_gpt` | claude, gemini, mistral, opencode |
| opencode | `ask_opencode` | claude, gpt, gemini, mistral |

Si le self-hide ne marche pas pour un host (sa propre lane reste visible), relève le nom exact que
le host déclare : appelle `doctor`, regarde la ligne « Host (caller): **xxx** ». Si c'est un nom
qu'on n'a pas prévu, on l'ajoute aux `client_ids` de la lane (ou tu mets
`CLI_BRIDGE_HOST=<nom>` en attendant).

---

## 6. Quand tout est validé → publier

Une fois que TU es satisfait :
1. Publier sur GitHub : `gh repo create cli-bridge-mcp --public --source=. --push` (depuis le dossier).
2. (Optionnel) publier sur PyPI pour que `uvx cli-bridge-mcp` marche pour tout le monde.

**Rien n'est publié tant que tu ne lances pas ces commandes.**
