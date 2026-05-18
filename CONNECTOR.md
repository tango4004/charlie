# Charlie Connector Specification

**Version:** 0.1-draft  
**Component:** MCP Bridge (Charlie Connector)

---

## Overview

The Charlie Connector is an MCP server that exposes the Charlie protocol to LLM agent clients. It is the only component visible to the outside world. All internal protocol details — packet format, streams, buffer interaction — are hidden behind four stable MCP tools.

The tool list **never changes**. Adding new workspace types or new output streams requires no client reconnection, no tool list refresh, no version negotiation on the client side.

---

## Protocol Primitives

The Charlie protocol has two primitives: `call` and `get`. Everything else — including help and discovery — is a stream.

---

## MCP Tools

### `call`

Single dispatch point for all workspace operations.

```
call(token: string, workspace_id: string, payload: string) → job_id: string
```

**Behavior:**
1. Validates token. Invalid token → error returned as plain text (not MCP error).
2. Checks that workspace_id is accessible for this token.
3. Generates a unique `job_id`.
4. Wraps payload in one or more Charlie packets (chunking if payload exceeds buffer limit).
5. Submits packet(s) to buffer stdin stream for the target workspace.
6. Returns `job_id` immediately, without waiting for workspace response.

**Chunking:** If payload length exceeds `MAX_PAYLOAD_BYTES` (implementation-defined, recommended 8KB), the bridge splits payload into chunks, assigns seq 0..N-1, seq_total=N, same job_id. All chunks are submitted atomically before returning job_id.

**Return value:** Plain text string containing the job_id. Example: `j_a3f92c10b4d1`

---

### `get`

Poll any output stream for a given job — including help and discovery.

```
get(token: string, job_id: string, stream: string) → text: string
```

`stream` names the channel to read: `"stdout"`, `"stderr"`, `"help"`, or any connector-defined stream name. Available streams for a workspace are declared in the schema and returned by the `"help"` stream.

**Behavior:**
1. Validates token.
2. Reads available packets from the named stream for this job_id.
3. Reassembles chunks in seq order if chunked.
4. Returns payload content. If no data is available yet: returns empty string.
5. Does not consume packets — repeated calls return accumulated output (append semantics).

**Streaming:** Workspaces may write partial results before completion. Each `get` call returns all content written to that stream so far.

**New streams:** If a workspace declares additional output channels (e.g. `"progress"`, `"metadata"`), clients read them with the same `get` call — no connector update required.

---

## Token Validation

The bridge validates tokens on every `call`, `get_result`, and `get_error`. Validation rules:

- Token must exist in the Allocator's registry.
- Token must be active (not revoked, not expired if TTL applies).
- For `call`: workspace_id must be in the token's allowed workspace list.
- For `get`: job_id must have been created by this token.

Token validation is synchronous and must complete before any buffer interaction.

---

## Error Handling

Errors are returned as plain text in the MCP tool result, not as MCP protocol errors. This ensures LLM clients can read and act on error descriptions naturally.

| Error | Returned in | Text |
|-------|------------|------|
| Invalid token | tool result | `error: invalid or expired token` |
| Unknown workspace | tool result | `error: workspace not found` |
| Buffer unavailable | tool result | `error: buffer unavailable` |
| Job not found | get | `error: unknown job_id` |
| Unknown stream | get | `error: unknown stream` |

---

## Syntactic Sugar (optional)

An MCP connector may expose `get_help` as a named tool for LLM client ergonomics:

```
get_help(token?: string, workspace_id?: string) → text: string
```

This is hardcoded sugar — a static bootstrap response with no token required, no job_id, no routing. It exists so that a freshly connected LLM agent sees a clearly named discovery tool without needing a token or a prior `call`. Clients that understand `get` need nothing extra. `get_help` is not a protocol primitive.

---

## Implementation Notes

- The connector must run as a streamable-http MCP server.
- Session IDs must be generated on `initialize` and returned in response headers.
- The connector must not block on workspace response. `call` returns job_id before workspace begins processing.
- Connector does not implement retry logic. Failed buffer submissions return an error immediately.
- `MAX_PAYLOAD_BYTES` should be documented per deployment. Clients that exceed this without knowing the limit will receive chunked job_ids transparently.
