# fixtures/zoo — a stranger's traces, copied byte for byte

The twelve captures of `SigorMatt/spanweave-zoo`: six agents (`ZOO-BRIEFS.md`
Z1–Z6 there), each built by an implementer given its brief and the zoo's
`EXPORT-CONTRACT.md` and nothing about this library, run under stock
instrumentation into a stock Collector 0.162.0 — once against a real model
(`real`) and once against a recorded one (`recorded`).

**Pin:** `SigorMatt/spanweave-zoo` at
`7eb5b6944ccef34861dbaf92e8f0acb0b7edaf99` (`7eb5b69`), the commit its
`PROBES.md` and its twelve `audit/<project>-<run-id>.md` were written at.

**The bodies and manifests are the record and are never edited; this README
is ours and is held by `tests/test_zoo.py`.** Each
`<project>/<run-id>/NNNN.json` is the zoo's
`captures/<project>/<run-id>/json/NNNN.json` — the Collector's OTLP/JSON
re-encoding of the exporter's body — and `MANIFEST.json` beside it is that
capture's sealed manifest, unchanged; the manifest's `json/NNNN.json` entries
name the files here as `NNNN.json`. Each `<project>/<run-id>/raw/NNNN.body` is
the zoo's `captures/<project>/<run-id>/raw/NNNN.body`, the exporter's own
OTLP protobuf body as it was sent — the manifest's `bodies` entries with
`content_type: application/x-protobuf`, named as they are there.
`.gitattributes` marks them `binary`. The headers, `bodies.jsonl`,
`forwards.jsonl` and `collector.log` are not copied: the manifest still lists
and digests them, and they are in the zoo at the pin. `tests/test_zoo.py`
re-derives every body's sha256, JSON and raw, against its manifest, every
manifest's seal against its own claims (the zoo's `SPEC.md` §5, "The seal"),
and that this directory holds exactly those files.

**The pairs are the wire series' oracle.** Every JSON body is paired with the
raw body it re-encodes, read from the manifest's `forwards` list (the `k`-th
JSON body with the `k`-th body forwarded to the Collector), and
`tests/test_zoo.py` asserts that on every capture each JSON body has exactly
one raw body and that the pair shares its `NNNN` — which the zoo's `SPEC.md`
§4.7 does not promise, so the test checks it rather than assumes it. The
JSON path is the one every graph here has been built from; a reader of the
raw bodies is correct when it yields, for each pair, the records the JSON
body yields.

| Capture | Brief | Instrumentation | Bodies (records) | Raw bodies (bytes) | Seal |
|---|---|---|---|---|---|
| `z1/2026-10-13-real` | Z1 `ledger-clerk` | `openinference-instrumentation-langchain==0.1.79` | 2 (22, 9) | 2 (49592, 31379) | `6376317e68e83b0cbc97df11dc20125f98925884e5fa4e541e0b3bc85ae256e8` |
| `z1/2026-10-13-recorded` | Z1 `ledger-clerk` | as above | 1 (31) | 1 (74269) | `609e9a97065a5c2dbb1f11a1ce0c30ddf7b6a3d5887804adbf3ac78cff4f48b9` |
| `z2/2026-10-14-real` | Z2 `fan-out-researcher` | `openinference-instrumentation-llama-index==4.6.0` | 3 (3, 15, 5) | 3 (3684, 24926, 25516) | `17c9833d2a27f898c2379a69efd6ff974c3d5bd6b7976601a29405c6e47b63a7` |
| `z2/2026-10-14-recorded` | Z2 `fan-out-researcher` | as above | 1 (23) | 1 (47985) | `1e7b88b42f90bfcf2a189c93da9c84fafff7ecf34fa04b6e7ba858d6312a8558` |
| `z3/2026-10-13-real` | Z3 `echo-planner` | `openinference-instrumentation-openai-agents==2.5.3`, `openinference-instrumentation-openai==0.1.65` | 4 (24, 32, 32, 14) | 4 (73874, 200084, 202130, 63644) | `14a8ba0bbf285bb4f893e83df4fc4d1593c4421ddb6f2065781376065058594b` |
| `z3/2026-10-13-recorded` | Z3 `echo-planner` | as above | 1 (102) | 1 (499035) | `dc812474cf27936c8fed663b82712efbe0c032fce6298f42ca6b6e899d13f78a` |
| `z4/2026-10-12-real` | Z4 `streaming-concierge` | `opentelemetry-instrumentation-openai-v2==2.4b0`, `opentelemetry-util-genai==0.4b0` | 2 (3, 2) | 2 (4864, 2676) | `f1b6a1d12377f314d6a25bea4601d70744d42955b802a431785d82bfc8bf7353` |
| `z4/2026-10-12-recorded` | Z4 `streaming-concierge` | as above | 1 (5) | 1 (6884) | `808a480dc453ff1281c3354095b4cced48dba352e28ce05d2c580fd78c716446` |
| `z5/2026-10-13-real` | Z5 `flaky-fetcher` | `openinference-instrumentation-langchain==0.1.79` | 1 (4) | 1 (5934) | `6cdcb6f563a37413a20c1f90a3fabeeb6db0e79fc9c6b2ad3b588a2b0000a8b2` |
| `z5/2026-10-13-recorded` | Z5 `flaky-fetcher` | as above | 1 (4) | 1 (5934) | `c9870c1480d1f44f7e06861e325510803bd8497392497795045d88e066548f5d` |
| `z6/2026-10-14-real` | Z6 `crew-of-three` | `openinference-instrumentation-crewai==1.1.21`, `openinference-instrumentation-openai==0.1.65` | 11 (2, 2, 4, 1, 2, 2, 3, 3, 2, 2, 3) | 11 (5337, 12460, 35179, 24887, 20200, 37987, 60373, 109691, 13074, 66973, 155019) | `d90f97c7381bc4de631caa233938e3f469d5f0f7eb0c79c4626fea04650562f9` |
| `z6/2026-10-14-recorded` | Z6 `crew-of-three` | as above | 1 (16) | 1 (114281) | `a9e7228940f7b3c8e042864a058b7db53af2c6454a69d307c6a3163c94fae9d6` |

Instrumentation is each manifest's `project_manifest.instrumentation`; bodies
and records are the zoo's `PROBES.md` "The captures", which the test re-counts;
raw bodies are each capture's `raw/` files, counted and measured by the test,
their bytes in the order their JSON bodies pair with them.
The seals are copied from the zoo's sealed manifests at the pin and are the
pin: the test holds the copy to this table, and holding this table to the zoo
is the reviewer's job, done by comparing it against a checkout of the zoo at
`7eb5b69`, as the cold reviews of 2026-10-14 and 2026-10-15 did.

**The census.** `tests/zoo_census.py` holds eleven counts for each capture —
nodes, `parent` and `temporal` edges, `orphan_parent`, `unpaired_call`,
`unknown` nodes, `timestamp_unit_suspect`, `unmapped_attributes`,
`attributes_dropped`, `exception_event` and `span_event` — and, beside them,
the instrumentation scopes each capture's records state and each graph's node
order and edges with their basis. The first eight counts are the zoo's audit's,
each citing its report, with the report's number kept beside any a batch has
moved; no report counts the last three, whose codes did not exist then. Z4's
whole capture, one record more than the audit fed, is held beside its audit
graph, and its counts are this library's own.
`tests/test_zoo.py` holds this library to them, batch and incremental alike,
with the records fed in the exporter's order (child before parent; the zoo's
`PROBES.md` S15). A change that moves a count updates the census in the commit
that moves it, with the reason. `make conformance` runs it.
