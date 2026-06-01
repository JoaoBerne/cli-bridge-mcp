---
name: Lane request
about: Ask for a new built-in CLI lane
title: "[lane] "
labels: lane-request
---

**Which CLI?**
Name + link to the official CLI.

**Install + auth**
How is it installed, and how does a user log in (subscription / free tier / API key)?

**Invocation**
The exact non-interactive command to send one prompt and get an answer, e.g.:

```
mycli --print "the prompt"
```

- Model selection flag (if any):
- Reasoning/effort flag (if any):
- Write/build mode flag (if any):
- How to list models (if any):

**Cost**
Is it free, quota-limited, or paid/credits for a typical user?

> Tip: you may not need a built-in lane — you can add any CLI yourself via
> `CLI_BRIDGE_LANES_FILE` (see `examples/lanes.example.json`).
