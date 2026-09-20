"""The hard errors, and their codes.

Nearly everything the library cannot handle becomes a **diagnostic**, not an
exception: malformed lines, unmappable kinds, unpaired calls, cycles. What is
left here is the short list of structural impossibilities, where continuing
would mean publishing a graph that is quietly wrong (`SECURITY.md`).

The distinction is deliberate. A wrong graph is worse than no graph, because
nothing downstream can tell.

Every error carries a stable ``code``, the same shape and for the same reason
as a diagnostic code (``SPEC.md`` §3.10). Exception *types* are too coarse to
tell a caller what happened -- ``AdapterSelectionError`` alone covers a tie, a
low confidence, an empty registry and an adapter that raised -- and the only
alternative to a code is string-matching the message, which makes every
message a compatibility surface nobody can improve. Codes are a public
contract from ``0.9.x``: naming them is free now and needs a version bump
after the freeze.
"""

from __future__ import annotations

# Two records resolved to the same node id. A silent overwrite would drop a
# record, and losslessness is not negotiable (`SPEC.md` §3.6).
DUPLICATE_NODE_ID = "duplicate_node_id"

# Nothing is registered, so nothing can read this input.
NO_ADAPTERS_REGISTERED = "no_adapters_registered"

# Two or more adapters are equally confident. Never a first-wins race.
ADAPTER_AMBIGUOUS = "adapter_ambiguous"

# Nobody is confident enough. Never a best guess.
ADAPTER_UNCONFIDENT = "adapter_unconfident"

# An adapter raised from `detect()`, which the protocol forbids. Reported
# rather than scored zero: swallowing it lets another adapter win by default.
ADAPTER_DETECT_FAILED = "adapter_detect_failed"

# Two adapters claim the same id.
DUPLICATE_ADAPTER_ID = "duplicate_adapter_id"

# A caller named an adapter that is not registered.
UNKNOWN_ADAPTER = "unknown_adapter"

# A value the library must encode cannot be: it nests deeper than the JSON
# encoder will descend, is a non-finite number RFC 8259 has no token for, or
# refers back to itself. Either the graph is held and cannot be written, or a
# record cannot be digested (`SPEC.md` §3.6). Nothing may be dropped to get
# past any of them -- the verbatim record is the whole of losslessness -- so
# there is no graph to publish, and saying so beats an interpreter's
# traceback.
GRAPH_NOT_SERIALIZABLE = "graph_not_serializable"

#: Every code the library raises. A test asserts this matches `SPEC.md` §3.10.
ERROR_CODES = (
    ADAPTER_AMBIGUOUS,
    ADAPTER_DETECT_FAILED,
    ADAPTER_UNCONFIDENT,
    DUPLICATE_ADAPTER_ID,
    DUPLICATE_NODE_ID,
    GRAPH_NOT_SERIALIZABLE,
    NO_ADAPTERS_REGISTERED,
    UNKNOWN_ADAPTER,
)


class SpanweaveError(Exception):
    """Base class for every error the library raises deliberately."""

    #: Stable and machine-matchable. Match on this, never on the message.
    code: str = "spanweave_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class AdapterSelectionError(SpanweaveError):
    """No adapter could be chosen for this input, or more than one could.

    Never a silent fallback to a default: an ambiguous input that quietly
    produced a plausible graph from the wrong adapter is this library's worst
    failure mode, because nothing downstream could detect it (`SPEC.md` §6.1).

    One type, several causes -- which is exactly why the cause travels in
    ``code`` rather than in the message.
    """

    code = ADAPTER_AMBIGUOUS


class UnknownAdapterError(SpanweaveError):
    """A caller named an adapter that is not registered."""

    code = UNKNOWN_ADAPTER


class DuplicateNodeIdError(SpanweaveError):
    """Two records claimed the same node id.

    A silent overwrite would drop a record, and losslessness is not
    negotiable (`SPEC.md` §3.6, `CLAUDE.md` 2).
    """

    code = DUPLICATE_NODE_ID


class GraphNotSerializableError(SpanweaveError):
    """A value the library must encode cannot be, so there is nothing to publish.

    Raised where the reader's own guard cannot help. Three things defeat the
    encoder, and `json.dumps` reports them as **two different exception
    types**, which is why the guard names both:

    * A value the JSON parser accepted at the top level can still nest deeper
      than the encoder will descend once it sits inside a graph document
      (`SPEC.md` §7 measures the offset). That arrives as ``RecursionError``.
    * A non-finite number -- ``inf``, ``-inf``, ``nan`` -- which RFC 8259 has
      no token for, and which the encoder is told to refuse rather than write
      as Python's extension to JSON. That arrives as ``ValueError``.
    * A value that refers back to itself, which JSON cannot express at all.
      That arrives as ``ValueError`` too, so the message says which of the two
      it was rather than guessing.

    A guard that named only one of the two types would be a guard that is not
    there for the other, and what escapes instead is an interpreter traceback
    from a build that read its input without complaint (§7's rule that
    unreadable input never escapes as one).

    It is a refusal rather than a diagnostic because nothing can be dropped to
    get past it: the offending value may be a node's verbatim source record,
    and losslessness is not negotiable (`CLAUDE.md` 2). What a caller acts on
    is the ``code`` (`SPEC.md` §3.10), which the CLI prints on stderr for the
    same reason.

    **Two places raise it, for one fact about one value.** Writing a graph is
    the obvious one. The other is `spanweave.read.record_digest`: a record's
    canonical digest is an encode too (`SPEC.md` §3.6), so on an interpreter
    whose encoder ceiling is the lower of the two the *reader* meets it first,
    on a record the parser was willing to read. A record with no digest has no
    identity and could not have been written either, so it is the same
    refusal and not a second code to learn.
    """

    code = GRAPH_NOT_SERIALIZABLE
