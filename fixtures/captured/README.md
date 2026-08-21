# fixtures/captured/

Traces produced by **real instrumentation on real runs**. Currently empty —
the first one lands at `TASKS.md` 1.9, and it is a human-run step.

## Rules

1. **Never hand-authored, never synthesized.** An autonomous agent must not
   produce a file here (`AGENT.md` halt point). A fabricated "captured" trace
   would destroy the only thing this directory is for.
2. **Every file needs `<name>.provenance.md`**, recording:
   - the instrumentor and its exact version,
   - the framework / SDK and version,
   - the model or runtime, if relevant,
   - the date captured,
   - the exact command run,
   - **what was redacted before commit, and by whom**,
   - **what this fixture is allowed to be used to claim.**
3. **Human review and redaction before commit.** Never commit credentials,
   customer data, or personal information (`SECURITY.md`).

## Why these exist

A hand-authored fixture in `conformance/` proves an adapter matches *our
understanding* of a dialect. Only a captured trace proves it matches *the
instrumentor*. Those are different claims, and the second is the one that
matters the moment someone points the library at their own stack.

If a captured trace and a hand-authored one disagree, **the captured one is
right** and the adapter is wrong.
