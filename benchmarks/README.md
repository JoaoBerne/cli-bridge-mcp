# Eval harness (outside the package, not in CI)

Does a council of distinct models beat one strong model + self-consistency? `eval.py` measures it
against the fixture corpus in `fixtures/evalset/` with a deterministic scorer (no LLM judge).

    PYTHONPATH=src python benchmarks/eval.py          # offline: proves the scorer (calibration gate)
    PYTHONPATH=src python benchmarks/eval.py --live --council-lanes gpt,gemini,mistral,opencode --single-lane gpt --k 4 --repeats 5
    pytest benchmarks/tests -q                        # scorer tests
