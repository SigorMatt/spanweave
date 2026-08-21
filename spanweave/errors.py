"""The hard errors.

Nearly everything the library cannot handle becomes a **diagnostic**, not an
exception: malformed lines, unmappable kinds, unpaired calls, cycles. What is
left here is the short list of structural impossibilities, where continuing
would mean publishing a graph that is quietly wrong (`SECURITY.md`).

The distinction is deliberate. A wrong graph is worse than no graph, because
nothing downstream can tell.
"""

from __future__ import annotations


class SpanweaveError(Exception):
    """Base class for every error the library raises deliberately."""


class AdapterSelectionError(SpanweaveError):
    """No adapter could be chosen for this input, or more than one could.

    Never a silent fallback to a default: an ambiguous input that quietly
    produced a plausible graph from the wrong adapter is this library's worst
    failure mode, because nothing downstream could detect it (`SPEC.md` §6.1).
    """


class UnknownAdapterError(SpanweaveError):
    """A caller named an adapter that is not registered."""


class DuplicateNodeIdError(SpanweaveError):
    """Two records claimed the same node id.

    A silent overwrite would drop a record, and losslessness is not
    negotiable (`SPEC.md` §3.6, `CLAUDE.md` 2).
    """
