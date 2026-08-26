# Contributing to spanweave

The most valuable contribution is **an adapter for a telemetry dialect we don't
support yet**. The whole project is shaped to make that contribution easy to get
right and hard to get wrong.

## Ways to contribute, most to least valuable

1. **A new adapter.** One file plus fixtures. Follow `ADAPTERS.md` exactly.
2. **A captured trace** from real instrumentation, with provenance. Hand-authored
   fixtures prove we matched our *understanding* of a dialect; captured ones
   prove we matched the instrumentor (`FIXTURES.md` §6).
3. **A degenerate scenario we don't cover.** Telemetry we mishandle is a gift.
   Open an issue with the smallest trace that reproduces it — a failing scenario
   is a complete bug report.
4. **A falsification consumer.** Built something on the library that needed a
   change to it? Tell us what and why. That is direct evidence about the model's
   generality, which is the thing we most need and can least manufacture.
5. **Docs.** Especially where the specs disagree with the code — those are real
   bugs (`CLAUDE.md`, spec-first).

## Before you write code

Read, in order: `README.md`, `CLAUDE.md` (the invariants), `SPEC.md` (the part
you're touching), and `ADAPTERS.md` if it's an adapter.

The invariants are non-negotiable and a PR that violates one won't be merged
even if it works. In particular:

- **Semantic neutrality.** No roles, severity, risk, cost, or quality judgement
  in `spanweave/`. Interesting analysis belongs in *your* tool, on top of the
  graph. This is not gatekeeping — it is the only reason the library is safe for
  everyone else to depend on.
- **Losslessness.** Nothing silently dropped. When in doubt, emit a diagnostic.
- **Warranted edges.** Never infer a relation the telemetry didn't state, and
  never promote a derived edge to explicit.
- **Determinism.** No `hash()`, clocks, randomness, or input-order dependence.
- **Adapters, not model changes.** If your dialect seems to need a new
  `NodeKind` or `EdgeKind`, **open an issue first** — that's a spec conversation.

## The bar

A mergeable PR:

- [ ] Passes `make check` — lint, `mypy --strict`, tests, and all gates.
- [ ] Adds or updates conformance fixtures, including at least one degenerate
      case (`FIXTURES.md` §3).
- [ ] Passes cross-dialect equivalence against the **unmodified** expected
      graphs. If yours doesn't, the adapter is wrong or the model is — open an
      issue, don't edit the expectation (`FIXTURES.md` §4).
- [ ] Updates `SPEC.md` if behavior changed, in the same PR.
- [ ] Is small. One concern per PR.
- [ ] Has no test whose result depends on what happens to be installed on the
      machine running it. A test that asserts the *absent* branch of an
      optional dependency is green in CI and red on the developer's machine —
      it passes in every environment where it cannot catch anything. Assert
      both branches, and drive them from the test.

## Adding an adapter — the short version

1. Read `ADAPTERS.md`.
2. `spanweave/adapters/<dialect>.py` — implement `detect()` and `parse()`.
3. Register it in `spanweave/adapters/__init__.py`.
4. Render **every** scenario in `fixtures/conformance/*/dialects/<dialect>.*`.
5. `make conformance` — your renderings must produce the existing canonical
   graphs, unchanged.
6. Capture one real trace, redact it, write its provenance file.
7. `make check`, then open the PR.

Expect review to focus on three things: whether you inferred anything the
telemetry didn't say, whether the five payload states are distinguished
correctly, and whether the degenerate scenarios are handled honestly. Those are
where adapters go wrong.

## Reporting a bug

The best bug report is a **failing scenario**: the smallest trace that
reproduces it, the graph you got, and the graph you expected. If it's a
mishandled dialect, add it to the corpus and let the test speak.

## Security

Do not open a public issue for a suspected vulnerability. See `SECURITY.md`.

## License

Contributions are accepted under the MIT license (`LICENSE`). By opening a PR
you agree your contribution is licensed under it.
