# Acceptance harness (task 0.8). `make check` is the gate a task must pass
# before it counts as done (ENVIRONMENT.md): it wraps the exact toolchain
# commands plus the phase done-whens as runnable checks.

.PHONY: check install-check lint types test gates conformance shape stranger bench bench-smoke capture clean

check: lint types test gates bench-smoke
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

# Regenerate the committed serialized-shape artifact (TASKS.md 3.7, Option C).
# `SCHEMA_VERSION` stays "0.1" for the whole of 0.x (Option B), so the version
# number is NOT what stops a change to the serialized graph shipping unnoticed
# -- this artifact is. `make check` fails when the shape moves; regenerate here
# and commit the diff IN THE SAME CHANGE, so the move is reviewed rather than
# discovered. Never regenerate to make a failure go away: the diff is the
# finding. Nothing in it reads the corpus, so adding a fixture cannot move it.
shape:
	uv run python -m tests.schema_shape

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

# Walk the path a stranger walks, and time it (TASKS.md 3.9). Clones this repo
# into a temp directory, builds a fresh venv, runs the README's OWN `From a
# checkout` commands -- read out of the README, not restated here -- and then
# the first command of its quickstart. Prints a per-step and total time.
# It asserts that every step SUCCEEDS; it deliberately asserts nothing about
# the DURATION. A wall-clock threshold in an automated check is a flake that
# gets tuned until it means nothing, and the criterion it would guard
# ("~60 seconds", ROADMAP.md) is about a human's first minute, not this
# machine's load average. Print the number; let a human read it.
# The one substitution: the clone source is this repo on disk, since the
# harness has no network. That makes the number an UNDERESTIMATE and it says so.
# ARGS passes flags through: make stranger ARGS="--repeat 3 --quiet"
stranger:
	uv run python -m tests.stranger_path $(ARGS)

# What a live build costs (WORKPLAN.md L5, `SPEC.md` §10.6). Feeds the two
# shapes the September 2026 audit measured -- an agent loop that resends its
# history, and one root with N children -- and prints what `feed`, `graph()` and
# `delta()` cost on each, plus the share of `delta()` that the canonical-order
# sort actually is. That share is the number L5 turned on.
# It asserts NOTHING about the clock, for the reason `stranger` states above: a
# duration threshold in an automated check is a flake that gets tuned until it
# means nothing. It prints numbers; a human reads them. Not run by `check`.
# ARGS passes flags through: make bench ARGS="--only echo --turns 100"
# The wide shape's `feed` is quadratic in its own right (see the module
# docstring), so the default width takes tens of minutes.
bench:
	uv run python -m tests.live_cost $(ARGS)

# The smoke form of that harness, and the one thing in it `check` DOES run
# (WORKPLAN.md L18). It feeds eleven records and six, and asserts the SHAPE the
# numbers above are about -- the receipt count SPEC.md section 4.2.1 promises,
# one Edge built per edge the prefix holds, zero canonical sorts while feeding
# against one per materialization and two per delta, and the same bytes from the
# same records fed in a different order. Still nothing about the clock, for the
# reason `bench` and `stranger` both give: what belongs in a gate is the part
# that can be true or false. Milliseconds, so the fast gate stays fast.
bench-smoke:
	uv run python -m tests.live_cost --smoke

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
