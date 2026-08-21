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

#: Every code the library raises. A test asserts this matches `SPEC.md` §3.10.
ERROR_CODES = (
    ADAPTER_AMBIGUOUS,
    ADAPTER_DETECT_FAILED,
    ADAPTER_UNCONFIDENT,
    DUPLICATE_ADAPTER_ID,
    DUPLICATE_NODE_ID,
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
