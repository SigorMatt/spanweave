"""The adapter registry and dialect selection.

Selection is the one place this library can fail in the way it least wants
to: quietly. A mis-detected input produces a **plausible but wrong graph**,
and nothing downstream can tell. So ambiguity is a hard error here, never a
first-wins race and never a fallback to a default (`SPEC.md` §6.1).

That hard error is also what makes the weaker half of the mechanism
survivable. Adapters self-report their confidence and could inflate it
(`OPEN_QUESTIONS.md` §3); failing loudly on a tie means an inflated claim
collides visibly instead of winning silently.
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
    "detect",
    "get",
    "register",
    "registered",
]

#: `detect()` sees a bounded sample, so selection costs the same on a
#: 10-record trace and a 10-million-record one.
DETECTION_SAMPLE_SIZE = 50

#: Below this, nobody is confident enough and the caller is told so.
MINIMUM_CONFIDENCE = 0.5


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
        results = []
        for adapter in self.registered():
            try:
                confidence = float(adapter.detect(sample))
            except Exception as failure:
                # `detect()` must not raise (ADAPTERS.md §2). One that does is
                # a broken adapter, not malformed input, and swallowing it
                # would let a different adapter win by default -- which is
                # exactly the silent-wrong-graph outcome this module exists to
                # prevent. So it is reported, loudly, naming the adapter.
                raise AdapterSelectionError(
                    f"adapter {adapter.id!r} raised during detection "
                    f"({failure!r}); detect() must be pure and must not raise",
                    code=ADAPTER_DETECT_FAILED,
                ) from failure
            results.append((adapter.id, confidence))
        return tuple(results)

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


def _report(measured: Sequence[tuple[str, float]]) -> str:
    listed = ", ".join(f"{name} {confidence:.2f}" for name, confidence in measured)
    return f"Confidence declared by each adapter: {listed}."


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


# Registered here, at the end of the module, so that importing the registry
# also makes the shipped dialects available -- and so that an adapter file
# never has to import the registry back (ADAPTERS.md §4).
from spanweave.adapters.openinference import OpenInferenceAdapter  # noqa: E402
from spanweave.adapters.otel_genai import OtelGenAiAdapter  # noqa: E402

REGISTRY.register(OpenInferenceAdapter())
REGISTRY.register(OtelGenAiAdapter())
