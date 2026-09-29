"""The adapter registry and dialect selection.

Selection is the one place this library can fail in the way it least wants
to: quietly. A mis-detected input produces a **plausible but wrong graph**,
and nothing downstream can tell. So ambiguity is a hard error here, never a
first-wins race and never a fallback to a default (`SPEC.md` §6.1).

That hard error is also what makes the weaker half of the mechanism
survivable. Adapters self-report their confidence and could inflate it
(`OPEN_QUESTIONS.md` §3); failing loudly on a tie means an inflated claim
collides visibly instead of winning silently.

**A dialect is a property of a record, not of a file.** One process can run a
framework instrumentor and an SDK instrumentor at once; they share a tracer
provider and their spans share an export. So classification asks each adapter
about each record -- `classify()`, and `partition()` over a whole input -- and
the refusal narrows with it: two adapters claiming *one record* is
unresolvable, two adapters claiming *different* records is not ambiguity at
all. No marker table lives here; each adapter answers for itself through the
declaration the protocol already has, so this module stays as dialect-blind as
the layer below it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from spanweave.adapters.base import Adapter
from spanweave.errors import (
    ADAPTER_DETECT_FAILED,
    ADAPTER_UNCONFIDENT,
    DUPLICATE_ADAPTER_ID,
    NO_ADAPTERS_REGISTERED,
    AdapterSelectionError,
    UnknownAdapterError,
)
from spanweave.model import JsonValue

__all__ = [
    "DETECTION_SAMPLE_SIZE",
    "MINIMUM_CONFIDENCE",
    "AdapterRegistry",
    "Claim",
    "Partition",
    "classify",
    "detect",
    "get",
    "partition",
    "register",
    "registered",
]

#: What an adapter is asked to *declare* over: a bounded sample, so the number
#: recorded in `meta` is measured over at most this many records, whether the
#: trace holds 10 or 10 million. Classification is a separate question and is
#: asked of every record
#: (`SPEC.md` §6.1).
DETECTION_SAMPLE_SIZE = 50

#: Below this, nobody is confident enough and the caller is told so.
MINIMUM_CONFIDENCE = 0.5


@dataclass(frozen=True, slots=True)
class Claim:
    """One adapter, and the records of one input that it claimed."""

    adapter_id: str
    #: The adapter's own confidence, declared over the first
    #: `DETECTION_SAMPLE_SIZE` records it claimed. A declaration, not a
    #: measurement, and `meta` records it under that name (`SPEC.md` §3.9).
    declared_confidence: float
    #: In input order: `parse()` numbers what it is given, and that number is
    #: `RawRecord.line_number` (`SPEC.md` §3.5).
    records: tuple[JsonValue, ...]


@dataclass(frozen=True, slots=True)
class Partition:
    """Every record of one input, sorted into the adapter that claimed it.

    `unclaimed` is not a leftover to be tidied away: no registered adapter
    recognized those records, which is a reportable outcome and never a
    discard (`CLAUDE.md` 2).
    """

    #: Ordered by adapter id, never by registration order or by first arrival.
    claims: tuple[Claim, ...]
    unclaimed: tuple[JsonValue, ...]

    @property
    def contributors(self) -> tuple[str, ...]:
        """The adapters that claimed at least one record, by id."""
        return tuple(claim.adapter_id for claim in self.claims)


@dataclass(slots=True)
class AdapterRegistry:
    """The registered adapters. Registration order never affects selection."""

    _adapters: dict[str, Adapter] = field(default_factory=dict)

    def register(self, adapter: Adapter) -> None:
        existing = self._adapters.get(adapter.id)
        if existing is not None and existing is not adapter:
            raise AdapterSelectionError(
                f"two different adapters both claim the id {adapter.id!r}; "
                f"ids must be unique",
                code=DUPLICATE_ADAPTER_ID,
            )
        self._adapters[adapter.id] = adapter

    def registered(self) -> tuple[Adapter, ...]:
        """Every adapter, ordered by id -- never by registration order."""
        return tuple(self._adapters[key] for key in sorted(self._adapters))

    def get(self, adapter_id: str) -> Adapter:
        try:
            return self._adapters[adapter_id]
        except KeyError:
            known = ", ".join(sorted(self._adapters)) or "none registered"
            raise UnknownAdapterError(
                f"no adapter with id {adapter_id!r}; registered: {known}"
            ) from None

    def confidences(self, sample: Sequence[JsonValue]) -> tuple[tuple[str, float], ...]:
        """Every adapter's confidence in this input, ordered by adapter id."""
        return tuple(
            (adapter.id, _declared(adapter, sample)) for adapter in self.registered()
        )

    def classify(self, record: JsonValue) -> tuple[str, ...]:
        """Which adapters claim this **one** record, ordered by adapter id.

        The question the protocol already answers: an adapter claims a record
        when `detect([record])` reaches `MINIMUM_CONFIDENCE`. Nothing new is
        asked of an adapter and no marker table lives here -- which is what
        keeps dialect knowledge inside the adapter that owns it even though
        dispatch happens above the seam (`DESIGN.md` §3).

        One record, no neighbours: a classification cannot depend on where the
        record sat, on how many records around it matched, or on the order the
        adapters were registered in (`SPEC.md` §5).
        """
        return tuple(
            name
            for name, confidence in self.confidences([record])
            if confidence >= MINIMUM_CONFIDENCE
        )

    def partition(self, records: Sequence[JsonValue]) -> Partition:
        """Sort a whole input into the adapters that claim it (`SPEC.md` §6.1).

        Refuses where a guess would be required and nowhere else. Two adapters
        claiming one record is unresolvable: they disagree about that span's
        kind, its payloads and its call ids, publishing both parses would
        invent a second span for one operation, and picking one is the
        plausible-but-wrong graph this module exists to prevent. Two adapters
        claiming *different* records is not ambiguity -- each record has
        exactly one answer.
        """
        if not self._adapters:
            raise AdapterSelectionError(
                "no adapters are registered, so nothing can read this input",
                code=NO_ADAPTERS_REGISTERED,
            )
        claimed: dict[str, list[JsonValue]] = {}
        unclaimed: list[JsonValue] = []
        for position, record in enumerate(records, start=1):
            claimants = self.classify(record)
            if len(claimants) > 1:
                raise AdapterSelectionError(_ambiguous(position, record, claimants))
            if not claimants:
                # Never a discard, and never handed to a designated adapter:
                # that would put a dialect's name on a node on the strength of
                # that dialect having said nothing about the record.
                unclaimed.append(record)
                continue
            claimed.setdefault(claimants[0], []).append(record)
        return Partition(
            claims=tuple(
                Claim(
                    adapter_id=name,
                    declared_confidence=_declared(
                        self.get(name), claimed[name][:DETECTION_SAMPLE_SIZE]
                    ),
                    records=tuple(claimed[name]),
                )
                for name in sorted(claimed)
            ),
            unclaimed=tuple(unclaimed),
        )

    def detect(self, records: Sequence[JsonValue]) -> tuple[Adapter, float]:
        """Choose the adapter for this input, or refuse to (`SPEC.md` §6.1)."""
        if not self._adapters:
            raise AdapterSelectionError(
                "no adapters are registered, so nothing can read this input",
                code=NO_ADAPTERS_REGISTERED,
            )
        sample = list(records[:DETECTION_SAMPLE_SIZE])
        measured = self.confidences(sample)
        best = max(confidence for _, confidence in measured)
        winners = [name for name, confidence in measured if confidence == best]

        if best < MINIMUM_CONFIDENCE:
            raise AdapterSelectionError(
                f"no adapter is confident enough about this input "
                f"(highest {best:.2f}, minimum {MINIMUM_CONFIDENCE:.2f}). "
                f"{_report(measured)} "
                f"Name one explicitly with --adapter if you know the dialect.",
                code=ADAPTER_UNCONFIDENT,
            )
        if len(winners) > 1:
            tied = ", ".join(winners)
            raise AdapterSelectionError(
                f"this input is ambiguous: {tied} are equally confident "
                f"({best:.2f}). {_report(measured)} "
                f"Name one explicitly with --adapter; guessing between them "
                f"would produce a plausible graph from possibly the wrong "
                f"dialect."
            )
        return self.get(winners[0]), best


