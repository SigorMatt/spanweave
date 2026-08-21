"""Capture a real trace from real instrumentation. **Human-run only.**

    make capture                      # picks the backend you have configured
    make capture ARGS="--backend openai"
    make capture ARGS="--fleet 8"     # the scratch fleet for TASKS.md 2.2

This is the step an autonomous agent must not take (``AGENT.md``). Everything
else in this repository can be verified by running it; this one produces
evidence about the *outside world*, and evidence you generated yourself is not
evidence. A hand-authored fixture proves the adapter matches **our
understanding** of a dialect. Only a captured one proves it matches **the
instrumentor** (``FIXTURES.md`` §6).

Two backends are supported and both are first-class: the Anthropic SDK, and
the OpenAI SDK pointed at any OpenAI-compatible endpoint. See
``capture/README.md`` for what to install and export.

What it does **not** do: put anything into ``fixtures/captured/``. That is a
human act, performed after reading the trace, redacting whatever needs
redacting, and writing the provenance file. The harness prints exactly what
remains.

``--fleet N`` is a different job with the same rule, only harder: it writes N
deliberately unalike traces to ``capture/_scratch/fleet/`` for the adversarial
consumer to aggregate (``capture/fleet.py``). Those are **scratch** — never
promoted, never given provenance — and the reason the rule is harder there is
that eight traces nobody reads carefully are a better hiding place than one
fixture under review. The fabrication halt point in ``AGENT.md`` covers both.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys
from collections.abc import Mapping

from capture import backends, fleet
from capture.backends import BACKENDS, Backend
from capture.exporter import JsonlSpanExporter

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRATCH = REPO / "capture/_scratch"
FLEET_SCRATCH = SCRATCH / "fleet"
TRACER_NAME = "spanweave.capture"


class CaptureError(Exception):
    """Something the human has to fix before a capture can run."""


def select(explicit: str | None, environ: Mapping[str, str]) -> Backend:
    """Choose a backend, or refuse to.

    Deliberately the same posture as the library's own adapter selection
    (`SPEC.md` §6.1): an unambiguous configuration is used, an ambiguous one
    is a hard error naming the escape hatch, and nothing is ever guessed. A
    capture that quietly ran against the backend you did not mean is a
    fixture whose provenance file is wrong, which is worse than no fixture.
    """
    if explicit is not None:
        if explicit not in BACKENDS:
            known = ", ".join(sorted(BACKENDS))
            raise CaptureError(f"unknown backend {explicit!r}; available: {known}")
        return BACKENDS[explicit]

    configured = [b for b in BACKENDS.values() if b.configured(dict(environ))]
    if len(configured) == 1:
        return configured[0]
    if not configured:
        wanted = "\n".join(
            f"    {b.id:<10} needs {b.api_key_env}"
            + (f" (and optionally {b.base_url_env})" if b.base_url_env else "")
            for b in BACKENDS.values()
        )
        raise CaptureError(
            "no backend is configured -- none of their credentials are set:\n"
            f"{wanted}\n"
            "Export one, or name a backend with --backend."
        )
    names = ", ".join(sorted(b.id for b in configured))
    raise CaptureError(
        f"more than one backend is configured ({names}), so the choice is "
        f"ambiguous. Name one with --backend; guessing would produce a "
        f"fixture whose provenance says the wrong thing."
    )


def _install_hint(backend: Backend) -> str:
    packages = " ".join(backend.packages)
    return (
        "This harness needs framework dependencies that the library itself must\n"
        "never have. Install them in your own environment:\n\n"
        f"    uv pip install {packages} opentelemetry-sdk\n\n"
        "Core has zero runtime dependencies and these are never added to it\n"
        "(ENVIRONMENT.md)."
    )


def _instrument(backend: Backend, exporter: JsonlSpanExporter):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    backend.instrument(provider)
    return provider, provider.get_tracer(TRACER_NAME)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="make capture",
        description="Capture a real instrumented trace. Human-run only.",
    )
    parser.add_argument(
        "--backend",
        choices=sorted(BACKENDS),
        help="which SDK to drive; default is whichever one you have configured",
    )
    parser.add_argument("--name", help="base name for the output file")
    parser.add_argument("--model", help="override the model this backend uses")
    parser.add_argument(
        "--fleet",
        type=int,
        metavar="N",
        help=(
            "capture N deliberately unalike runs into capture/_scratch/fleet/ "
            "for TASKS.md 2.2. Scratch, never fixtures."
        ),
    )
    args = parser.parse_args(argv)

    environ = os.environ
    try:
        backend = select(args.backend, environ)
    except CaptureError as failure:
        print(f"capture: {failure}", file=sys.stderr)
        return 2

    model = backend.model(dict(environ), args.model)
    name = args.name or f"{backend.id}_tool_call"

    if not environ.get(backend.api_key_env):
        print(
            f"capture: {backend.api_key_env} is not set. This step makes a real "
            f"model call, which is exactly why it is human-run.\n\n"
            f"{_install_hint(backend)}",
            file=sys.stderr,
        )
        return 2

    exporter = JsonlSpanExporter()
    try:
        provider, tracer = _instrument(backend, exporter)
    except ImportError as failure:
        print(
            f"capture: missing dependency: {failure}\n\n{_install_hint(backend)}",
            file=sys.stderr,
        )
        return 2

    if args.fleet is not None:
        try:
            return _fleet(args.fleet, backend, model, tracer, exporter)
        finally:
            provider.shutdown()

    try:
        called = backends.converse(backend, model, tracer)
    finally:
        provider.shutdown()

    if not called:
        print(
            "capture: the model answered without calling the tool, so the trace "
            "has no tool span and no call pairing. Re-run, or keep it and say so "
            "in the provenance file.",
            file=sys.stderr,
        )
    if not exporter.records:
        print(
            "capture: no spans were exported; instrumentation did not attach",
            file=sys.stderr,
        )
        return 2

    captured = write_trace(SCRATCH / f"{name}.local.jsonl", exporter.sorted_records())

    print(
        _next_steps(
            captured=captured,
            name=name,
            backend=backend,
            model=model,
            endpoint=environ.get(backend.base_url_env or "", ""),
            today=datetime.date.today().isoformat(),
            count=len(exporter.records),
        )
    )
    return 0


def write_trace(path, records):
    """One trace, one file, in the flat JSONL the corpus uses."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def _fleet(count, backend, model, tracer, exporter):
    """Capture N deliberately unalike runs. Scratch only -- see `fleet.py`.

    One file per run, because one trace is one graph (`SPEC.md` §7) and the
    consumer this exists for aggregates *across* graphs. The exporter is
    drained between runs so a trace cannot pick up the previous one's spans.

    Returns non-zero when a required shape is missing. That is deliberate: a
    partial fleet is a real problem to fix by re-running, and an exit code is
    harder to skim past than a paragraph. The files stay on disk either way.
    """
    if count < 1:
        print("capture: --fleet needs at least 1 run", file=sys.stderr)
        return 2

    runs = fleet.specs(count)
    traces = []
    for position, spec in enumerate(runs, start=1):
        exporter.drain()
        # parallel=True for fleet runs ONLY: it enables a capability the
        # fleet needs and changes `llm.invocation_parameters`, which would
        # unmatch 2.6's pair if it reached the reference capture.
        backends.converse(
            backend, model, tracer, spec.prompt, spec.tools, parallel=True
        )
        records = exporter.sorted_records()
        if not records:
            print(
                "capture: no spans were exported; instrumentation did not attach",
                file=sys.stderr,
            )
            return 2
        path = write_trace(
            FLEET_SCRATCH / f"{position:02d}_{spec.id}.local.jsonl", records
        )
        traces.append(records)
        print(
            f"  run {position:2d}/{count}  {spec.id:<20} {len(records):2d} spans"
            f"  -> {path.name}"
        )

    found = fleet.coverage(traces)
    absent = fleet.missing(found)
    print(f"\nWrote {len(traces)} traces -> {FLEET_SCRATCH}")
    print(fleet.report(found, absent))
    return 1 if absent else 0


