"""Capture a real trace from real instrumentation. **Human-run only.**

    make capture                      # picks the backend you have configured
    make capture ARGS="--backend openai"
    make capture ARGS="--backend genai"   # the OTel GenAI half of the pair
    make capture ARGS="--fleet 8"     # the scratch fleet for TASKS.md 2.2

This is the step an autonomous agent must not take (``AGENT.md``). Everything
else in this repository can be verified by running it; this one produces
evidence about the *outside world*, and evidence you generated yourself is not
evidence. A hand-authored fixture proves the adapter matches **our
understanding** of a dialect. Only a captured one proves it matches **the
instrumentor** (``FIXTURES.md`` §6).

Three backends are supported and all are first-class: the Anthropic SDK, and
the OpenAI SDK pointed at any OpenAI-compatible endpoint, under either of two
instrumentors -- ``openai`` (OpenInference) and ``genai`` (OTel GenAI). See
``capture/README.md`` for what to install and export.

The last two share a credential on purpose: they are the **matched pair**
``TASKS.md`` 2.6 needs, identical but for the instrumentor. A consequence is
that a bare ``make capture`` with ``NEBIUS_API_KEY`` set is now genuinely
ambiguous and refuses, naming ``--backend``. That is the same posture as
everywhere else here: a capture that quietly ran as the backend you did not
mean is a fixture whose provenance file is wrong.

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
import importlib.metadata
import json
import os
import pathlib
import sys
import textwrap
from collections.abc import Mapping

from capture import backends, fleet
from capture.backends import BACKENDS, Backend, CaptureError
from capture.exporter import JsonlSpanExporter

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRATCH = REPO / "capture/_scratch"
FLEET_SCRATCH = SCRATCH / "fleet"
TRACER_NAME = "spanweave.capture"


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
    notices: tuple[str, ...] = ()
    try:
        # Whatever this backend has to switch on BEFORE instrumenting -- and
        # then verify actually switched on. `genai` turns message-content
        # capture on here; without it the run would be a credential spent on a
        # trace with no payloads and no tool-call ids (`TASKS.md` 2.5).
        if backend.enable is not None:
            notices = backend.enable(environ)
        provider, tracer = _instrument(backend, exporter)
    except ImportError as failure:
        print(
            f"capture: missing dependency: {failure}\n\n{_install_hint(backend)}",
            file=sys.stderr,
        )
        return 2
    except CaptureError as failure:
        print(f"capture: {failure}", file=sys.stderr)
        return 2

    for notice in notices:
        print(f"capture: {notice}")

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

    records = exporter.sorted_records()

    # A trace this backend says is not worth having is not written. The
    # alternative -- writing it with a warning -- leaves a file on disk that
    # looks exactly like a usable capture, and the warning scrolls away.
    blocking = backend.require(records) if backend.require is not None else ()
    for reason in blocking:
        print(f"capture: {reason}", file=sys.stderr)
    if blocking:
        print(
            "capture: nothing was written. Fix the above and re-run.",
            file=sys.stderr,
        )
        return 2

    captured = write_trace(SCRATCH / f"{name}.local.jsonl", records)

    checks = backend.checklist(records) if backend.checklist is not None else ()
    hosts = endpoints_in(records)
    if checks:
        print(_checklist(checks))

    print(
        _next_steps(
            captured=captured,
            name=name,
            backend=backend,
            model=model,
            endpoint=environ.get(backend.base_url_env or "", ""),
            today=datetime.date.today().isoformat(),
            count=len(exporter.records),
            hosts=hosts,
        )
    )
    # Non-zero when a verification failed, and the file stays: the same
    # posture as the fleet's coverage report. An exit code is harder to skim
    # past than a paragraph, and the trace is the evidence for WHY it failed.
    return 0 if all(check.ok for check in checks) else 1


#: Attributes that record WHERE the call went, rather than what it said.
#: OTel's HTTP/network conventions; an OpenInference instrumentor does not
#: emit them, and a GenAI one does -- which makes them a real difference in
#: what the two halves of the matched pair need reading for before commit.
ENDPOINT_KEYS = ("server.address", "server.port", "url.full", "http.url")


def endpoints_in(records):
    """Every `key=value` in the trace that names the service that answered.

    Reported rather than removed. Redaction is a human act (`FIXTURES.md` §6),
    and the harness's job is to make sure the human is told where to look --
    the Phase 1 capture's provenance could say "the endpoint does not appear
    in the file at all" because with that instrumentor it genuinely did not,
    and repeating the sentence for a trace where it does would be a false
    claim in a file whose whole purpose is being true.
    """
    found = {}
    for record in records:
        for key in ENDPOINT_KEYS:
            if key in record["attributes"]:
                found[key] = record["attributes"][key]
    return tuple(sorted(found.items()))


def _checklist(checks):
    """The pre-promotion verifications, answered against the exported records.

    Printed BEFORE the next-steps block, because a human who reads only the
    first screen should see a failure rather than instructions for committing.
    """
    lines = [
        "",
        "Verification (TASKS.md 2.6) -- the harness's reading of what it just",
        "wrote. Confirm each against the file; a harness that both produces a",
        "trace and certifies it is not evidence.",
        "",
    ]
    for check in checks:
        lines.append(f"  [{'OK' if check.ok else '--'}] {check.question}")
        lines.append(f"       {check.detail}")
    if not all(check.ok for check in checks):
        lines += [
            "",
            "At least one verification FAILED, and this run exits non-zero.",
            "The trace was still written -- it is the evidence for why.",
            "",
            "If it is the SPEC.md 4.2.1 declaration that is missing, do NOT",
            "work around it. `llm_tool_llm` is never-cut and its canonical",
            "graph contains that edge, so a dialect that cannot declare it is",
            "a finding about the corpus's equivalence rule (TASKS.md 2.9),",
            "not a rendering to fudge.",
        ]
    return "\n".join(lines)


def installed(package):
    """The exact installed version, or a placeholder the human must fill in.

    Printed straight into the provenance template. `TASKS.md` 2.5 requires the
    fixture to name the exact package and version, and these conventions are
    moving fast enough that a transcription step is a place for the record to
    go stale or wrong. Reading it from the environment that just produced the
    trace removes that step.
    """
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "<exact version -- NOT INSTALLED, fill this in>"


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
    stale = clear_fleet_dir()
    if stale:
        print(f"  cleared {stale} trace(s) from a previous fleet")
    traces = []
    skipped = []
    for position, spec in enumerate(runs, start=1):
        run_model = spec.model or model
        endpoint = os.environ.get(spec.endpoint_env) if spec.endpoint_env else None
        if spec.endpoint_env and not endpoint:
            # Refuse rather than send this model to the default endpoint. A
            # trace whose provenance is wrong is worse than one you do not
            # have -- the same posture as backend selection (SPEC.md §6.1).
            skipped.append((spec.id, spec.endpoint_env))
            print(
                f"  run {position:2d}/{count}  {spec.id:<24} SKIPPED "
                f"-- {spec.endpoint_env} is not set"
            )
            continue

        exporter.drain()
        # parallel=True for fleet runs ONLY: it enables a capability the
        # fleet needs and changes `llm.invocation_parameters`, which would
        # unmatch 2.6's pair if it reached the reference capture.
        backends.converse(
            backend,
            run_model,
            tracer,
            spec.prompt,
            spec.tools,
            parallel=True,
            note={"model": run_model, "spec": spec.id},
            base_url=endpoint,
        )
        records = exporter.sorted_records()
        if not records:
            print(
                "capture: no spans were exported; instrumentation did not attach",
                file=sys.stderr,
            )
            return 2
        name = f"{position:02d}_{spec.id}__{_slug(run_model)}.local.jsonl"
        write_trace(FLEET_SCRATCH / name, records)
        traces.append(records)
        print(
            f"  run {position:2d}/{count}  {spec.id:<24} {len(records):2d} spans"
            f"  {run_model}"
        )

    if not traces:
        print("capture: every run was skipped; nothing was captured", file=sys.stderr)
        return 2

    found = fleet.coverage(traces)
    absent = fleet.missing(found)
    print(f"\nWrote {len(traces)} traces -> {FLEET_SCRATCH}")
    print(fleet.report(found, absent))
    for spec_id, variable in skipped:
        print(f"SKIPPED: {spec_id} -- export {variable} to include it.")
    for spec_id in fleet.unreached(count):
        print(f"NOT REACHED at --fleet {count}: {spec_id}")
    if fleet.unreached(count):
        # Said out loud because the multi-model specs sit at the end, so a
        # habitual `--fleet 8` skips all of them and a silent cap would read
        # as "we covered everything".
        print(f"Run --fleet {len(fleet.FLEET)} to reach every spec.")
    return 1 if absent else 0


def clear_fleet_dir():
    """Remove the previous fleet's traces before writing this one.

    **A defect this fixed rather than a precaution.** The runner appended, so
    `--fleet 14` after `--fleet 12` left 26 files: 12 stale ones under the old
    naming beside 14 new. An aggregator pointed at the directory would have
    double-counted nine traces and treated a stale run as distinct from its
    own re-run -- and the duplicates are *not* identical (`unmapped_attributes`
    went 2 to 3 once the model/spec stamp was added), so they would have looked
    like real variation rather than like duplicates. That corrupts the evidence
    silently, which is the worst way for evidence to be wrong.

    The directory therefore holds exactly one fleet. Only files this harness
    writes are removed, and the count is reported -- a deletion nobody is told
    about is its own small version of the same problem.
    """
    if not FLEET_SCRATCH.is_dir():
        return 0
    removed = 0
    for path in sorted(FLEET_SCRATCH.glob("*.local.jsonl")):
        path.unlink()
        removed += 1
    return removed


def _slug(model: str) -> str:
    """A model id as a filename fragment, so a trace is attributable at a glance."""
    return "".join(c if c.isalnum() or c in "-." else "-" for c in model).strip("-")


def _next_steps(*, captured, name, backend, model, endpoint, today, count, hosts=()):
    where = f"\n     - endpoint: {endpoint}" if endpoint else ""
    caution = (
        "\n   If the endpoint URL embeds a credential, redact it. It is the one\n"
        "   thing here that can carry a secret without looking like one.\n"
        if endpoint
        else ""
    )
    if hosts:
        named = "".join(f"\n     {key} = {value}" for key, value in hosts)
        caution += (
            "\n   This trace NAMES THE SERVICE THAT ANSWERED, which not every"
            "\n   instrumentor does:"
            f"{named}"
            "\n   Decide whether that is public, and say what you decided. Do not"
            "\n   copy another fixture's sentence about the endpoint not appearing"
            "\n   in the file -- here it does.\n"
        )
    instrumentor = backend.packages[-1]
    sdk = backend.packages[0]
    dialect_note = textwrap.fill(
        backend.dialect.provenance_note,
        width=72,
        initial_indent="",
        subsequent_indent="       ",
    )
    versions = "\n".join(
        f"     - {label}: {package} {installed(package)}"
        for label, package in (
            ("instrumentor", instrumentor),
            ("SDK", sdk),
            ("OTel SDK", "opentelemetry-sdk"),
        )
    )
    # 2.6's matched-pair statement. It has to appear in BOTH provenance files,
    # because the property it records -- same model, same prompt, same tools,
    # different instrumentor -- is what makes the cross-dialect comparison mean
    # anything, and it is invisible from either file on its own.
    pair = (
        f"""
   AND, because this backend is half of a matched pair, the sentence that
   makes the pair legible from either side:

     - matched pair: same model ({model}), same prompt, same tool
       inventory as the other half of the pair -- differing ONLY in the
       instrumentor. Add the same statement to the other half's provenance
       file, naming this one. Neither file can be read as evidence about
       the dialect without it.