def _declared(adapter: Adapter, sample: Sequence[JsonValue]) -> float:
    try:
        return float(adapter.detect(sample))
    except Exception as failure:
        # `detect()` must not raise (ADAPTERS.md §2). One that does is a
        # broken adapter, not malformed input, and swallowing it would let a
        # different adapter win by default -- which is exactly the
        # silent-wrong-graph outcome this module exists to prevent. So it is
        # reported, loudly, naming the adapter.
        raise AdapterSelectionError(
            f"adapter {adapter.id!r} raised during detection "
            f"({failure!r}); detect() must be pure and must not raise",
            code=ADAPTER_DETECT_FAILED,
        ) from failure


def _report(measured: Sequence[tuple[str, float]]) -> str:
    listed = ", ".join(f"{name} {confidence:.2f}" for name, confidence in measured)
    return f"Confidence declared by each adapter: {listed}."


def _ambiguous(position: int, record: JsonValue, claimants: Sequence[str]) -> str:
    """The refusal, located precisely enough to go and look at the record."""
    where = f"record {position}"
    span_id = _span_id_of(record)
    if span_id is not None:
        where += f" (span id {span_id!r})"
    return (
        f"{where} is claimed by more than one adapter: "
        f"{', '.join(claimants)}. Name one explicitly with --adapter; "
        f"guessing between them would produce a plausible graph from possibly "
        f"the wrong dialect, and parsing it twice would publish two nodes for "
        f"one operation."
    )


def _span_id_of(record: JsonValue) -> str | None:
    """The record's own span id, for the refusal message and nothing else.

    `span_id` is a field of the span envelope every supported dialect rides
    on rather than a field of any one dialect, and it is read here only so
    that a refusal can be matched to a record by a human holding the file.
    Nothing is interpreted from it and it never reaches a graph.
    """
    if isinstance(record, dict):
        value = record.get("span_id")
        if isinstance(value, str):
            return value
    return None


#: The registry the CLI and the public API use.
REGISTRY = AdapterRegistry()


def register(adapter: Adapter) -> None:
    REGISTRY.register(adapter)


def registered() -> tuple[Adapter, ...]:
    return REGISTRY.registered()


def get(adapter_id: str) -> Adapter:
    return REGISTRY.get(adapter_id)


def detect(records: Sequence[JsonValue]) -> tuple[Adapter, float]:
    return REGISTRY.detect(records)


def classify(record: JsonValue) -> tuple[str, ...]:
    return REGISTRY.classify(record)


def partition(records: Sequence[JsonValue]) -> Partition:
    return REGISTRY.partition(records)


# Registered here, at the end of the module, so that importing the registry
# also makes the shipped dialects available -- and so that an adapter file
# never has to import the registry back (ADAPTERS.md §4).
from spanweave.adapters.openinference import OpenInferenceAdapter  # noqa: E402
from spanweave.adapters.otel_genai import OtelGenAiAdapter  # noqa: E402

REGISTRY.register(OpenInferenceAdapter())
REGISTRY.register(OtelGenAiAdapter())
