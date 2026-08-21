# SECURITY.md

## Reporting a vulnerability

Email **m.sigor@gmail.com** with details and, if possible, a minimal reproducing
trace. Please do not open a public issue for a suspected vulnerability. Expect an
acknowledgement within a few days.

If your reproducer contains real data, redact it first — and tell us what you
redacted rather than sending the original.

## Threat model

`spanweave` parses **untrusted input by design**. Agent traces contain model
outputs, retrieved web pages, tool results, and user text. Any of it may be
adversarial, malformed, or enormous. The library's security posture follows
directly from that.

### What we assume

- Trace content is **hostile data**. Payload strings may contain injection
  attempts, control characters, deeply nested structures, or gigabyte values.
- Trace files may be **malformed**: truncated lines, invalid JSON, duplicate ids,
  cyclic parent references, timestamps in the wrong order.
- The library may run **inside CI or a security pipeline**, where a crash or a
  hang is itself a denial of service, and a wrong graph is worse than no graph.

### What the library guarantees

- **No execution.** Trace content is never evaluated, imported, deserialized
  into objects, or used to construct code paths. No `eval`, `exec`,
  `__import__`, `pickle`, `marshal`, or `yaml.load` — anywhere. CI gate
  (`TASKS.md` 0.4).
- **No network.** Core opens no sockets, fetches no URLs, resolves no hostnames,
  and listens on nothing. It cannot exfiltrate a trace it parses, and it cannot
  be pointed at a remote URL to fetch one. CI gate.
- **No filesystem writes** except the output the user explicitly requested.
  Nothing is written to temp directories, caches, or the input's directory.
- **No crash on malformed input.** Parsing failures produce **diagnostics**, not
  exceptions. The only hard errors are structural impossibilities (duplicate
  span ids, id collisions) where continuing would produce a *silently wrong*
  graph — and failing loudly is the safer outcome.
- **No unbounded recursion.** Traversal is iterative; cycles are detected and
  diagnosed, never followed (`SPEC.md` §5.2).
- **No payload interpretation.** The library does not scan payloads for secrets,
  PII, or injection patterns. It does not redact. It reports what the source
  reported (`SPEC.md` §9).

### What the library does *not* protect you from

Stated plainly, because a library that overclaims here is dangerous:

- **`spanweave` does not sanitize your traces.** If you feed it a trace
  containing credentials, the graph will contain those credentials. Redaction is
  your responsibility, upstream or downstream.
- **`spanweave` does not detect anything.** It is not a security tool. It builds
  no findings and makes no judgements. Tools built on top of it may; those are
  separate projects with their own threat models.
- **Memory is proportional to input.** A hostile multi-gigabyte trace will
  consume multi-gigabyte memory. Bound your inputs if you accept them from
  untrusted parties. Streaming (which would change this) is parked
  (`ROADMAP.md`).
- **Graph output contains payload content by design** (losslessness,
  `CLAUDE.md` 2). Treat `graph.json` with exactly the same sensitivity as the
  trace it came from. It is not a redacted artifact and was never intended as
  one.

## Handling traces safely

- **Never commit a real trace without human review and redaction.** Captured
  fixtures require a provenance file recording what was redacted and by whom
  (`FIXTURES.md` §6).
- Treat `graph.json` as sensitive as its source trace.
- In CI, prefer committed fixtures over live captures. The capture harness is
  human-run and lives outside the package for exactly this reason
  (`ENVIRONMENT.md`).

## Supported versions

Pre-1.0: only the latest release receives fixes. Once `schema_version` 1 is
frozen (Phase 4), a support policy will be published here.