"""
        if backend.dialect.id != "openinference" or backend.id == "openai"
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

{versions}
     - dialect emitted: {backend.dialect.id}
     - model: {model}{where}
     - captured: {today}
     - command: make capture --backend {backend.id}
     - redacted: <what, by whom> (or: nothing, and why that was safe)
     - this fixture may be used to claim: <what it actually demonstrates>

   The versions above are read from the environment that just produced this
   trace, not typed from memory. Copy them verbatim.
{pair}
   On that last line, two things this capture does NOT demonstrate:

     * Only the `llm` spans come from the instrumentor. The `agent` and `tool`
       spans are emitted by capture/backends.py, because executing a tool is
       not an SDK call and no instrumentor would record it. That is what a
       real application's trace looks like too -- but "captured from real
       instrumentation" is then true of some spans and not others.

       {dialect_note}
     * The instrumentor patches the SDK client, not the endpoint. This
       demonstrates {instrumentor}, whatever service answered.

Then check that it builds, and that what it says about itself is true:

     uv run spanweave inspect fixtures/captured/{name}.jsonl
     uv run spanweave build fixtures/captured/{name}.jsonl -o /dev/null

If the captured trace and a hand-authored one disagree, the captured one is
right and the adapter is wrong (FIXTURES.md §6).
"""


if __name__ == "__main__":
    sys.exit(main())
