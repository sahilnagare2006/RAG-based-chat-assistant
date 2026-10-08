#!/usr/bin/env python3
"""
pdf_slides_mcp.py
Model Context Protocol (MCP) server for extracting and parsing PDF slide decks.

Supports:
1. Standard MCP stdio JSON-RPC protocol (for OpenCode / Claude Code / Codex).
2. Direct CLI invocation for standalone testing and scripts.

Tools provided:
- extract_pdf_slides: Extracts slide-by-slide text, titles, and bullets.
- get_slide_metadata: Returns deck page count, title, and metadata.
- validate_mermaid: Checks Mermaid syntax for common syntax bugs.
"""

import sys
import json
import os
import re
from typing import Dict, Any, List

try:
    import pypdf
except ImportError:
    pypdf = None


def clean_slide_text(text: str) -> str:
    """Removes repetitive watermarks, extra blank lines, and normalizes slide text."""
    if not text:
        return ""
    lines = text.splitlines()
    cleaned_lines = []
    watermarks = {"deboistech", "confidential", "draft", "copyright"}

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower() in watermarks:
            continue
        cleaned_lines.append(stripped)

    return "\n".join(cleaned_lines)


def parse_slide_content(page_text: str, slide_index: int) -> Dict[str, Any]:
    """Infers title and bullet points from slide text."""
    cleaned = clean_slide_text(page_text)
    raw_lines = [l.strip() for l in cleaned.splitlines() if l.strip()]

    # Filter out footer slide numbers like 'Slide 1 of 6'
    lines = [
        l for l in raw_lines
        if not re.match(r"^Slide\s+\d+(\s+of\s+\d+)?$", l, re.IGNORECASE)
    ]

    title = f"Slide {slide_index}"
    bullets = []

    if lines:
        # Find first line that looks like a title (not just numbers/symbols)
        for idx, candidate in enumerate(lines):
            if len(candidate) > 3 and not candidate.startswith("http"):
                title = candidate
                remaining_lines = lines[:idx] + lines[idx+1:]
                break
        else:
            title = lines[0]
            remaining_lines = lines[1:]
    else:
        remaining_lines = []

    for l in remaining_lines:
        # Strip bullet points
        cleaned_bullet = re.sub(r"^[\*\-\•\–\d+\.]\s+", "", l).strip()
        if cleaned_bullet:
            bullets.append(cleaned_bullet)

    return {
        "slide_index": slide_index,
        "title": title,
        "bullets": bullets,
        "cleaned_text": cleaned,
        "char_count": len(cleaned)
    }


def extract_pdf_slides_impl(pdf_path: str, max_slides: int = None) -> Dict[str, Any]:
    """Reads a PDF file and returns structured slide representations."""
    if not os.path.exists(pdf_path):
        return {"error": f"File not found: {pdf_path}"}

    if pypdf is None:
        return {"error": "pypdf library not installed. Please install via: pip install pypdf"}

    try:
        reader = pypdf.PdfReader(pdf_path)
        total_pages = len(reader.pages)
        limit = total_pages if max_slides is None else min(total_pages, max_slides)

        slides = []
        total_chars = 0

        for i in range(limit):
            page = reader.pages[i]
            raw_text = page.extract_text() or ""
            slide_data = parse_slide_content(raw_text, i + 1)
            slides.append(slide_data)
            total_chars += slide_data["char_count"]

        return {
            "success": True,
            "pdf_path": os.path.abspath(pdf_path),
            "filename": os.path.basename(pdf_path),
            "total_slides": total_pages,
            "processed_slides": len(slides),
            "total_characters": total_chars,
            "slides": slides
        }
    except Exception as e:
        return {"error": f"Failed to extract PDF: {str(e)}"}


def get_slide_metadata_impl(pdf_path: str) -> Dict[str, Any]:
    """Returns high-level metadata about the PDF slide deck."""
    if not os.path.exists(pdf_path):
        return {"error": f"File not found: {pdf_path}"}

    if pypdf is None:
        return {"error": "pypdf library not installed."}

    try:
        reader = pypdf.PdfReader(pdf_path)
        metadata = reader.metadata or {}
        outline = []
        try:
            raw_outline = reader.outline
            if raw_outline:
                for item in raw_outline:
                    if hasattr(item, "title"):
                        outline.append(str(item.title))
        except Exception:
            pass

        return {
            "success": True,
            "pdf_path": os.path.abspath(pdf_path),
            "filename": os.path.basename(pdf_path),
            "page_count": len(reader.pages),
            "title": str(metadata.get("/Title", "")),
            "author": str(metadata.get("/Author", "")),
            "creator": str(metadata.get("/Creator", "")),
            "outline": outline
        }
    except Exception as e:
        return {"error": f"Failed to read metadata: {str(e)}"}


