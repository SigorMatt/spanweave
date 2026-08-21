"""The scratch fleet: many real traces, deliberately unalike (``TASKS.md`` 2.2).

The adversarial consumer of Phase 2b attacks ``PREDICTIONS.md`` P5 — *one
trace = one graph*. Run over the committed corpus it tests **the aggregator**;
run over a real heterogeneous fleet it tests **the claim**. So this module
exists to produce the second kind of input.

**These traces are scratch, and the distinction is absolute.** They land in
``capture/_scratch/fleet/``, which is gitignored. They get no provenance file,
they are never promoted to ``fixtures/captured/``, and they are never cited as
evidence for anything beyond 2b's own findings. ``fixtures/captured/`` holds
human-reviewed, redacted, provenance-bearing artifacts; a fleet of unreviewed
traces in there would destroy the only property that directory has
(``FIXTURES.md`` §6).

**What varies, and what does not.** The backend and the instrumentor are
fixed. What varies is the *shape of the run* — which tools exist, whether the
model calls one, several, or none, and whether a tool fails — and, for some
runs, **the model**. A fleet of identical traces is one trace counted N times.

**Why the model varies too.** A fleet drawn from one model is a batch, not a
fleet: real fleets span models, so a multi-model fleet is closer to what a
fleet aggregator actually meets, which is what P5 needs. Swapping the model is
changing the setup, not selecting an answer — it is not the thing the steering
rule below prohibits, which is rewording prompts inside a fixed setup until one
model does what you want. The bound is stated instead: **at most two models
beyond the configured default**, pinned by a test, because past that it *is*
selection.

**The reference capture is not part of this.** ``TASKS.md`` 2.6 pins the
matched pair to ``openai/gpt-oss-120b``; that pin belongs to the pair, never to
the fleet. Nothing here touches it.

**Every trace records which model produced it**, as OpenInference ``metadata``
on its ``agent.run`` span and in its filename. A fleet that mixes models
without saying which is worse than a single-model fleet, because every finding
it produces is unattributable.

**Enabling a capability is not steering.** The fleet sends
``parallel_tool_calls=True`` on the OpenAI backend (`backends.py`). That is
allowed, and it is not the thing this module prohibits: it asks the API to
*permit* several calls in one turn, and leaves entirely open whether the model
makes any. The distinction is worth holding precisely, because the first fleet
produced no parallel call while its spans recorded
``llm.invocation_parameters`` as ``{"model": ...}`` alone — so "the model will
not do it" was a conclusion about a question nobody had put. It is scoped to
fleet runs: the parameter changes what the instrumentor records, and the
reference conversation must not move (``TASKS.md`` 2.5, 2.6).

**Steering is not guaranteeing, and that gap is handled honestly.** A prompt
steers a model; it does not command it. So this module never asserts that a
run produced the shape it was aimed at. It reads back what the exported
records *actually contain* (:func:`shapes_of`) and reports which required
shapes are missing, so the human can re-run. What it must never do — and the
reason the reading is done from records rather than from intent — is
manufacture a missing shape by editing an exported span afterwards. That would
make the fleet synthetic again while still looking real, which is the failure
the whole capture harness exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass

# The shapes a fleet has to contain. The four REQUIRED ones are named in
# `TASKS.md` 2.2; a fleet missing any of them is not exercising P5.
TOOL_CALL = "tool_call"
PARALLEL_TOOL_CALLS = "parallel_tool_calls"
NO_TOOL_CALL = "no_tool_call"
TOOL_ERROR = "tool_error"
VARIED_TOOLS = "varied_tools"

REQUIRED = (VARIED_TOOLS, NO_TOOL_CALL, PARALLEL_TOOL_CALLS, TOOL_ERROR)

WHY = {
    VARIED_TOOLS: "more than one tool, so per-tool rollup has something to roll up",
    NO_TOOL_CALL: "turns the model answered directly, with no tool span at all",
    PARALLEL_TOOL_CALLS: "several calls requested at once, by a model not a fixture",
    TOOL_ERROR: "a tool that failed, so Status and the error side are populated",
    TOOL_CALL: "the ordinary call/result pairing (reported, not required)",
}


#: The models a run may name. `None` means "whatever the backend resolved",
#: which is the configured default. The two overrides both advertise strong
#: agentic tool use, which is the property under test.
QWEN = "Qwen/Qwen3-235B-A22B-Instruct-2507"
KIMI = "moonshotai/Kimi-K3"

#: Kimi is served from a different regional endpoint, so the runs that name it
#: also name the environment variable holding that endpoint. If it is unset the
#: run is **skipped and said so**, never quietly sent to the wrong endpoint --
#: the same refusal posture as backend selection (`SPEC.md` §6.1), for the same
#: reason: a trace whose provenance is wrong is worse than a trace you do not
#: have.
KIMI_ENDPOINT = "NEBIUS_BASE_URL_EU_WEST2"

#: At most this many models beyond the configured default. The bound is the
#: line between changing the setup and selecting an answer, and it is pinned by
#: a test rather than left to judgement in the moment.
MAX_EXTRA_MODELS = 2


@dataclass(frozen=True)
class RunSpec:
    """One run of the fleet: a prompt, an inventory, and what it aims at.

    ``intends`` is the shape this run is *steered* toward. It is documentation
    and a tripwire (:func:`intended_shapes`), never evidence — what a run
    actually produced is read back from its records.

    ``model`` is ``None`` for the configured default. ``endpoint_env`` names
    the variable holding this model's endpoint, when it is not the default one.
    """

    id: str
    prompt: str
    tools: tuple[str, ...]
    intends: tuple[str, ...]
    model: str | None = None
    endpoint_env: str | None = None


FLEET: tuple[RunSpec, ...] = (
    RunSpec(
        id="weather",
        prompt="What is the weather in Paris? Use the tool.",
        tools=("get_weather",),
        intends=(TOOL_CALL,),
    ),
    RunSpec(
        id="two_cities",
        prompt=(
            "Compare the weather in Paris and in Oslo. Call the tool for each city."
        ),
        tools=("get_weather",),
        intends=(TOOL_CALL, PARALLEL_TOOL_CALLS),
    ),
    RunSpec(
        id="weather_and_people",
        prompt=(
            "How is the weather in Oslo, and how many people live there? Use the tools."
        ),
        tools=("get_weather", "get_population"),
        intends=(TOOL_CALL, PARALLEL_TOOL_CALLS, VARIED_TOOLS),
    ),
    RunSpec(
        id="no_tool",
        prompt="In one sentence, and without using any tool: what is a barometer?",
        tools=("get_weather",),
        intends=(NO_TOOL_CALL,),
    ),
    RunSpec(
        id="failing_flight",
        prompt="Look up flight BA117 with the tool and tell me its status.",
        tools=("lookup_flight",),
        intends=(TOOL_CALL, TOOL_ERROR, VARIED_TOOLS),
    ),
    RunSpec(
        id="currency",
        prompt="Convert 100 EUR into NOK using the tool.",
        tools=("convert_currency",),
        intends=(TOOL_CALL, VARIED_TOOLS),
    ),
    RunSpec(
        id="out_of_scope",
        prompt=(
            "Using only the tools you have, who won the 2031 World Cup? "
            "If your tools cannot answer that, say so plainly."
        ),
        tools=("get_weather",),
        intends=(NO_TOOL_CALL,),
    ),
    RunSpec(
        id="three_at_once",
        prompt=(
            "For Paris: the weather, the population, and what 50 USD is in EUR. "
            "Use the tools."
        ),
        tools=("get_weather", "get_population", "convert_currency"),
        intends=(TOOL_CALL, PARALLEL_TOOL_CALLS, VARIED_TOOLS),
    ),
    # The parallel-aimed specs again, against two other models. Same prompts,
    # same tools, same instrumentor -- only the model differs, so a difference
    # in outcome is attributable to the model and to nothing else. `gpt-oss-120b`
    # answered these sequentially across turns 32 times (`TASKS.md` 2.2); these
    # runs are what turn "that model does not" into either "these models do" or
    # the considerably more interesting "none of them do".
    RunSpec(
        id="two_cities_qwen",
        prompt="Compare the weather in Paris and in Oslo. Call the tool for each city.",
        tools=("get_weather",),
        intends=(TOOL_CALL, PARALLEL_TOOL_CALLS),
        model=QWEN,
    ),
    RunSpec(
        id="weather_and_people_qwen",
        prompt=(
            "How is the weather in Oslo, and how many people live there? Use the tools."
        ),
        tools=("get_weather", "get_population"),
        intends=(TOOL_CALL, PARALLEL_TOOL_CALLS, VARIED_TOOLS),
        model=QWEN,
    ),
    RunSpec(
        id="three_at_once_qwen",
        prompt=(
            "For Paris: the weather, the population, and what 50 USD is in EUR. "
            "Use the tools."
        ),
        tools=("get_weather", "get_population", "convert_currency"),
        intends=(TOOL_CALL, PARALLEL_TOOL_CALLS, VARIED_TOOLS),
        model=QWEN,
    ),
    RunSpec(
        id="two_cities_kimi",
        prompt="Compare the weather in Paris and in Oslo. Call the tool for each city.",
        tools=("get_weather",),
        intends=(TOOL_CALL, PARALLEL_TOOL_CALLS),
        model=KIMI,
        endpoint_env=KIMI_ENDPOINT,
    ),
    RunSpec(
        id="weather_and_people_kimi",
        prompt=(
            "How is the weather in Oslo, and how many people live there? Use the tools."
        ),
        tools=("get_weather", "get_population"),
        intends=(TOOL_CALL, PARALLEL_TOOL_CALLS, VARIED_TOOLS),
        model=KIMI,
        endpoint_env=KIMI_ENDPOINT,
    ),
    RunSpec(
        id="three_at_once_kimi",
        prompt=(
            "For Paris: the weather, the population, and what 50 USD is in EUR. "
            "Use the tools."
        ),
        tools=("get_weather", "get_population", "convert_currency"),
        intends=(TOOL_CALL, PARALLEL_TOOL_CALLS, VARIED_TOOLS),
        model=KIMI,
        endpoint_env=KIMI_ENDPOINT,
    ),
)


def extra_models(runs: tuple[RunSpec, ...] = FLEET) -> frozenset[str]:
    """The models named explicitly, i.e. beyond the configured default."""
    return frozenset(run.model for run in runs if run.model)


def unreached(count: int) -> tuple[str, ...]:
    """Specs a fleet of ``count`` runs never gets to.

    A silent cap reads as "we covered everything" when it did not, and the
    multi-model specs sit at the end of the list -- so a habitual
    ``--fleet 8`` would skip every one of them and nothing would say so.
    """
    return tuple(spec.id for spec in FLEET[count:]) if count < len(FLEET) else ()


def specs(count: int) -> tuple[RunSpec, ...]:
    """The first ``count`` runs, cycling the fleet if more are asked for."""
    if count < 1:
        raise ValueError("a fleet needs at least one run")
    return tuple(FLEET[index % len(FLEET)] for index in range(count))


def intended_shapes(runs: tuple[RunSpec, ...]) -> frozenset[str]:
    """What the given runs are aimed at, as opposed to what they achieved."""
    return frozenset(shape for run in runs for shape in run.intends)


# --------------------------------------------------------------------------
# Reading back what a run actually produced
# --------------------------------------------------------------------------
#
# From the exported records, never from the harness's intent. This file is
# allowed to know the dialect -- like `backends.py`, it is on the emitting
# side of the seam, and nothing under `spanweave/` imports it.

SPAN_KIND = "openinference.span.kind"
TOOL_NAME = "tool.name"


def _tool_spans(records) -> list[dict]:
    return [
        record
        for record in records
        if (record.get("attributes") or {}).get(SPAN_KIND) == "TOOL"
    ]


def tools_in(records) -> frozenset[str]:
    """Which tools actually ran in one trace."""
    return frozenset(
        str(span["attributes"][TOOL_NAME])
        for span in _tool_spans(records)
        if TOOL_NAME in span.get("attributes", {})
    )


def shapes_of(records) -> frozenset[str]:
    """The shapes one trace contains, read off its records.

    Two of these are sound only because of how ``backends.converse`` is built,
    so the reasoning is written down rather than assumed:

    * **Parallel calls** — every tool span in a run is a child of that run's
      one ``agent.run`` span, and the harness executes tools for exactly one
      assistant turn. So two tool spans in a trace means the model requested
      two calls at once, which is the shape ``parallel_tool_calls`` is about.
    * **No tool call** — the harness emits a tool span for every call the
      model requested, so no tool span means no call was requested. It does
      not mean a call was requested and lost.

    ``VARIED_TOOLS`` is deliberately absent here: it is a property of a fleet,
    not of a trace, and :func:`coverage` computes it across runs.
    """
    tool_spans = _tool_spans(records)
    shapes = set()
    if tool_spans:
        shapes.add(TOOL_CALL)
    else:
        shapes.add(NO_TOOL_CALL)
    if len(tool_spans) > 1:
        shapes.add(PARALLEL_TOOL_CALLS)
    if any(span.get("status") == "ERROR" for span in tool_spans):
        shapes.add(TOOL_ERROR)
    return frozenset(shapes)


def coverage(traces) -> dict[str, tuple[int, ...]]:
    """Shape -> the 1-based runs that produced it, over a whole fleet."""
    fleet = list(traces)
    found: dict[str, list[int]] = {}
    used: set[str] = set()
    for position, records in enumerate(fleet, start=1):
        used |= tools_in(records)
        for shape in shapes_of(records):
            found.setdefault(shape, []).append(position)
    if len(used) > 1:
        # A fleet-level property: one trace can never show it, so it is
        # credited to the runs that contributed a tool.
        found[VARIED_TOOLS] = [
            position
            for position, records in enumerate(fleet, start=1)
            if tools_in(records)
        ]
    return {shape: tuple(runs) for shape, runs in found.items()}


def missing(found: dict[str, tuple[int, ...]]) -> tuple[str, ...]:
    """Which required shapes the fleet does not contain. Empty is the goal."""
    return tuple(shape for shape in REQUIRED if not found.get(shape))


def report(found: dict[str, tuple[int, ...]], absent: tuple[str, ...]) -> str:
    """What the human needs in order to confirm the fleet is usable."""
    lines = ["", "Fleet coverage -- what these traces actually contain:", ""]
    for shape in (*REQUIRED, TOOL_CALL):
        runs = found.get(shape, ())
        mark = "yes" if runs else "NO "
        where = f"runs {', '.join(str(run) for run in runs)}" if runs else "-"
        lines.append(f"  [{mark}] {shape:<21} {where}")
        lines.append(f"        {WHY[shape]}")
    if absent:
        lines += [
            "",
            "MISSING: " + ", ".join(absent),
            "",
            "A fleet without these is not exercising P5 -- it is a fleet of the",
            "runs where everything went the same way. A model is steered by a",
            "prompt, not commanded by one, so this happens.",
            "",
            "Re-run the fleet, or raise --fleet, or reword the run that was aimed",
            "at the missing shape. What you must NOT do is edit an exported span",
            "to add the shape: that makes the fleet synthetic while it still",
            "looks real, which is the one thing this harness exists to prevent.",
        ]
    else:
        lines += ["", "Every required shape is present. The fleet is usable for 2.3."]
    lines += [
        "",
        "These are SCRATCH. Gitignored, no provenance, never promoted to",
        "fixtures/captured/, never cited as evidence beyond 2b's findings.",
        "",
    ]
    return "\n".join(lines)
