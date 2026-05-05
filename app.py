"""
Disaster Data MCP endpoint deployed via Streamlit.

Streamlit is used purely as the deployment platform. This script injects
an /mcp route directly into Streamlit's Tornado 6 wildcard_router so the
endpoint is reachable on the same port/URL as the Streamlit app.

Connect MCP Inspector (Streamable HTTP):
  Local:   http://localhost:8501/mcp
  Cloud:   https://<your-app>.streamlit.app/mcp

NOTE: Visit the Streamlit URL in a browser once before connecting MCP
Inspector. The route injection runs on first browser connection.
"""

import gc
import json
import os
import sys

import streamlit as st
import tornado.routing
import tornado.web

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import TOOLS, handle_message
from data_service import load_data


# ── MCP Tornado request handler ───────────────────────────────────────────────

class _MCPHandler(tornado.web.RequestHandler):
    def check_xsrf_cookie(self):
        # MCP clients send no XSRF token — skip Tornado's built-in check
        pass

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type, Accept, Mcp-Session-Id")
        self.set_header("Access-Control-Expose-Headers", "Mcp-Session-Id")

    def options(self):
        self.set_status(204)

    def get(self):
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({
            "server": "disaster-data MCP",
            "transport": "streamable-http",
            "tools": [t["name"] for t in TOOLS],
        }))

    def post(self):
        try:
            msg = json.loads(self.request.body)
        except Exception:
            self.set_status(400)
            self.write('{"error":"parse error"}')
            return

        is_batch = isinstance(msg, list)
        responses = [
            r for r in (handle_message(m) for m in (msg if is_batch else [msg]))
            if r is not None
        ]

        if not responses:
            self.set_status(202)
            return

        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(responses if is_batch else responses[0], default=str))


# ── Inject /mcp into Streamlit's Tornado 6 wildcard_router ───────────────────

@st.cache_resource
def _setup() -> dict:
    """Load data and inject /mcp into Tornado. Runs once per server process."""
    load_data()

    try:
        # Find the tornado.web.Application Streamlit is running on
        tornado_app = next(
            (obj for obj in gc.get_objects() if type(obj) is tornado.web.Application),
            None,
        )
        if tornado_app is None:
            return {"ok": False, "error": "Tornado Application not found in process heap"}

        # Tornado 6 uses wildcard_router.rules (not app.handlers as in Tornado 5)
        rules = tornado_app.wildcard_router.rules

        # Guard against double-injection on hot-reload
        if any(getattr(r, "target", None) is _MCPHandler for r in rules):
            return {"ok": True, "note": "already injected"}

        # Insert at position 0 so /mcp matches before Streamlit's /(.*) catch-all
        new_rule = tornado.routing.Rule(
            tornado.routing.PathMatches(r"/mcp/?"),
            _MCPHandler,
        )
        rules.insert(0, new_rule)

        return {"ok": True, "total_rules": len(rules)}

    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Minimal status page ───────────────────────────────────────────────────────

st.set_page_config(page_title="Disaster MCP", page_icon="🌍", layout="centered")
st.title("🌍 Disaster Data MCP")

result = _setup()

if result["ok"]:
    st.success("MCP endpoint is live at **/mcp**")
    st.code(
        "Transport : Streamable HTTP\n"
        "Local     : http://localhost:8501/mcp\n"
        "Cloud     : https://<your-app>.streamlit.app/mcp"
    )
else:
    st.error(f"Setup failed: {result['error']}")
    st.stop()

st.divider()
st.subheader("Available tools")
for t in TOOLS:
    st.markdown(f"**`{t['name']}`** — {t['description'].split(chr(10))[0]}")