def validate_mermaid_impl(mermaid_code: str) -> Dict[str, Any]:
    """Validates basic syntax and structure of a Mermaid diagram."""
    if not mermaid_code or not mermaid_code.strip():
        return {"valid": False, "error": "Empty mermaid code"}

    code = mermaid_code.strip()
    valid_starters = [
        "graph", "flowchart", "sequenceDiagram", "classDiagram",
        "stateDiagram", "erDiagram", "gantt", "pie", "mindmap", "timeline"
    ]

    first_line = code.splitlines()[0].strip()
    has_valid_starter = any(first_line.startswith(s) for s in valid_starters)

    issues = []
    if not has_valid_starter:
        issues.append(f"First line '{first_line}' does not match standard Mermaid diagram types ({', '.join(valid_starters)})")

    # Check for unescaped brackets in node labels like A[Some [text]]
    bracket_mismatch = code.count("[") != code.count("]")
    paren_mismatch = code.count("(") != code.count(")")
    brace_mismatch = code.count("{") != code.count("}")

    if bracket_mismatch:
        issues.append(f"Mismatched square brackets: [ {code.count('[')} vs ] {code.count(']')}")
    if paren_mismatch:
        issues.append(f"Mismatched parentheses: ( {code.count('(')} vs ) {code.count(')')}")
    if brace_mismatch:
        issues.append(f"Mismatched curly braces: {{ {code.count('{')} vs }} {code.count('}')}")

    return {
        "valid": len(issues) == 0,
        "type": first_line.split()[0] if has_valid_starter else "unknown",
        "line_count": len(code.splitlines()),
        "issues": issues
    }


# ==============================================================================
# Model Context Protocol (MCP) Stdio JSON-RPC Server
# ==============================================================================

TOOLS = [
    {
        "name": "extract_pdf_slides",
        "description": "Extract text, outline, titles, and clean bullet points from a PDF slide deck.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pdf_path": {
                    "type": "string",
                    "description": "Path to the slide deck PDF file"
                },
                "max_slides": {
                    "type": "integer",
                    "description": "Optional maximum number of slides to process"
                }
            },
            "required": ["pdf_path"]
        }
    },
    {
        "name": "get_slide_metadata",
        "description": "Extract high-level metadata (page count, title, outline) from a PDF slide deck.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pdf_path": {
                    "type": "string",
                    "description": "Path to the slide deck PDF file"
                }
            },
            "required": ["pdf_path"]
        }
    },
    {
        "name": "validate_mermaid",
        "description": "Validate syntax, diagram type, and bracket balance of a Mermaid diagram.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mermaid_code": {
                    "type": "string",
                    "description": "Mermaid diagram code string"
                }
            },
            "required": ["mermaid_code"]
        }
    }
]


def send_response(response: Dict[str, Any]):
    """Writes a JSON-RPC response to stdout followed by newline and flushes."""
    out = json.dumps(response)
    sys.stdout.write(out + "\n")
    sys.stdout.flush()


def run_mcp_server():
    """Runs the stdio event loop processing JSON-RPC messages."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params", {})

        if method == "initialize":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "pdf-slides-mcp",
                        "version": "1.0.0"
                    }
                }
            })
        elif method == "notifications/initialized":
            # Handshake notification, no response required
            pass
        elif method == "tools/list":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": TOOLS
                }
            })
        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})

            if tool_name == "extract_pdf_slides":
                res = extract_pdf_slides_impl(
                    args.get("pdf_path", ""),
                    args.get("max_slides")
                )
            elif tool_name == "get_slide_metadata":
                res = get_slide_metadata_impl(args.get("pdf_path", ""))
            elif tool_name == "validate_mermaid":
                res = validate_mermaid_impl(args.get("mermaid_code", ""))
            else:
                send_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {tool_name}"
                    }
                })
                continue

            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(res, indent=2)
                        }
                    ]
                }
            })
        elif method == "ping":
            send_response({"jsonrpc": "2.0", "id": msg_id, "result": {}})
        else:
            if msg_id is not None:
                send_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Unhandled method: {method}"
                    }
                })


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--extract" and len(sys.argv) > 2:
            res = extract_pdf_slides_impl(sys.argv[2])
            print(json.dumps(res, indent=2))
            return
        elif sys.argv[1] == "--metadata" and len(sys.argv) > 2:
            res = get_slide_metadata_impl(sys.argv[2])
            print(json.dumps(res, indent=2))
            return
        elif sys.argv[1] == "--test-mermaid":
            res = validate_mermaid_impl("flowchart TD\nA[Start] --> B[End]")
            print(json.dumps(res, indent=2))
            return
        elif sys.argv[1] in ["--help", "-h"]:
            print("pdf_slides_mcp: Model Context Protocol Server for Course Slides")
            print("Usage:")
            print("  python pdf_slides_mcp.py              # Run as stdio MCP server")
            print("  python pdf_slides_mcp.py --extract <path> # Extract PDF to JSON")
            print("  python pdf_slides_mcp.py --metadata <path> # Get PDF metadata")
            return

    run_mcp_server()


if __name__ == "__main__":
    main()
