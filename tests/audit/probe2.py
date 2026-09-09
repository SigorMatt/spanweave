"""Audit reproduction script (probe2). Run: python tests/audit/probe2.py

September 2026 audit. Each case prints what spanweave did; lines marked
!!! UNCAUGHT are contract violations, REFUSED are hard errors, the rest are
graphs with their diagnostics. See WORKPLAN.md section 5 for the mapping
from case to fix batch. Not collected by pytest; batches convert cases into
regression tests as they fix them.
"""
import json, pathlib, sys, time, tracemalloc
import spanweave
from spanweave import SpanweaveError

import tempfile
OUT = pathlib.Path(tempfile.mkdtemp(prefix="spanweave-audit-"))
sys.setrecursionlimit(1000)

def oi(sid, parent, kind, name, t0, t1, attrs=None, status="OK", trace="t1"):
    return {"trace_id": trace, "span_id": sid, "parent_id": parent, "name": name, "start_time": t0, "end_time": t1, "status": status,
            "attributes": {"openinference.span.kind": kind, **(attrs or {})}}

def write(label, records):
    p = OUT / f"{label}.jsonl"; p.write_text("\n".join(json.dumps(r) for r in records) + "\n"); return p

def timed(label, fn):
    tracemalloc.start(); t = time.perf_counter()
    try:
        r = fn()
    except SpanweaveError as e:
        print(f"{label}: REFUSED {type(e).__name__} [{getattr(e,'code','?')}] {str(e)[:160]}"); tracemalloc.stop(); return None
    except Exception as e:
        print(f"{label}: !!! UNCAUGHT {type(e).__name__}: {str(e)[:160]}"); tracemalloc.stop(); return None
    dt = time.perf_counter() - t; peak = tracemalloc.get_traced_memory()[1] / 1e6; tracemalloc.stop()
    print(f"{label}: {dt:.2f}s peak {peak:.0f}MB", end=" ")
    return r

# A. Exact duplicate lines (collector retry / at-least-once export) is now a
# regression test, not a probe: tests/test_read.py, under "Duplicate records".
# Fixed in batch A3.

# B. Agent loop with history echo: N llm->tool turns, each llm input carries every prior tool result.
def loop(n):
    recs = [oi("s0", None, "AGENT", "agent", 1000.0, 1000.0 + n)]
    t = 1000.0
    for i in range(n):
        attrs = {"llm.model_name": "m", "llm.token_count.prompt": 10, "llm.token_count.completion": 2,
                 f"llm.output_messages.0.message.tool_calls.0.tool_call.id": f"c{i}",
                 f"llm.output_messages.0.message.tool_calls.0.tool_call.function.name": "t"}
        attrs["llm.input_messages.0.message.role"] = "user"
        for j in range(i):  # history echo
            attrs[f"llm.input_messages.{j+1}.message.role"] = "tool"
            attrs[f"llm.input_messages.{j+1}.message.tool_call_id"] = f"c{j}"
        recs.append(oi(f"l{i}", "s0", "LLM", "llm", t + 0.1, t + 0.4, attrs)); 
        recs.append(oi(f"t{i}", "s0", "TOOL", "tool", t + 0.5, t + 0.9, {"tool.name": "t", "tool_call.id": f"c{i}", "output.value": "{}"}))
        t += 1.0
    return recs

for n in (50, 200, 400):
    p = write(f"loop{n}", loop(n))
    g = timed(f"history_echo_loop turns={n} file={p.stat().st_size//1024}KB", lambda: spanweave.build(p))
    if g:
        ek = {}
        for e in g.edges(): ek[str(e.kind)] = ek.get(str(e.kind), 0) + 1
        print(f"nodes={len(g)} edges={ek}")

# C. Flat wide trace: one root, N tool children, no echo.
for n in (5000, 20000):
    recs = [oi("s0", None, "AGENT", "a", 0.0, n)] + [oi(f"t{i}", "s0", "TOOL", "t", i, i + 0.5, {"tool.name": "t"}) for i in range(n)]
    p = write(f"wide{n}", recs)
    g = timed(f"wide n={n}", lambda: spanweave.build(p))
    if g:
        t = time.perf_counter(); g.topo_order; g.subgraph(edge_kinds={"parent"}); print(f"nodes={len(g)}  topo+subgraph {time.perf_counter()-t:.2f}s")

# D. Deep parent chain
for n in (500, 3000):
    recs = [oi("s0", None, "AGENT", "a", 0.0, n + 1)] + [oi(f"c{i}", f"c{i-1}" if i else "s0", "CHAIN", "c", i * 0.001, n, ) for i in range(n)]
    p = write(f"deep{n}", recs)
    g = timed(f"deep_chain depth={n}", lambda: spanweave.build(p))
    if g:
        t = time.perf_counter()
        try:
            a = g.ancestors(f"c{n-1}"); d = g.descendants("s0"); print(f"ancestors={len(a)} descendants={len(d)} {time.perf_counter()-t:.2f}s")
        except Exception as e:
            print(f"!!! query {type(e).__name__}: {str(e)[:100]}")

# E. Annotation cost is now a regression test, not a probe: tests/test_graph.py,
# under "What annotating copies" and "annotate_many". The test asserts the structural
# property (an annotated graph shares its node and edge indexes, so the work per
# annotation does not grow with the graph) rather than a wall-clock number.
# Fixed in batch B1.

# F. Huge single line read (a 40MB payload on one span)
big = "x" * 40_000_000
p = OUT / "bigline.jsonl"; p.write_text(json.dumps(oi("s0", None, "AGENT", "a", 1.0, 2.0, {"input.value": big})) + "\n")
g = timed("single_40MB_line", lambda: spanweave.build(p)); print()

# G. ns-int timestamp precision: two spans 100ns apart
recs = [oi("s0", None, "AGENT", "a", 1700000000000000000, 1700000002000000000),
        oi("s1", "s0", "TOOL", "t", 1700000000100000000, 1700000000200000000, {"tool.name": "t"}),
        oi("s2", "s0", "TOOL", "u", 1700000000100000100, 1700000000200000100, {"tool.name": "u"})]
g = spanweave.build(write("ns", recs))
print(f"ns precision: s1.start={g.node('s1').started_at!r} s2.start={g.node('s2').started_at!r} equal={g.node('s1').started_at == g.node('s2').started_at} temporal={[ (e.src,e.dst) for e in g.edges(kind='temporal')]} duration_s1={g.node('s1').ended_at - g.node('s1').started_at}")
