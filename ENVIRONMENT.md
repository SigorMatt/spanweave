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
- Ships:   `make install-check` — builds the sdist and wheel, installs the
  wheel into a throwaway venv, and runs it from **outside** the repo
  (`TASKS.md` 3.6). `make check` runs everything under `uv run` with the
  source tree on the path, so it can only answer questions about the
  repository; this is the only gate that answers one about the distribution.
  Reaches PyPI only as **zone 1** does, for dependencies. It never publishes —
  that is zone 4 and human-run.
- Shape:   `make shape` — regenerates `tests/serialized_shape.json`, the
  committed shape of the serialized graph (`TASKS.md` 3.7, Option C). Under
  Option B `schema_version` never moves during `0.x`, so this artifact, not the
  version number, is what stops a change to what is serialized shipping
  unnoticed: `make check` fails when the shape moves, and the fix is to
  regenerate **and commit the diff in the same change**, never to regenerate
  until the failure goes away. It reads no fixture, so corpus growth cannot
  move it.
- Stranger: `make stranger` — walks the path a stranger walks and **times** it
  (`TASKS.md` 3.9): clone into a temp directory, fresh venv, the README's own
  `From a checkout` commands read out of the README, then the first command of
  its quickstart. It asserts every step succeeds and deliberately asserts
  **nothing about the duration** — a wall-clock threshold in an automated check
  is a flake that gets tuned until it means nothing. The clone source is this
  repo on disk, since the harness has no network, which makes the number an
  underestimate and it says so. `ARGS="--repeat 3 --quiet"`.
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
- `examples/`             — consumer code. Three exist: `fleet_aggregate` (the
  **adversarial** consumer, Phase 2b — it is the pressure that phase existed to
  apply), and the two **confirmatory** ones, `trajectory_dump` and
  `cost_latency`. **Outside the package**; free to be as opinionated as they
  like, which is exactly why they must not live inside it (`DESIGN.md` §8).
  They consume committed fixtures only, and the no-network rule below binds
  them all.
- `tests/`                — pytest, including the invariant gates (0.4–0.6) and
  the acceptance checks (0.8).

## Network policy (four zones — do not blur them)

1. **Build / CI:** may reach PyPI (via uv) to install dependencies. Nothing else.
2. **Library core (`spanweave/`):** makes **no network connection, ever** —
   enforced by the no-network gate (task 0.4). It reads trace files and stdin
   and writes graphs to files/stdout. It never fetches a remote trace, never
   phones home, and never listens.
3. **`capture/` harness:** may use the network, a model API, and framework
   dependencies — but it is human-run (`make capture`), lives outside the
   package, and never runs in the library's path.
4. **Publish (`TASKS.md` 3.10):** **outbound, credentialed, human-run.** The
   first three zones are inbound or none — build *pulls* from PyPI, core
   connects nowhere, capture *pulls* from a model API. Pushing an artifact **to**
   an external index is a fourth thing and differs in kind, not degree: it is
   outward-facing, it needs a credential the agent does not have, and a
   name-plus-version on PyPI cannot be reused, which makes it the closest thing
   in this project to irreversible. It happens from a human's environment, once
   per release. The agent may **build** the distribution (`uv build` → `dist/`)
   and may install a locally built wheel into a throwaway venv — the wheel-install
   check arriving at `TASKS.md` 3.6 reaches PyPI only as **zone 1** does, for
   dependencies. The agent must never run `uv publish`, `twine upload`, or any
   equivalent, **including to TestPyPI**, which is an external index with a
   credential like any other.

`examples/` may not use the network either; they consume committed fixtures so
that anyone can run them reproducibly.

## Credentials

- The **autonomous agent runs with no secrets and no API keys.** It therefore
  cannot — and must not — capture a real trace (`AGENT.md` halt point,
  `FIXTURES.md` §6), nor publish one line of this project anywhere.
- There are exactly **two** credentialed steps, both human-run, both in the
  human's own environment and never in the agent's:
  - a **model API key**, for `make capture`, which may also need a framework
    install;
  - a **PyPI token** (and a TestPyPI token, if the recommended
    TestPyPI-first sequence is used), for the publish — network zone 4,
    `TASKS.md` 3.10. Human-only. The agent must not hold one, must not be given
    one "just to test the upload", and prepares the publish command **unrun**.
- Keep keys out of the repo and out of the agent's environment. No token belongs
  in `pyproject.toml`, the `Makefile`, CI configuration, an example, or a task
  record — including a revoked one, which still teaches the shape.
- Captured traces are **reviewed and redacted by a human before commit**, and
  the redaction is recorded in the provenance file.
