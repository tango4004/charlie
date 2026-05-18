# Charlie

**Charlie** is a minimal async protocol for connecting LLM agents to workspaces and to each other via MCP (Model Context Protocol).

It defines:
- An 8-field packet format (including `reply_to` for stateless return routing)
- A named-pipe transport model with variable stream count per connector
- A standard MCP interface (4 tools, never changes)
- Two component types: internal cubes (primitives) and external connectors (plugins)
- A schema-driven assembly/disassembly lifecycle (up/down, cold/warm)

Charlie does not prescribe connector internals, workspace logic, or security policies.

---

## Documents

| Document | Description |
|----------|-------------|
| [SPEC.md](SPEC.md) | Core protocol: packet format, routing model, TTL, versioning |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design: cubes vs connectors, schema, lifecycle, topology |
| [CONNECTOR.md](CONNECTOR.md) | MCP bridge interface: help, call, get_result, get_error |
| [WORKSPACE.md](WORKSPACE.md) | Workspace contract: stdin/stdout/stderr, help, identity |

---

## Design Principles

**Dumb pipe.** The buffer holds packets and delivers them. It does not interpret, transform, or route by payload content.

**Immutable payload.** What goes in comes out unchanged. No middleware touches the payload.

**Async by default.** Clients submit work and poll results. No blocking, no timeouts on the call side.

**Frozen interface.** Four MCP tools, forever. New workspace types do not require client reconnection.

**Streams, not messages.** Three independent channels per job: stdin (in), stdout (results), stderr (errors). Mirrors Unix conventions.

---

## Architecture

```
Client
  │
  │  MCP / streamable-http
  ▼
Charlie Bridge          ← validates token, wraps payload in packets
  │
  │  HTTP  (stdin stream)
  ▼
Buffer                  ← stores packets, enforces TTL, three streams per job_id
  │
  │  HTTP  (stdin stream)
  ▼
Workspace               ← executes, writes to stdout/stderr streams
  │
  │  HTTP  (stdout / stderr streams)
  ▼
Buffer
  │
  │  HTTP  (stdout / stderr streams)
  ▼
Charlie Bridge
  │
  │  MCP response
  ▼
Client
```

---

## Naming

Charlie (C) is part of a broader roadmap:

- **Alpha** — open inter-BBS network specification (AgentNet)
- **Bravo** — BBS implementation; a Charlie workspace and an Alpha node
- **Charlie** — this document; the connector protocol
- **Foxtrot** — the unified vision encompassing A, B, C

---

## Status

Version 0.1 — internal draft. Frozen for initial implementation.  
Reference testbed: Tango2 stand (private).

## License

To be determined upon public release.
