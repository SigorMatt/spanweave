"""Turning real OTel spans into the flat JSONL dialect the corpus uses.

The conformance renderings are flat JSONL -- one span per line, with
``span_id``, ``parent_id``, unix-second timestamps, and OpenInference
attributes. A real instrumentor emits OTel ``ReadableSpan`` objects. This is
the adapter between the two, and it is the part of the harness worth testing,
because everything else is a network call.

Deliberately **duck-typed**: it reads attributes off whatever it is given and
imports nothing from opentelemetry. That means the conversion can be tested
against a stub span without the SDK installed -- which is how it is tested.
"""

from __future__ import annotations

NANOSECONDS = 1_000_000_000

STATUS_NAMES = {0: "UNSET", 1: "OK", 2: "ERROR"}


def _hex(value, width):
    """OTel ids are integers; the dialect writes them as fixed-width hex."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return format(value, f"0{width}x")


def _seconds(nanoseconds):
    """Unix seconds, as the dialect reports them. Never rounded to a whole."""
    if nanoseconds is None:
        return None
    return nanoseconds / NANOSECONDS


def _json_safe(value):
    """OTel attribute values are primitives and sequences of primitives."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _status_of(span):
    status = getattr(span, "status", None)
    if status is None:
        return "UNSET", None
    code = getattr(status, "status_code", None)
    name = getattr(code, "name", None) or STATUS_NAMES.get(
        getattr(code, "value", None), "UNSET"
    )
    return str(name), getattr(status, "description", None)


def _links_of(span):
    links = []
    for link in getattr(span, "links", ()) or ():
        context = getattr(link, "context", None)
        if context is None:
            continue
        links.append(
            {
                "trace_id": _hex(getattr(context, "trace_id", None), 32),
                "span_id": _hex(getattr(context, "span_id", None), 16),
                "attributes": {
                    str(key): _json_safe(value)
                    for key, value in dict(
                        getattr(link, "attributes", {}) or {}
                    ).items()
                },
            }
        )
    return links


def record_of(span):
    """One OTel span as one line of the flat OpenInference dialect.

    Nothing is renamed, dropped, or interpreted on the way through: whatever
    the instrumentor put in ``attributes`` is what the fixture will contain,
    which is the entire reason a captured trace is worth more than a
    hand-authored one.
    """
    context = getattr(span, "context", None) or span.get_span_context()
    parent = getattr(span, "parent", None)
    status, message = _status_of(span)

    record = {
        "trace_id": _hex(getattr(context, "trace_id", None), 32),
        "span_id": _hex(getattr(context, "span_id", None), 16),
        "parent_id": _hex(getattr(parent, "span_id", None), 16) if parent else None,
        "name": getattr(span, "name", ""),
        "start_time": _seconds(getattr(span, "start_time", None)),
        "end_time": _seconds(getattr(span, "end_time", None)),
        "status": status,
        "attributes": {
            str(key): _json_safe(value)
            for key, value in dict(getattr(span, "attributes", {}) or {}).items()
        },
    }
    if message:
        record["status_message"] = message
    links = _links_of(span)
    if links:
        record["links"] = links
    return record


class JsonlSpanExporter:
    """An OTel ``SpanExporter`` that appends dialect records to a list.

    Kept in memory rather than streamed to a file: the human has to read and
    redact this before it becomes a fixture (`FIXTURES.md` §6), and a harness
    that writes as it goes invites committing whatever landed on disk.
    """

    def __init__(self):
        self.records = []

    def export(self, spans):
        self.records.extend(record_of(span) for span in spans)
        return None

    def shutdown(self):
        return None

    def force_flush(self, timeout_millis=30_000):
        return True

    def sorted_records(self):
        """Start-time order, which is the order a human will want to read."""
        return sorted(
            self.records,
            key=lambda record: (
                record["start_time"]
                if record["start_time"] is not None
                else float("inf"),
                record["span_id"] or "",
            ),
        )
