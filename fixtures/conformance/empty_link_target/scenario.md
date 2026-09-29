# empty_link_target

Two spans. The first is an agent; the second is a tool it contains, and the
tool states one span link whose target is `span_id: ""`. The field is present,
and it is empty.

An **empty string is not a span id at either end of a relation** (`SPEC.md`
§3.6), and a link's target is the far end of one. Batch S3 applied that rule to
a record's own `span_id` and to its `parent_id`, and left the third reference
field alone: a link stating `span_id: ""` became an `explicit` `link` edge
whose `dst` was `""` — and, because S3 had made sure no node can be named `""`,
an edge guaranteed to point at nothing (run-5 review 3.1). This scenario exists
because no record in the corpus stated a link target empty, so the sentence was
checkable, false, and checked by nothing.

The rule is now one rule at three fields: an empty link target states no
target, exactly as a link that omits `span_id` does, so it becomes **no link**.
And because a link entry exists only to name a span, an entry that names none
is a declaration the adapter recognized and could not map — it is reported
(below), where an empty `span_id` or `parent_id` is not.

## Structure

Nodes: 1 `agent`, 1 `tool`.

Edges: 1 `parent` (explicit), agent → tool. **No `link` edge**, and in
particular none whose `dst` is `""`. No `temporal` edge: the tool is the
agent's only child and the agent is the only root, so no two spans are
siblings (`SPEC.md` §4.3).

What the record said is still readable on the node: `raw.source.links` carries
`[{"trace_id": "t1", "span_id": ""}]` verbatim (§3.5). `tests/test_adapters.py`
and `tests/test_read.py` assert that carriage, because `canonical()` erases
`raw` and this corpus therefore cannot see it.

Node order: the agent (1000.0), then the tool (1000.5).

## Payloads

Both `absent` on both nodes. Neither record carries a payload attribute, and
`absent` is not `empty` (`SPEC.md` §3.3).

## Usage

None. Neither dialect reports token counts on an agent or a tool span.

## Diagnostics

**One `unmapped_attributes`**, on the tool, naming `<record>.links[0]` — keys
only, never values (`SPEC.md` §3.7). That is what was declared: the first entry
of the record's `links`, which the adapter read and could not turn into a
relation. A link that omits its target, reports it `null`, or reports it as
anything but a non-empty string draws the identical report, because they are
the identical statement. No new diagnostic code: `unmapped_attributes` is the
code §3.7 already gives a record field recognized and not read.

## Cross-dialect notes

Both node ids are stated (`s1`, `s2`), so they are compared by value. `links`
is a **record-level** field, read identically by both adapters, so the two
renderings differ only in the vocabulary of the attributes that state the kind
and the tool's name. This is the first scenario whose `links` field is
rendered in `otel_genai` (`span_links` cannot be; see its `coverage.json`),
though it carries no `link` edge and so leaves that scenario's coverage gap
exactly where it was.

Only `name` is declared dialect-varying, for the reason `missing_payloads`
records.

## Dialects

- [x] `openinference`
- [x] `otel_genai`
