# genai_workflow.jsonl — provenance

## What this is

A captured trace of a two-leg workflow, run by hand through
`make capture --backend genai --shape workflow`. Not hand-authored.

Topology: `invoke_workflow -> [invoke_agent, invoke_agent]`, the second
`invoke_agent` carrying an OTel span link back to the first. Each leg is a
complete tool-using conversation of its own (`chat` -> `execute_tool` ->
`chat`).

## Capture details

- **Instrumentor:** opentelemetry-instrumentation-genai-openai 1.1b0
- **SDK:** openai 3.3.1
- **OTel SDK:** opentelemetry-sdk 1.44.0
- **Dialect emitted:** `otel_genai`
- **Model:** openai/gpt-oss-120b
- **Endpoint:** https://api.tokenfactory.nebius.com/v1/
- **Captured:** 2026-08-27
- **Command:** `make capture --backend genai --shape workflow`
- **Shape:** `workflow` — a workflow of two agent legs, the second linked to
  the first: `invoke_workflow -> [invoke_agent, invoke_agent]`

## Not part of the matched pair

`genai_tool_call.jsonl` and `openai_tool_call.jsonl` are a **matched pair**:
same model, same prompt, same tool inventory, differing only in the
instrumentor. **This file is not part of that pair and must not be folded into
it.** It has different prompts (weather *and* population, not weather alone), a
different tool inventory (`get_weather` *and* `get_population`), a different
topology (a workflow over two agent legs, not one conversation), and **no
twin** — there is no OpenInference capture of this shape. Any claim of the form
"the dialects agree, because nothing else varies" rests on the pair, not on
this file.

## The `invoke_workflow` span is harness-emitted

The `invoke_workflow` root is emitted by `capture/backends.py`, **not** by the
instrumentor. An instrumentor wraps SDK calls, and a workflow is not an SDK
call — no instrumentor has anything to hook.

What the conventions supply is the **vocabulary**: `invoke_workflow` is one of
the nine normative `gen_ai.operation.name` values, and `gen_ai.workflow.name`
is a defined attribute. So the span is **convention-named and
harness-emitted** — exactly the standing `execute_tool` has in
`genai_tool_call.jsonl`.

Its payloads are **absent**, and that is correct rather than a gap: the
conventions describe no message content for a workflow, so there is nothing
for the harness to have recorded.

## The span link

OTel span links are a **record-level field of the span data model**, identical
in both dialects — not a GenAI attribute and not an OpenInference one. The
**field** is therefore convention-defined.

**Which** spans are linked is ours. That is why the link is attributed as
`spanweave.capture.link = previous_workflow_leg` rather than under a `gen_ai.`
name: inventing a `gen_ai.`-prefixed key for a relation the conventions do not
define would misrepresent our own choice as a standard one.

The link asserts only **"this leg ran after that one, inside this workflow."**
The two legs are independent conversations — neither leg's messages carry the
other's, and no data flows between them.

The link is **in-trace only**. A cross-trace link would require naming a span
in a trace this run did not produce, which a single capture run cannot do
honestly.

## Redaction

Nothing was redacted, and that was checked rather than assumed.

Reviewed by Matthew Sigurko on 2026-08-27. Every payload was read in full, not
merely pattern-scanned. The content is two synthetic Paris queries — one about
weather, one about population — against stub tools returning fixed values.
Scanned for credential patterns (API key prefixes, bearer tokens, URLs with
embedded credentials): none found.

**`server.address` is kept, deliberately.**
`server.address = api.tokenfactory.nebius.com` appears **4 times**, once on
each `chat` span. It is a public endpoint hostname carrying no credential, and
this file names the endpoint anyway.

## What this fixture may be used to claim

**It is the capture that makes three scenarios renderable.** Three conformance
scenarios were declared unrenderable at `TASKS.md` 2.10 for want of a captured
workflow trace; this file retires that.

**It restores `EdgeKind.link` to the cross-dialect claim.** `link` was
previously untested across dialects — no captured trace exercised it. This one
does.

**It builds to 9 nodes / 18 edges** — and the `invoke_workflow` root degrades
to kind `unknown` plus an `unknown_span_kind` diagnostic, **retained rather
than dropped**. That degradation is the honest current behaviour, and recording
it is part of what this fixture is for: the fixture is evidence of what the
library does today, not of what it ought to do.

**Only the `chat` spans come from the instrumentor.** As with
`genai_tool_call.jsonl`, "captured from real instrumentation" is true of some
spans here and not others: the `invoke_workflow` root, both `invoke_agent`
spans and both `execute_tool` spans are emitted by `capture/backends.py`.
