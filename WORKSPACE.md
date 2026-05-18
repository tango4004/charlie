# Charlie Workspace Specification

**Version:** 0.1-draft  
**Component:** Workspace (executor)

---

## Overview

A workspace is any service that receives work from the Charlie buffer, executes it, and returns results. Workspaces are independent of the Charlie bridge and of each other. They communicate exclusively through the buffer using the three-stream contract.

Workspace internals are not defined by Charlie. A workspace may be a bash executor, a BBS node, a SQL interface, an LLM, or any other service. The protocol does not distinguish between them.

---

## Required Interface

A conforming workspace must implement the following:

### 1. Accept work from stdin stream

The workspace polls or subscribes to the buffer's stdin stream for its workspace_id.

```
GET /stdin/{workspace_id}   → packet(s)
```

The workspace reads packets, reassembles chunks (by job_id + seq order), and processes the payload.

### 2. Write results to stdout stream

```
POST /stdout/{job_id}   body: Charlie packet
```

The workspace may write to stdout at any time during or after processing. Partial results are permitted and encouraged for long-running operations. The client will see them as they arrive.

### 3. Write errors to stderr stream

```
POST /stderr/{job_id}   body: Charlie packet
```

Errors may be written independently of stdout. Writing to stderr does not imply that stdout is finished.

### 4. Respond to the `"help"` stream (mandatory)

Every workspace with an address token **must** respond to `get(token, job_id, "help")`. Help is a stream like any other — the workspace writes its documentation to the `"help"` output channel in response to a help request. A workspace that does not implement the `"help"` stream is non-compliant.

The help response is a static Markdown document describing:
- What this workspace does
- Payload format expected in stdin (structure of the payload string)
- What stdout returns on success
- What stderr returns on error
- Available streams and their meaning
- Any limitations or constraints

---

## Packet Handling Rules

When creating response packets, the workspace must:

- Use the **same job_id** as the received request packet.
- Generate a **new unique packet_id** (if packet_id is implemented).
- Set **ts** to current UTC time.
- Set **version** to its supported protocol version.
- Set **routing** to the originating token/bridge identifier (for return routing).
- Set **seq** / **seq_total** according to response payload size.
- Set **payload** to the result content (opaque string).

The workspace must **not** modify the job_id under any circumstances.

---

## Payload Format

Charlie does not define payload format. Each workspace defines its own payload schema and documents it in its help text.

Recommended convention (not required):

```json
{
  "action": "string — what to do",
  "params": {}
}
```

Response payload convention:

```json
{
  "result": "...",
  "meta": {}
}
```

Plain text payloads are equally valid if documented.

---

## Lifecycle

```
buffer stdin  →  workspace receives packet(s)
                   │
                   ├── reassemble chunks (if seq_total > 1)
                   ├── parse payload
                   ├── execute
                   │     │
                   │     ├── write partial stdout (optional, streaming)
                   │     └── write final stdout
                   │
                   └── write stderr if error occurred
```

A workspace may:
- Write stdout multiple times (streaming partial results).
- Write stderr and stdout for the same job_id (e.g., warnings + result).
- Take arbitrarily long to process (TTL is enforced by the buffer, not the workspace).

A workspace must not:
- Hold packets without eventually writing to stdout or stderr.
- Modify packets received from stdin before processing.
- Write to another workspace's streams.

---

## Identity and Registration

Each workspace has a unique `workspace_id` assigned by the Allocator. The workspace_id is used by the buffer for stream routing.

Workspaces do not self-register. Registration is performed by a human operator or the Allocator. The workspace only needs to know its own workspace_id to poll the correct stdin stream.

---

## Example Workspaces

### Bash Connector

- **workspace_id:** `bash`
- **payload format:** `{"command": "shell command string"}`
- **stdout:** stdout of the shell command
- **stderr:** stderr of the shell command + exit code if non-zero

### BBS Connector (Bravo)

- **workspace_id:** `bbs`
- **payload format:** `{"action": "read|write", "to": "...", "text": "...", "after": 0}`
- **stdout:** BBS messages as JSON array
- **stderr:** connection errors, auth errors

---

## Compliance Checklist

A workspace is Charlie-compliant if it:

- [ ] Polls buffer stdin for its workspace_id
- [ ] Reassembles chunked packets before processing
- [ ] Writes results to buffer stdout using correct job_id
- [ ] Writes errors to buffer stderr using correct job_id
- [ ] Responds to the `"help"` stream with Markdown documentation
- [ ] Does not modify received job_id
- [ ] Does not interpret packet fields other than payload
