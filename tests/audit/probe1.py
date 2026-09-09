"""Audit reproduction script (probe1). Run: python tests/audit/probe1.py

September 2026 audit. Each case prints what spanweave did; lines marked
!!! UNCAUGHT are contract violations, REFUSED are hard errors, the rest are
graphs with their diagnostics. See WORKPLAN.md section 5 for the mapping
from case to fix batch. Not collected by pytest; batches convert cases into
regression tests as they fix them.
"""
import json, pathlib, sys, traceback
import spanweave
from spanweave import SpanweaveError

import tempfile
OUT = pathlib.Path(tempfile.mkdtemp(prefix="spanweave-audit-"))

def oi(sid, parent, kind, name, t0, t1, attrs=None, status="OK", **extra):
    r = {"trace_id": "t1", "span_id": sid, "parent_id": parent, "name": name, "start_time": t0, "end_time": t1, "status": status,
         "attributes": {"openinference.span.kind": kind, **(attrs or {})}}
    r.update(extra); return r

def genai(sid, parent, name, t0, t1, attrs):
    return {"trace_id": "t1", "span_id": sid, "parent_id": parent, "name": name, "start_time": t0, "end_time": t1, "status": "OK", "attributes": attrs}

def run(label, records, adapter=None, raw=None):
    p = OUT / f"{label}.jsonl"
    if raw is not None:
        p.write_bytes(raw)
    else:
        p.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    print(f"\n=== {label}")
    try:
        g = spanweave.build(p, adapter=adapter)
    except SpanweaveError as e:
        print(f"  REFUSED {type(e).__name__} [{getattr(e,'code','?')}]: {str(e)[:220]}")
        return None
    except Exception as e:
        print(f"  !!! UNCAUGHT {type(e).__name__}: {str(e)[:200]}")
        return None
    kinds = {}
    for n in g.nodes(): kinds[str(n.kind)] = kinds.get(str(n.kind), 0) + 1
    ek = {}
    for e in g.edges(): ek[str(e.kind)] = ek.get(str(e.kind), 0) + 1
    print(f"  nodes={len(g)} {kinds} edges={ek} trace={g.trace_id!r}")
    for d in g.diagnostics:
        if d.code != "unmapped_attributes":
            print(f"  diag {d.level} {d.code} node={d.node_id}: {d.message[:150]}")
    return g

# 1. Mixed instrumentation: OpenInference framework spans + OTel GenAI SDK span in one trace.
mixed = [
    oi("s0", None, "AGENT", "agent.run", 1000.0, 1003.0),
    genai("s1", "s0", "chat gpt-x", 1000.1, 1001.0, {"gen_ai.operation.name": "chat", "gen_ai.request.model": "gpt-x",
          "gen_ai.output.messages": json.dumps([{"role": "assistant", "parts": [{"type": "tool_call", "id": "c1", "name": "lookup", "arguments": {}}]}])}),
    oi("s2", "s0", "TOOL", "tool.lookup", 1001.1, 1001.5, {"tool.name": "lookup", "tool_call.id": "c1", "output.value": "{}"}),
]
run("mixed_detect", mixed)
g = run("mixed_forced_oi", mixed, adapter="openinference")
run("mixed_forced_otel", mixed, adapter="otel_genai")

# 2. Deep JSON nesting (audit finding 3) is now a regression test, not a probe:
# tests/test_read.py (record line, array container), tests/test_openinference.py
# and tests/test_otel_genai.py (payload and message list). Fixed in batch A1.

# 3. Parent structure abuse
run("self_parent", [oi("s0", "s0", "AGENT", "a", 1.0, 2.0)])
run("parent_cycle", [oi("s0", "s1", "AGENT", "a", 1.0, 2.0), oi("s1", "s0", "CHAIN", "b", 1.1, 1.9)])
run("orphan_parent", [oi("s0", "nope", "AGENT", "a", 1.0, 2.0)])
run("duplicate_ids", [oi("s0", None, "AGENT", "a", 1.0, 3.0), oi("s1", "s0", "TOOL", "t", 1.1, 1.5, {"tool.name": "t"}), oi("s1", "s0", "TOOL", "t2", 1.6, 1.9, {"tool.name": "t2"})])

