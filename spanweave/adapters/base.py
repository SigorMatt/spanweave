"""What an adapter is.

An adapter teaches `spanweave` exactly one telemetry dialect, and it is the
only place dialect knowledge may live. Full authoring guide: ``ADAPTERS.md``.

The seam types are defined in ``spanweave.seam`` and re-exported here, because
an adapter author should need one import and because the builder must be able
to name ``NormalizedSpan`` without importing anything from this package
(``DESIGN.md`` §2).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import Protocol, runtime_checkable

from spanweave.model import JsonValue
from spanweave.seam import CallRole, DeclaredDataEdge, NormalizedSpan, SpanLink

__all__ = [
    "Adapter",
    "CallRole",
    "DeclaredDataEdge",
    "NormalizedSpan",
    "SpanLink",
]


@runtime_checkable
class Adapter(Protocol):
    """One dialect, translated. Nothing more (`SPEC.md` §6)."""

    #: Stable, lowercase, no spaces.
    id: str
    #: The adapter's own version, independent of the library's.
    version: str

    def detect(self, sample: Sequence[JsonValue]) -> float:
        """Confidence in ``[0.0, 1.0]`` that this adapter handles the input.

        Pure, and it must not raise. Key on distinctive marker keys, not on
        generic ones. Be honest about partial matches, and **do not return
        1.0 defensively**: inflated confidence turns detection into a race,
        and a wrong adapter silently producing a plausible graph is far worse
        than an honest "ambiguous input" error.
        """
        ...

    def parse(self, records: Iterable[JsonValue]) -> Iterator[NormalizedSpan]:
        """Translate records into spans.

        Pure, lazy, order-independent, and it never raises on malformed
        input: what cannot be mapped becomes a diagnostic on the span, or an
        ``unknown`` span carrying the record verbatim. Transcribe, don't
        interpret -- every temptation to infer something the dialect did not
        say is answered with a ``Diagnostic`` or a ``None``.
        """
        ...
