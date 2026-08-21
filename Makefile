# Acceptance harness (task 0.8). `make check` is the gate a task must pass
# before it counts as done (ENVIRONMENT.md): it wraps the exact toolchain
# commands plus the phase done-whens as runnable checks.

.PHONY: check lint types test gates conformance capture clean

check: lint types test gates
	uv run spanweave --version

lint:
	uv run ruff check .
	uv run ruff format --check .

types:
	uv run mypy spanweave

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

# Human-run only (TASKS.md 1.9). Captures a trace from real instrumentation:
# needs framework dependencies and a model API key in YOUR environment. Two
# backends: the Anthropic SDK, or the OpenAI SDK against any OpenAI-compatible
# endpoint. It picks whichever one you have configured and refuses if that is
# ambiguous -- see capture/README.md.
# Lives in capture/, outside the package, so its network use never trips the
# no-network gate. The build agent runs with no key and never runs this.
# Review and redact the output, write its provenance file, THEN commit it to
# fixtures/captured/ (FIXTURES.md section 6).
# ARGS passes flags through: make capture ARGS="--backend openai --name x"
# ARGS="--fleet 8" captures the scratch fleet for TASKS.md 2.2 instead: many
# deliberately unalike runs into capture/_scratch/fleet/, for the Phase 2b
# adversarial consumer. Scratch -- gitignored, no provenance, NEVER promoted
# to fixtures/captured/. Exits non-zero if the fleet is missing a shape P5
# needs; re-run, never edit a trace to add one.
capture:
	uv run --extra dev python -m capture.run $(ARGS)

clean:
	rm -rf .mypy_cache .ruff_cache .pytest_cache out/
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
