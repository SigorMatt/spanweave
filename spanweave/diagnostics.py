"""Diagnostic codes, and the collector that gathers them during a build.

Diagnostics are the alternative to guessing. When the library cannot map
something confidently, it says so in the output rather than inventing a
plausible answer or dropping the record (``SPEC.md`` §3.7).

The codes are string constants in one place because they are a public
contract once the schema freezes: a consumer matches on them. Adding one is a
deliberate act and a halt point (``AGENT.md``).

The collector is the one deliberately mutable thing in the build path. It is
process state, not model data -- what it produces is a sorted, frozen tuple.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from spanweave.model import Diagnostic, DiagnosticLevel, JsonValue, NodeId

# The dialect reported a span kind we do not map. The node is kept as
# `unknown` and the original string travels with the diagnostic: an honest
# `unknown` is visible, a wrong kind is not.
UNKNOWN_SPAN_KIND = "unknown_span_kind"

# Attributes the adapter did not normalize. **Keys only** -- the values are
# already preserved verbatim in `raw`, and copying payload content into a
# diagnostic is an exposure surface with no benefit (`SPEC.md` §3.7).
UNMAPPED_ATTRIBUTES = "unmapped_attributes"

# A JSON mime type whose value did not parse. `raw` keeps the string.
PAYLOAD_PARSE_FAILED = "payload_parse_failed"

# A `parent` reference to a span that is not in the trace. The node stays.
ORPHAN_PARENT = "orphan_parent"

# A requested tool call with no fulfilling span, and the reverse. Never a
# fabricated pairing, and never a fallback to guessing by name or proximity.
UNPAIRED_CALL = "unpaired_call"
UNPAIRED_RESULT = "unpaired_result"

# No start time, so this node is excluded from temporal edges.
MISSING_TIMESTAMP = "missing_timestamp"

# `ended_at` precedes `started_at`. Reported, never repaired.
NONMONOTONIC_TIME = "nonmonotonic_time"

# Two records claimed the same source id, without their node ids colliding.
# A node id collision is a hard error instead (`SPEC.md` §3.6).
DUPLICATE_SOURCE_ID = "duplicate_source_id"

# More than one trace id in a single input (`SPEC.md` §7).
MULTI_TRACE_INPUT = "multi_trace_input"

# An input line that is not JSON. It cannot become a record, so the diagnostic
# carrying its text is the only place it survives.
MALFORMED_RECORD = "malformed_record"

# The ordering edges contain a cycle, which telemetry should not produce and
# sometimes does. The graph is still built (`SPEC.md` §5.2).
ORDERING_CYCLE = "ordering_cycle"

#: Every code the library emits. A test asserts this matches `SPEC.md` §3.7.
CODES = (
    DUPLICATE_SOURCE_ID,
    MALFORMED_RECORD,
    MISSING_TIMESTAMP,
    MULTI_TRACE_INPUT,
    NONMONOTONIC_TIME,
    ORDERING_CYCLE,
    ORPHAN_PARENT,
    PAYLOAD_PARSE_FAILED,
    UNKNOWN_SPAN_KIND,
    UNMAPPED_ATTRIBUTES,
    UNPAIRED_CALL,
    UNPAIRED_RESULT,
)


@dataclass(slots=True)
class DiagnosticCollector:
    """Gathers diagnostics during a build and hands back a sorted tuple."""

    _items: list[Diagnostic] = field(default_factory=list)

    def add(
        self,
        code: str,
        message: str,
        *,
        level: DiagnosticLevel = DiagnosticLevel.WARNING,
        node_id: NodeId | None = None,
        source: JsonValue = None,
        adapter: str | None = None,
    ) -> None:
        self._items.append(
            Diagnostic(
                code=code,
                message=message,
                level=level,
                node_id=node_id,
                source=source,
                adapter=adapter,
            )
        )

    def extend(self, diagnostics: Iterable[Diagnostic]) -> None:
        self._items.extend(diagnostics)

    def collected(self) -> tuple[Diagnostic, ...]:
        """Sorted by `(code, node_id, message)` (`SPEC.md` §5.2)."""
        return tuple(sorted(self._items, key=lambda d: d.sort_key))

    def __len__(self) -> int:
        return len(self._items)
