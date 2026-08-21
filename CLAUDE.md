# CLAUDE.md — operating contract

This file governs how Claude Code works in this repo. Read it at the start of
every session. `SPEC.md` is the source of truth for *what* to build; this file
is the source of truth for *how*, and for the lines that must never be crossed.

## What this project is

A **semantically neutral** library that converts agentic-system execution
telemetry into a normalized, deterministic graph. It reads trace files and
writes a graph. It is not an analyzer, not a security tool, not a runtime, not a
service. It has no opinion about what the telemetry means, and acquiring one is
the primary failure mode to guard against.

## Non-negotiable invariants

These are correctness *and* credibility requirements. A change that violates any
of them is wrong even if it passes tests.

1. **Semantic neutrality.** Core assigns no roles, no severity, no risk, no
   cost, no quality judgement, and no domain interpretation of any kind. If a
   change adds security, cost, or evaluation vocabulary to `spanweave/`, it is
   wrong — it belongs in a consumer. This is the product, not a preference: the
   library is depend-able precisely because it takes no position.

2. **Losslessness.** Every node carries its verbatim source record. Nothing is
   ever silently dropped, prettified, normalized-away, or truncated. Input the
   library cannot map becomes an `unknown` node and/or a **Diagnostic** — never
   a discard. "We didn't understand it" is a reportable outcome; "it vanished"
   is a bug.

3. **Warranted edges.** Every edge declares its kind and its warrant
   (`explicit` = the telemetry said so; `derived` = we computed it) plus the
   `basis` rule that produced it. A derived edge is **never** promoted to
   explicit. `data` edges are **never** inferred from value comparison
   (`SPEC.md` §4.2) — that is a consumer's analysis, and smuggling it in here
   would break invariant 1.

4. **Determinism.** Same input bytes → byte-identical graph, on any machine, in
   any process. No clocks, no randomness, no `hash()` (it is salted per
   process), no reliance on set or dict iteration order, no timestamps or
   hostnames in output. Input line order MUST NOT affect the result.

5. **Read-only, no network, no execution.** Core reads files and stdin and
   writes files and stdout. It never opens a socket, never fetches a URL, never
   executes or `eval`s trace content, and never uses unsafe deserialization
   (`pickle`, `yaml.load`). Trace payloads are untrusted input (`SECURITY.md`).

6. **Adapters, not model changes.** A new dialect is a new adapter plus
   fixtures. It is never a new `NodeKind`, never a new `EdgeKind`, and never a
   dialect branch or dialect-keyed table in the builder. If a dialect seems to
   require a model change, **stop** — that is a spec conversation, not a patch.

7. **The schema is a public contract.** Once `schema_version` is frozen
   (Phase 4 — deliberately *after* the `0.9.x` launch, because publishing is
   reversible and freezing is not), changes are additive-only; anything breaking
   requires a version bump and a migration note. Before the freeze, say loudly
   and often that it is unfrozen — in the README, in `--help`, and in the
   version number itself.

## Architecture invariants

- **Two stages, one seam.** Adapters own all dialect mess; the builder owns
  graphs and never learns a dialect name (`DESIGN.md` §3). Enforced by a
  module-scoped CI gate.
- **Pure and immutable.** Model types are frozen dataclasses. Annotation returns
  a new graph. No mutation of a built graph, ever.
- **Layering is one-directional** (`DESIGN.md` §2). No upward imports.
- **Closed enums.** `NodeKind` and `EdgeKind` are closed. Extending either is a
  spec change and a halt point (`AGENT.md`).
- **Degrade honestly.** Missing payloads are `absent`, not empty. Missing
  timestamps omit temporal edges and say so. Unmapped kinds become `unknown`
  plus a diagnostic. Never paper over a gap.
- **Zero runtime dependencies in core.** Extras never affect core behavior.

## Working agreement

- **Spec-first.** If the change isn't described in `SPEC.md`, update `SPEC.md`
  in the same PR before/with the code. The spec leads, the code follows.
- **Vertical slice before breadth.** One dialect end-to-end (read → adapt →
  build → query → serialize) before a second. Breadth comes from adapters on a
  proven pipeline, never from a half-built pipeline applied to many dialects.
- **Conformance is the executable spec.** Every scenario lives in
  `fixtures/conformance/` in **multiple dialects with one expected canonical
  graph** (`FIXTURES.md`). Write the fixture and its expected graph before the
  adapter. The cross-dialect equivalence test is the library's central claim.
- **Degenerate fixtures matter as much as happy ones.** Missing payloads,
  unpaired calls, clock skew, orphan parents, malformed JSON — each needs a
  fixture proving the library degrades honestly rather than crashing or lying.
- **Milestones are demoable.** Each phase in `ROADMAP.md` exits with something
  runnable you could show someone.
- **Small PRs.** One task per PR. Keep diffs reviewable.

## Coding conventions

- Python 3.11+, fully type-annotated. `ruff` + `mypy --strict` clean. `pytest`.
- Frozen dataclasses (`@dataclass(frozen=True, slots=True)`) for all model types.
- No network imports in core (`requests`, `httpx`, `socket`, `urllib.request`) —
  CI fails the build if they appear under `spanweave/`.
- No `pickle`, `yaml.load`, `eval`, `exec`, `__import__` anywhere — CI gate.
- No `hash()` in any identity or ordering path — CI gate.
- No graph libraries (`networkx`) — the type is hand-rolled with explicit,
  deterministic iteration order (`DESIGN.md` §7).
- Serialization uses stdlib `json` with `sort_keys=True` — enforced by a test.
- Public API is what `spanweave/__init__.py` exports. Everything else is
  internal and may be refactored freely.

## Definition of done (per change)

- [ ] `SPEC.md` reflects the behavior.
- [ ] Conformance fixture(s) added, including at least one degenerate case.
- [ ] Deterministic: rebuild is byte-identical, and shuffled input is identical.
- [ ] Losslessness holds: every input record maps to a node or a diagnostic.
- [ ] Neutrality gate green: no semantic vocabulary added under `spanweave/`.
- [ ] `ruff`, `mypy --strict`, `pytest` green; `make check` passes.
