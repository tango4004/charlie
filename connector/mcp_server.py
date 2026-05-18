#!/usr/bin/env python3
"""Charlie MCP streamable-HTTP server — protocol version 2025-03-26."""

import json
import logging
import os
import sys
import threading
import uuid

from flask import Flask, Response, request

LOG_FILE = "/tmp/mcp_server.log"
SPEC_FILE = "/home/arm2bash/charlie/SPEC.md"
PORT = 9001

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("charlie-mcp")

app = Flask(__name__)

# In-process job store: job_id -> {stream -> result_string}
_jobs = {}
_jobs_lock = threading.Lock()

TOOLS = [
    {
        "name": "call",
        "description": "Charlie protocol — submit work to a workspace. Returns a job_id immediately. Args: dst (workspace id, e.g. 'echo', 'bash', 'bbs'), task (stream name, e.g. 'stdin'), payload (string). Use get() to retrieve the result.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dst": {"type": "string", "description": "Destination agent name"},
                "task": {"type": "string", "description": "Task identifier"},
                "payload": {"type": "string", "description": "JSON-encoded payload string"},
            },
            "required": ["dst", "task", "payload"],
        },
    },
    {
        "name": "get",
        "description": "Charlie protocol — read output from a submitted job. Args: job_id (from call()), stream (e.g. 'stdout', 'stderr', 'help'). Returns empty string if not ready yet, poll again.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID returned by call"},
                "stream": {"type": "string", "description": "Stream identifier (e.g. stdout, stderr)"},
            },
            "required": ["job_id", "stream"],
        },
    },
    {
        "name": "get_help",
        "description": "Charlie protocol connector (charlie.tango4004.com). Returns documentation for the Charlie async agent connector protocol and available workspaces.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

HELP_FALLBACK = (
    "Charlie MCP Server (protocol 2025-03-26)\n"
    "\n"
    "Tools:\n"
    "  call(dst, task, payload) -> job_id\n"
    "    Dispatch a task to a destination agent.\n"
    "    dst: agent name (e.g. 'echo', 'sierra', 'arm2')\n"
    "    task: task identifier string\n"
    "    payload: JSON-encoded string payload\n"
    "\n"
    "  get(job_id, stream) -> payload\n"
    "    Poll for the result of a dispatched job.\n"
    "    stream: 'stdout' or 'stderr'\n"
    "\n"
    "  get_help() -> help text\n"
    "    Returns this help text.\n"
    "\n"
    "Supported destinations:\n"
    "  echo  — returns the payload unchanged (round-trip test)\n"
)


def handle_tool_call(name, args):
    log.info("tool_call: %s(%s)", name, args)

    if name == "call":
        dst = args.get("dst", "")
        payload = args.get("payload", "")
        job_id = str(uuid.uuid4())

        if dst == "echo":
            with _jobs_lock:
                _jobs[job_id] = {"stdout": payload, "stderr": ""}
            log.info("  -> echo job_id=%s payload=%r", job_id, payload)
        else:
            error_msg = f"error: no route to {dst}"
            with _jobs_lock:
                _jobs[job_id] = {"stdout": error_msg, "stderr": error_msg}
            log.info("  -> no route dst=%s job_id=%s", dst, job_id)

        return {"content": [{"type": "text", "text": job_id}]}

    elif name == "get":
        job_id = args.get("job_id", "")
        stream = args.get("stream", "stdout") or "stdout"

        with _jobs_lock:
            job = _jobs.get(job_id)

        if job is None:
            log.info("  -> job_id=%s not found", job_id)
            return {"content": [{"type": "text", "text": "error: job_id not found (call() first to get a fresh job_id)"}]}

        result = job.get(stream, "")
        log.info("  -> job_id=%s stream=%s result=%r", job_id, stream, result)
        return {"content": [{"type": "text", "text": result}]}

    elif name == "get_help":
        if os.path.exists(SPEC_FILE):
            with open(SPEC_FILE) as fh:
                text = fh.read()
        else:
            text = HELP_FALLBACK
        return {"content": [{"type": "text", "text": text}]}

    else:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
        }


def dispatch(req):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params") or {}

    log.info("dispatch: method=%s id=%s", method, req_id)

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "charlie-mcp", "version": "0.1.0"},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        result = handle_tool_call(params.get("name", ""), params.get("arguments") or {})
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    if method.startswith("notifications/"):
        log.info("notification %s — no response", method)
        return None

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


@app.route("/mcp", methods=["GET"])
def mcp_get():
    log.info("GET /mcp from %s", request.remote_addr)
    return Response("charlie-mcp ok\n", status=200, mimetype="text/plain")


@app.route("/mcp", methods=["POST"])
def mcp_post():
    body = request.get_data(as_text=True)
    log.info("POST /mcp from %s  body=%s", request.remote_addr, body[:300])

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        log.error("JSON parse error: %s", exc)
        err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        return Response(json.dumps(err), status=400, mimetype="application/json")

    if isinstance(data, list):
        responses = [r for r in (dispatch(req) for req in data) if r is not None]
        if not responses:
            return Response("", status=204)
        return Response(json.dumps(responses), status=200, mimetype="application/json")

    resp = dispatch(data)
    if resp is None:
        return Response("", status=204)
    return Response(json.dumps(resp), status=200, mimetype="application/json")


if __name__ == "__main__":
    log.info("Charlie MCP server starting on port %d", PORT)
    app.run(host="127.0.0.1", port=PORT, debug=False)
