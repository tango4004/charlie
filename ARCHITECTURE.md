# Charlie Architecture

**Version:** 0.2-draft

---

## Two Types of Components

Charlie distinguishes two fundamentally different component types:

### Internal Cubes (Library Primitives)

Protocol-level building blocks. Interface fixed in manifest. No external dependencies.

| Cube | Inputs | Outputs | Role |
|------|--------|---------|------|
| generator | 0 | 1 | Test packet source |
| terminator | 1 | 0 | Test packet sink / logger |
| switch | 1 | N | Route by `routing` field (hashmap) |
| merger | N | 1 | Combine N streams, passthrough |
| echo | 1 | 1 | Swap `routing`↔`reply_to` (workspace stub) |

Internal cubes are protocol primitives. They know nothing about what agents or workspaces do — only about moving and routing packets.

### External Connectors (Plugins)

Defined by the connector author. The schema treats them as endpoints and wires the required number of pipes to them.

| Connector | Description |
|-----------|-------------|
| mcp_connector | LLM agent interface (Claude, GPT, Grok...) |
| bash_workspace | Shell command executor |
| bbs_workspace | BBS node (Bravo) |
| *any* | Any service that speaks Charlie packet format |

The connector author declares:
- How many input channels are needed and what they carry
- How many output channels are needed and what they carry
- A help document describing the interface

The schema assembles them as endpoints. It does not prescribe internals.

---

## Schema as Assembly Point

The schema is the single source of truth for a running deployment. It describes:
- Which internal cubes to instantiate
- Which external connectors to wire in
- How all channels connect (pipe topology)
- Routing tables for switch cubes

```yaml
version: "0.1"
pipes_dir: /tmp/charlie_pipes

# Internal cubes
pipeline:
  - id: switch_in
    from: library/switch
    routing:
      ws_bash: "{pipes_dir}/ws_bash.stdin"
      ws_bbs:  "{pipes_dir}/ws_bbs.stdin"

  - id: merger_out
    from: library/merger

  - id: switch_out
    from: library/switch
    routing:
      t_doo: "{pipes_dir}/t_doo.stdin"
      t_gpt: "{pipes_dir}/t_gpt.stdin"

# External connectors
connectors:
  - id: t_doo
    type: mcp
    channels:
      out: [{name: to_bash, doc: "run bash command"},
            {name: to_bbs,  doc: "post to BBS"}]
      in:  [{name: results, doc: "workspace results"}]
    help: ./docs/t_doo_connector.md

  - id: ws_bash
    type: workspace
    channels:
      in:  [{name: commands, doc: "shell command string"}]
      out: [{name: stdout,   doc: "command output"},
            {name: stderr,   doc: "errors and exit code"}]
    help: ./docs/ws_bash.md
```

---

## Full Topology (3 clients, 3 workspaces)

```
MCP_doo ──out──┐                      ┌──in── MCP_doo
MCP_gpt ──out──┤──[merger_in]──[switch_in]    [switch_out]──[merger_out]──┤──in── MCP_gpt
MCP_grk ──out──┘       │                           │              └──in── MCP_grk
                        ├── ws_bash ───────────────┤
                        ├── ws_bbs  ───────────────┤
                        └── ws_sql  ───────────────┘
```

Packet flow:
1. MCP_doo sends packet: `{routing: "ws_bash", reply_to: "t_doo", payload: "ls -la"}`
2. merger_in: passthrough (no modification)
3. switch_in: reads `routing="ws_bash"` → routes to ws_bash pipe
4. ws_bash: executes, swaps fields → `{routing: "t_doo", reply_to: "ws_bash", payload: "..."}`
5. merger_out: passthrough
6. switch_out: reads `routing="t_doo"` → routes to MCP_doo pipe
7. MCP_doo: delivers to agent via `get_result()`

---

## Lifecycle

### Allocator (Control Plane)

Manages registries and generates the schema:

```
clients:    {t_doo, t_gpt, t_grk}   ← MCP connector tokens
workspaces: {ws_bash, ws_bbs, ws_sql} ← workspace tokens
```

Rules:
- Every token must exist before schema assembly
- Adding a client or workspace = update schema + warm restart
- Revoking = remove from schema + warm restart
- The schema is a materialization of allocator state

### Assembly (up)

```
charlie up schema.yaml [--cold|--warm]
```

Order (bottom-up):
1. Create named pipes (mkfifo)
2. Start workspace connectors
3. Start internal cubes (switch, merger)
4. Start MCP connectors (last — they open to agents)
5. Write state.json

### Disassembly (down)

```
charlie down [--cold|--warm]
```

Order (top-down):
1. HALT all instances (SIGUSR1 → wait ACK)
2. Stop MCP connectors
3. Stop internal cubes
4. Stop workspace connectors
5. Remove named pipes (cold) or preserve (warm)
6. Remove state.json

### Warm Restart (add/remove component)

```
charlie down --warm   # preserves unchanged instances and pipes
# update schema.yaml
charlie up --warm     # starts only new instances, rewires
```

---

## Manifest Format

Every internal cube has a `manifest.yaml`:

```yaml
id: switch
version: "0.2"
inputs:
  - name: stdin
    type: pipe
    count: 1
outputs:
  - name: dynamic
    type: pipe
    count: N        # determined by routing table at assembly
entry: switch.py
signals:
  halt:   SIGUSR1
  resume: SIGUSR2
  ack:    /tmp/charlie_halt_{id}
```

External connectors describe their channel requirements inline in the schema (see above).

---

## Stream Count

The 3-stream model (stdin/stdout/stderr) is a convention for workspace-style connectors following Unix semantics. It is not a protocol requirement.

Each connector defines its actual stream count in the schema. Examples:
- MCP connector: 1 in + 1 out (results only, no stderr needed)
- Bash workspace: 1 in + 2 out (stdout + stderr)
- Agent-to-agent link: 1 in + 1 out
- Streaming workspace: 1 in + N out (multiple result channels)

---

## Routing Model

Packets carry two address fields:

| Field | Direction | Value |
|-------|-----------|-------|
| `routing` | destination | workspace_id (inbound) / token (outbound) |
| `reply_to` | source | token (inbound) / workspace_id (outbound) |

The originator sets both fields. Internal cubes (merger, switch) do not modify them. The workspace swaps the fields in the response.

No shared route tables. No state in the routing layer.

---

## What the Schema Does Not Know

- Workspace internals (implementation language, logic)
- Connector internals (which LLM, which API)
- Payload semantics (opaque string, application-defined)
- Security policies (Allocator's domain)
