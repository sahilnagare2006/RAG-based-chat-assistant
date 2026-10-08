#!/usr/bin/env bash
# start_ui.sh — Starts the Course Recap Generator interactive Web UI

cd "$(dirname "$0")"
PORT=5050

echo "=========================================================="
echo "⚡ Launching Course Recap Generator Web Dashboard"
echo "   Harness: OpenCode CLI (v2.0.20)"
echo "   MCP Server: pdf-slides-mcp"
echo "   Sub-Agent: @recap-reviewer"
echo "   URL: http://127.0.0.1:${PORT}"
echo "=========================================================="

./.venv/bin/python web/server.py
