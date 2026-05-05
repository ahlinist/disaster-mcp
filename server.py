"""
Disaster Data MCP Server — Streamable HTTP Transport
Implements the Model Context Protocol over HTTP using only stdlib + pandas.
No external mcp SDK required; works with Python 3.9+.

Usage:
    python server.py [--port 8000]

Connect MCP Inspector (streamable HTTP) to:
    http://localhost:8000/mcp
"""

import argparse
import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_service import (
    compute_statistics,
    df_to_records,
    filter_data,
    get_filter_options,
    load_data,
)

# ── Tool definitions (JSON Schema) ────────────────────────────────────────────

TOOLS = [
    {
        "name": "query_disasters",
        "description": (
            "Query EM-DAT disaster events with optional filters. "
            "Returns paginated records. Use limit/offset to walk through large result sets."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "country":           {"type": "string",  "description": "Country name, partial match (e.g. 'India')"},
                "disaster_type":     {"type": "string",  "description": "Disaster type (e.g. 'Flood', 'Earthquake', 'Storm')"},
                "year_from":         {"type": "integer", "description": "Start year, inclusive"},
                "year_to":           {"type": "integer", "description": "End year, inclusive"},
                "continent":         {"type": "string",  "description": "Continent (Africa/Americas/Asia/Europe/Oceania)"},
                "disaster_subgroup": {"type": "string",  "description": "Subgroup (e.g. 'Hydrological', 'Geophysical')"},
                "limit":             {"type": "integer", "default": 20,  "minimum": 1, "maximum": 200},
                "offset":            {"type": "integer", "default": 0,   "minimum": 0},
            },
        },
    },
    {
        "name": "get_statistics",
        "description": (
            "Aggregated statistics for a filtered subset: total events, deaths, "
            "affected, damages, breakdown by type/continent, and yearly counts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "country":       {"type": "string"},
                "disaster_type": {"type": "string"},
                "year_from":     {"type": "integer"},
                "year_to":       {"type": "integer"},
                "continent":     {"type": "string"},
            },
        },
    },
    {
        "name": "get_top_disasters",
        "description": "Top N worst disaster events ranked by deaths, affected, or damages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "metric":        {"type": "string",  "enum": ["deaths", "affected", "damages"], "default": "deaths"},
                "n":             {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
                "country":       {"type": "string"},
                "disaster_type": {"type": "string"},
                "year_from":     {"type": "integer"},
                "year_to":       {"type": "integer"},
                "continent":     {"type": "string"},
            },
        },
    },
    {
        "name": "list_filter_options",
        "description": (
            "Return all valid filter values: countries, disaster types, subgroups, "
            "continents, and year range. Call this first to discover available filters."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_country_summary",
        "description": "Full stats for a specific country: events, deaths, affected, damages, timeline.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "country": {"type": "string", "description": "Country name (partial match)"},
            },
            "required": ["country"],
        },
    },
    {
        "name": "search_events",
        "description": "Free-text search across event names, locations, and country names.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":  {"type": "string"},
                "limit":  {"type": "integer", "default": 20, "minimum": 1, "maximum": 200},
                "offset": {"type": "integer", "default": 0,  "minimum": 0},
            },
            "required": ["query"],
        },
    },
]

# ── Tool dispatch ─────────────────────────────────────────────────────────────