def _next_steps(*, captured, name, backend, model, endpoint, today, count):
    where = f"\n     - endpoint: {endpoint}" if endpoint else ""
    caution = (
        "\n   If the endpoint URL embeds a credential, redact it. It is the one\n"
        "   thing here that can carry a secret without looking like one.\n"
        if endpoint
        else ""
    )
    return f"""
Captured {count} spans -> {captured}

This file is NOT a fixture yet, and nothing has been committed. Three things
remain, and all three are yours (FIXTURES.md §6):

1. READ IT. It contains whatever the model and the instrumentation actually
   produced, including the prompt and the response.

2. REDACT IT, if anything in it should not be public -- then record what you
   removed, and that you removed it. Redaction is a human act performed before
   commit, and an unrecorded redaction is indistinguishable from none.
{caution}
3. MOVE AND DOCUMENT IT:

     mv {captured} fixtures/captured/{name}.jsonl

   and write fixtures/captured/{name}.provenance.md recording:

     - instrumentor: {backend.packages[-1]} <exact version>
     - SDK: {backend.packages[0]} <exact version>; opentelemetry-sdk <version>
     - model: {model}{where}
     - captured: {today}
     - command: make capture --backend {backend.id}
     - redacted: <what, by whom> (or: nothing, and why that was safe)
     - this fixture may be used to claim: <what it actually demonstrates>

   On that last line, two things this capture does NOT demonstrate:

     * Only the `llm` spans come from the instrumentor. The `agent` and `tool`
       spans are emitted by capture/backends.py, because executing a tool is
       not an SDK call and no instrumentor would record it. That is what a
       real application's trace looks like too -- but "captured from real
       instrumentation" is then true of some spans and not others.
     * The instrumentor patches the SDK client, not the endpoint. This
       demonstrates {backend.packages[-1]}, whatever service answered.

Then check that it builds, and that what it says about itself is true:

     uv run spanweave inspect fixtures/captured/{name}.jsonl
     uv run spanweave build fixtures/captured/{name}.jsonl -o /dev/null

If the captured trace and a hand-authored one disagree, the captured one is
right and the adapter is wrong (FIXTURES.md §6).
"""


if __name__ == "__main__":
    sys.exit(main())
