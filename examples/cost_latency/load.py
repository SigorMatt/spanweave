"""A generated load input, for checking an extrapolation. **Not a fixture.**

`TASKS.md` 3.4 permits one, in exactly these words: *"A generated load input
may be used to check the extrapolation. It is a **load input, not a fixture**:
it says nothing about what real traces contain, it is gitignored, it never
enters `fixtures/`, and it is never described as captured."*

So, plainly, and once:

* **This file is synthesized.** It is not captured, it is not a recording of
  anything, and no claim about what real telemetry looks like may be made from
  it. Its payloads are filler of a chosen length and its token counts are
  invented. The only question it can answer is *how does resident memory scale
  with span count and payload size*, which is arithmetic, not dialectics.
* **It never enters `fixtures/`.** ``generate`` refuses to write there, so the
  rule is enforced rather than remembered (`AGENT.md`'s fabrication halt
  point). The default destination is ``out/``, which is gitignored.
* **It is one dialect's records, and that is the one place in this consumer a
  dialect name appears.** The attributor itself never learns one; a generator
  necessarily does, because it has to emit something an adapter can read.
"""

from __future__ import annotations

import json
import pathlib

#: Records are OpenInference LLM spans, the smallest shape that carries both
#: token counts and timestamps — which is the whole of what the attributor
#: reads. Deliberately minimal: a richer record would make the memory figure a
#: measurement of this generator's imagination.
ADAPTER = "openinference"

#: Refused destinations. `fixtures/` holds the committed corpus, and a
#: generated file arriving there is the failure `FIXTURES.md` §6 exists to
#: prevent — a synthesized trace sitting where a captured one is expected.
FORBIDDEN = ("fixtures",)


class RefusedDestination(Exception):
    """Raised rather than writing a generated trace where fixtures live."""


def _check(path: pathlib.Path) -> None:
    parts = {part.lower() for part in path.resolve().parts}
    if parts & set(FORBIDDEN):
        raise RefusedDestination(
            f"refusing to write a generated load input to {path}: it is not a "
            f"fixture and must never sit where the committed corpus does "
            f"(`FIXTURES.md` §6, `AGENT.md`). Write it to `out/` instead."
        )


def records(spans: int, payload_chars: int) -> list[dict[str, object]]:
    """``spans`` OpenInference LLM spans with payloads of the given length.

    Deterministic: no clock, no randomness. Span *n* gets timestamps and token
    counts derived from *n*, so the same arguments give the same bytes.
    """
    filler = "x" * payload_chars
    out: list[dict[str, object]] = []
    for index in range(spans):
        out.append(
            {
                "trace_id": "load",
                "span_id": f"load{index:08d}",
                "parent_id": None if index == 0 else "load00000000",
                "name": "generated span",
                "start_time": 1_700_000_000.0 + index,
                "end_time": 1_700_000_000.5 + index,
                "status": "OK",
                "attributes": {
                    "openinference.span.kind": "LLM",
                    "llm.model_name": "demo-model",
                    "llm.token_count.prompt": 100 + (index % 97),
                    "llm.token_count.completion": 10 + (index % 31),
                    "input.value": json.dumps({"prompt": filler}),
                    "input.mime_type": "application/json",
                    "output.value": json.dumps({"completion": filler}),
                    "output.mime_type": "application/json",
                },
            }
        )
    return out


def generate(
    path: str | pathlib.Path, *, spans: int, payload_chars: int
) -> pathlib.Path:
    """Write the load input. Returns the path it wrote.

    Overwrites: the file is regenerated output, not a source artifact.
    """
    destination = pathlib.Path(path)
    _check(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for record in records(spans, payload_chars):
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    return destination


def default_path(spans: int, payload_chars: int) -> pathlib.Path:
    """``out/``, which `.gitignore` already excludes."""
    return pathlib.Path("out") / f"cost_latency_load_{spans}x{payload_chars}.jsonl"