def _int(val, default=None):
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def call_tool(name: str, args: dict) -> str:
    if name == "query_disasters":
        limit  = max(1, min(200, _int(args.get("limit"),  20)))
        offset = max(0, _int(args.get("offset"), 0))
        df = filter_data(
            country=args.get("country"),
            disaster_type=args.get("disaster_type"),
            year_from=_int(args.get("year_from")),
            year_to=_int(args.get("year_to")),
            continent=args.get("continent"),
            disaster_subgroup=args.get("disaster_subgroup"),
        )
        return json.dumps({
            "total_count": len(df),
            "offset": offset,
            "limit": limit,
            "records": df_to_records(df.iloc[offset: offset + limit]),
        }, default=str)

    if name == "get_statistics":
        df = filter_data(
            country=args.get("country"),
            disaster_type=args.get("disaster_type"),
            year_from=_int(args.get("year_from")),
            year_to=_int(args.get("year_to")),
            continent=args.get("continent"),
        )
        return json.dumps(compute_statistics(df), default=str)

    if name == "get_top_disasters":
        col_map = {
            "deaths":   "Total Deaths",
            "affected": "Total Affected",
            "damages":  "Total Damages ('000 US$)",
        }
        col = col_map.get(str(args.get("metric", "deaths")).lower(), "Total Deaths")
        n   = max(1, min(100, _int(args.get("n"), 10)))
        df  = filter_data(
            country=args.get("country"),
            disaster_type=args.get("disaster_type"),
            year_from=_int(args.get("year_from")),
            year_to=_int(args.get("year_to")),
            continent=args.get("continent"),
        )
        return json.dumps(
            {"metric": col, "top_n": n, "records": df_to_records(df.nlargest(n, col, keep="first"))},
            default=str,
        )

    if name == "list_filter_options":
        return json.dumps(get_filter_options())

    if name == "get_country_summary":
        country = args.get("country", "")
        df = filter_data(country=country)
        if df.empty:
            return json.dumps({"error": f"No records found for country matching '{country}'"})
        result = compute_statistics(df)
        result["matched_countries"] = sorted(df["Country"].dropna().unique().tolist())
        result["query"] = country
        return json.dumps(result, default=str)

    if name == "search_events":
        query  = args.get("query", "")
        limit  = max(1, min(200, _int(args.get("limit"),  20)))
        offset = max(0, _int(args.get("offset"), 0))
        df = filter_data(keyword=query)
        return json.dumps({
            "query": query,
            "total_count": len(df),
            "offset": offset,
            "limit": limit,
            "records": df_to_records(df.iloc[offset: offset + limit]),
        }, default=str)

    raise ValueError(f"Unknown tool: {name}")


# ── JSON-RPC message handler ──────────────────────────────────────────────────

def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_message(msg: dict):
    """Return a response dict, or None for notifications (no response needed)."""
    method   = msg.get("method", "")
    params   = msg.get("params") or {}
    req_id   = msg.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "disaster-data", "version": "1.0.0"},
            },
        }

    # Notifications — no response
    if method.startswith("notifications/"):
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        cursor = params.get("cursor")  # pagination — ignored (all tools fit in one page)
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments") or {}
        try:
            text = call_tool(tool_name, tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                },
            }
        except Exception as exc:
            return _error(req_id, -32000, str(exc))

    if req_id is not None:
        return _error(req_id, -32601, f"Method not found: {method}")
    return None


# ── HTTP handler ──────────────────────────────────────────────────────────────

_CORS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Accept, Mcp-Session-Id",
    "Access-Control-Expose-Headers": "Mcp-Session-Id",
}


class MCPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _cors(self):
        for k, v in _CORS.items():
            self.send_header(k, v)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path not in ("/mcp", "/mcp/", "/"):
            self._send_json(404, {"error": "Not found"})
            return
        info = {
            "server": "disaster-data MCP",
            "transport": "streamable-http",
            "mcp_endpoint": f"http://{self.headers.get('Host', 'localhost')}/mcp",
            "protocol_version": "2024-11-05",
            "tools": [t["name"] for t in TOOLS],
        }
        self._send_json(200, info)

    def do_POST(self):
        if self.path not in ("/mcp", "/mcp/"):
            self._send_json(404, {"error": "Not found"})
            return

        # Parse body
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw    = self.rfile.read(length)
            msg    = json.loads(raw)
        except Exception:
            self._send_json(400, _error(None, -32700, "Parse error"))
            return

        # Batch or single
        if isinstance(msg, list):
            responses = [r for r in (handle_message(m) for m in msg) if r is not None]
            if not responses:
                self._send_empty(202)
                return
            self._send_json(200, responses)
        else:
            result = handle_message(msg)
            if result is None:
                self._send_empty(202)
                return
            self._send_json(200, result)

    def _send_json(self, status: int, payload):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def log_message(self, fmt, *args):
        print(f"[MCP] {self.address_string()} {fmt % args}", flush=True)


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Disaster Data MCP Server")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    print("Loading dataset...", flush=True)
    load_data()
    print("Dataset loaded.", flush=True)

    server = _ThreadedHTTPServer((args.host, args.port), MCPHandler)
    print(f"\nDisaster MCP server running at http://localhost:{args.port}/mcp")
    print(f"MCP Inspector → Transport: Streamable HTTP → URL: http://localhost:{args.port}/mcp\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
