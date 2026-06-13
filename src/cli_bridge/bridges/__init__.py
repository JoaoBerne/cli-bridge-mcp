"""Bundled stdlib bridges that let the council reach OPT-IN, key-based API endpoints the same way
it reaches a CLI: the bridge is a tiny standalone program the runner spawns as a subprocess. No new
runtime dependency (urllib only); the API key is read from an env var named on the command line, so
the key VALUE never appears in argv."""
