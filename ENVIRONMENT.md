# ENVIRONMENT.md — runtime & toolchain contract

Ground truth for the build environment. The agent conforms to this; it does not
choose its own runtime. Kept consistent with `CLAUDE.md` — if the two disagree,
fix one deliberately, don't let them drift.

## Runtime

- Python **3.11+**.
- OS: Linux or macOS. CI runs on `ubuntu-latest`.
- CI additionally runs the test matrix on **3.11, 3.12, and 3.13**. A library
  meant to sit underneath other people's tools must not narrow their runtime.

## Toolchain

- **`pyproject.toml` is the single source of truth** for metadata and dependencies.
- Dependency tool: **uv**. The committed **`uv.lock`** pins exact versions so
  builds and graphs are reproducible byte-for-byte (`CLAUDE.md` 4). `uv.lock` is
  committed and MUST NOT be gitignored.
- Lint/format: **ruff**. Types: **mypy --strict** (code is fully type-annotated).
  Tests: **pytest**.

## Dependencies

- **Core has zero runtime dependencies.** This is a hard constraint, not a
  current state (`DESIGN.md` §7). A library that other tools depend on must not
  drag a tree into them.
- `dev` extra: ruff, mypy, pytest. Never imported by core.
- `otlp` extra (Phase 4): protobuf, for the binary OTLP form only. Core must
  work fully without it, and `make check` never installs it.
- Adding **any** core runtime dependency is a halt point (`AGENT.md`).

## Commands (exact — the agent uses these, does not invent them)

- Setup:   `uv sync --extra dev`
- Lint:    `uv run ruff check .`
- Format:  `uv run ruff format --check .`
- Types:   `uv run mypy spanweave`
- Tests:   `uv run pytest`
- Gate:    `make check` (the acceptance harness, task 0.8 — must pass before a
  task counts as done; the Makefile target wraps the `uv run ...` calls above
  plus the phase done-whens)
- Corpus:  `make conformance` (the cross-dialect equivalence suite)
- Capture: `make capture` — **human-run only**, see below

## Repo layout (expected)

- `spanweave/`            — the library. Pure, deterministic, **no network**,
  **no semantics**.
- `spanweave/adapters/`   — the only place dialect knowledge may live.
- `spanweave/cli.py`      — CLI entrypoint (`spanweave`).
- `fixtures/conformance/` — the corpus: scenarios × dialects → one canonical
  graph each (`FIXTURES.md`).
- `fixtures/captured/`    — human-captured real traces + provenance. Never
  agent-generated.
- `capture/`              — the capture harness. **Outside the package**;
  network and framework dependencies are allowed here and ONLY here.
- `examples/`             — falsification consumers (Phase 3). **Outside the
  package**; free to be as opinionated as they like, which is exactly why they
  must not live inside it (`DESIGN.md` §8).
- `tests/`                — pytest, including the invariant gates (0.4–0.6) and
  the acceptance checks (0.8).

## Network policy (three zones — do not blur them)

1. **Build / CI:** may reach PyPI (via uv) to install dependencies. Nothing else.
2. **Library core (`spanweave/`):** makes **no network connection, ever** —
   enforced by the no-network gate (task 0.4). It reads trace files and stdin
   and writes graphs to files/stdout. It never fetches a remote trace, never
   phones home, and never listens.
3. **`capture/` harness:** may use the network, a model API, and framework
   dependencies — but it is human-run (`make capture`), lives outside the
   package, and never runs in the library's path.

`examples/` may not use the network either; they consume committed fixtures so
that anyone can run them reproducibly.

## Credentials

- The **autonomous agent runs with no secrets and no API keys.** It therefore
  cannot — and must not — capture a real trace (`AGENT.md` halt point,
  `FIXTURES.md` §6).
- The single credentialed step is the human-run `make capture`, which may need a
  model API key and a framework install in the human's own environment. Keep
  keys out of the repo and out of the agent's environment.
- Captured traces are **reviewed and redacted by a human before commit**, and
  the redaction is recorded in the provenance file.