# 4. Timestamps
run("ns_int_timestamps", [oi("s0", None, "AGENT", "a", 1700000000000000000, 1700000001000000000), oi("s1", "s0", "TOOL", "t", 1700000000100000000, 1700000000200000000, {"tool.name": "t"})])
run("string_timestamps", [oi("s0", None, "AGENT", "a", "2026-09-05T10:00:00Z", "2026-09-05T10:00:02Z")])
run("nan_timestamps", None, raw=b'{"trace_id":"t1","span_id":"s0","parent_id":null,"name":"n","start_time":NaN,"end_time":Infinity,"status":"OK","attributes":{"openinference.span.kind":"AGENT"}}\n')
run("end_before_start", [oi("s0", None, "AGENT", "a", 5.0, 1.0)])
run("equal_starts", [oi("s0", None, "AGENT", "a", 1.0, 3.0), oi("s1", "s0", "TOOL", "t", 1.5, 1.6, {"tool.name": "t"}), oi("s2", "s0", "TOOL", "u", 1.5, 1.7, {"tool.name": "u"})])

# 5. Multi-trace file
two = [oi("s0", None, "AGENT", "a", 1.0, 2.0)] + [dict(oi("x0", None, "AGENT", "b", 1.0, 2.0), trace_id="t2")]
run("two_traces", two)
run("two_traces_first_is_child", [dict(oi("x0", None, "AGENT", "b", 1.0, 2.0), trace_id="t2"), oi("s0", None, "AGENT", "a", 1.0, 2.0), oi("s1", "s0", "TOOL", "t", 1.1, 1.2, {"tool.name": "t"})])

# 6. Degenerate inputs
run("empty", None, raw=b"")
run("whitespace", None, raw=b"\n\n   \n")
# A BOM at the head of the file (audit finding: minor) and CR-only or CRLF line
# endings are now regression tests, not probes: tests/test_read.py, under
# "Encoding and line endings". Fixed in batch A2.
run("no_trace_id", [{k: v for k, v in oi("s0", None, "AGENT", "a", 1.0, 2.0).items() if k != "trace_id"}])
run("missing_span_id", [{k: v for k, v in oi("s0", None, "AGENT", "a", 1.0, 2.0).items() if k != "span_id"}, oi("s1", None, "TOOL", "t", 1.0, 2.0, {"tool.name": "t"})])
run("attributes_not_dict", [dict(oi("s0", None, "AGENT", "a", 1.0, 2.0), attributes=["openinference.span.kind"])])
run("otlp_json_envelope", None, raw=json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [{"traceId": "t1", "spanId": "s0", "name": "chat", "startTimeUnixNano": "1", "endTimeUnixNano": "2", "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}}]}]}]}]}).encode())

# 7. call_result to a span of another kind, and result before request in time
run("call_result_to_llm", [oi("s0", None, "AGENT", "a", 1.0, 3.0),
    oi("s1", "s0", "LLM", "l", 1.1, 1.5, {"llm.model_name": "m", "llm.output_messages.0.message.tool_calls.0.tool_call.id": "c1", "llm.output_messages.0.message.tool_calls.0.tool_call.function.name": "x"}),
    oi("s2", "s0", "LLM", "l2", 1.6, 1.9, {"llm.model_name": "m", "tool_call.id": "c1"})])
run("result_before_request", [oi("s0", None, "AGENT", "a", 1.0, 3.0),
    oi("s1", "s0", "LLM", "l", 2.0, 2.5, {"llm.model_name": "m", "llm.output_messages.0.message.tool_calls.0.tool_call.id": "c1", "llm.output_messages.0.message.tool_calls.0.tool_call.function.name": "x"}),
    oi("s2", "s0", "TOOL", "t", 1.1, 1.5, {"tool.name": "x", "tool_call.id": "c1"})])
