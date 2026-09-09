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

# B. Agent loop with history echo is now two regression tests, not a probe.
# The DIAGNOSTIC half is tests/test_openinference.py, under "The keys a
# decision reads" (batch B3): loop 400's `unmapped_attributes` went from
# 13,193,072 bytes to 99,092 once the adapter consumed the keys it reads.
# The EDGE half is the same file, under `_echo_loop_trace` (batch D2): the
# n(n-1)/2 `data` edges are the file's own declaration count and every one of
# them stays, so the test asserts the count AND the basis split rather than a
# smaller number. Measured at the turn counts this probe used: 50 -> 1,225
# edges (49 earliest, 1,176 later), 200 -> 19,900 (199 / 19,701), 400 ->
# 79,800 (399 / 79,401), 0 decided by a tie. The volume is the telemetry's and
# `SPEC.md` §4.2.1 now says which declaration came first.

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

# G. ns-int timestamp precision is now a regression test, not a probe:
# tests/test_adapters.py, under "An integer timestamp keeps its digits". A
# timestamp reported as an integer literal is carried as an `int`, so two
# spans 100 ns apart no longer collapse onto one float and the edge between
# them is strict rather than tied. Fixed in batch C3.
