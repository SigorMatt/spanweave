# Acceptance harness (task 0.8). `make check` is the gate a task must pass
# before it counts as done (ENVIRONMENT.md): it wraps the exact toolchain
# commands plus the phase done-whens as runnable checks.

.PHONY: check install-check lint types test gates conformance capture clean

check: lint types test gates
	uv run spanweave --version

lint:
	uv run ruff check .
	uv run ruff format --check .

types:
	uv run mypy spanweave
	uv run mypy examples

test:
	uv run pytest

# The invariant gates (tasks 0.4-0.6). Called out as their own target so a
# failure names the invariant that broke rather than "some test failed".
# Names here match TASKS.md 0.4-0.6 exactly:
#   0.4  no-network / no-unsafe / no-hash()     (CLAUDE.md 4, 5)
#   0.5  neutrality / no-dialect-in-builder     (CLAUDE.md 1, 6)
#   0.6  determinism / losslessness             (CLAUDE.md 2, 4)
gates:
	uv run pytest tests/test_gates.py tests/test_determinism.py -v

# The cross-dialect equivalence suite (FIXTURES.md). Every scenario, in every
# dialect, must produce that scenario's ONE canonical graph. This is the
# library's central claim in executable form.
conformance:
	uv run pytest tests/test_conformance.py -v

# Human-run only (TASKS.md 1.9, and again at 2.6). Captures a trace from real
# instrumentation: needs framework dependencies and a model API key in YOUR
# environment. Three backends: the Anthropic SDK, or the OpenAI SDK against any
# OpenAI-compatible endpoint under either of two instrumentors -- `openai`
# (OpenInference) and `genai` (OTel GenAI), which are the matched pair 2.6
# needs. It picks whichever one you have configured and refuses if that is
# ambiguous, which -- because `genai` shares NEBIUS_API_KEY with `openai` -- is
# now the case whenever that variable alone is set. See capture/README.md.
# Lives in capture/, outside the package, so its network use never trips the
# no-network gate. The build agent runs with no key and never runs this.
# Review and redact the output, write its provenance file, THEN commit it to
# fixtures/captured/ (FIXTURES.md section 6).
# ARGS passes flags through: make capture ARGS="--backend openai --name x"
# ARGS="--backend genai --shape workflow" captures the second shape (TASKS.md
# 2.15): a workflow of two agent legs, the second linked to the first, so a real
# GenAI trace contains an invoke_workflow span and an EdgeKind.link. It is NOT
# half of 2.6's matched pair and gets its own provenance file.
# ARGS="--fleet 14" captures the scratch fleet for TASKS.md 2.2 instead: many
# deliberately unalike runs into capture/_scratch/fleet/, for the Phase 2b
# adversarial consumer. Scratch -- gitignored, no provenance, NEVER promoted
# to fixtures/captured/. Exits non-zero if the fleet is missing a shape P5
# needs; re-run, never edit a trace to add one.
capture:
	uv run --extra dev python -m capture.run $(ARGS)

# Prove that what SHIPS works (TASKS.md 3.6). Everything `check` runs happens
# under `uv run`, with the source tree on the path, so every gate it runs
# answers a question about the REPOSITORY. This target builds the sdist and
# wheel, installs the wheel into a throwaway venv, and runs it from a working
# directory outside the repo -- and *asserts* that it is doing that, rather
# than assuming it: the harness reports sys.path and spanweave.__file__ from
# inside the interpreter under test. It also audits the artifacts against what
# pyproject.toml declares they contain, and runs three planted violations, each
# of which must fail the check (tests/install_check.py, "Both directions").
#
# Deliberately NOT a prerequisite of `check`: it builds a wheel and a venv, and
# `check` is the fast gate a task must pass. CI runs both.
# ARGS passes flags through: make install-check ARGS="--skip-plants"
install-check:
	uv run python -m tests.install_check $(ARGS)

clean:
	rm -rf .mypy_cache .ruff_cache .pytest_cache out/
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
