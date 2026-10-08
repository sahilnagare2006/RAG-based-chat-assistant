#!/usr/bin/env python3
"""
generate_sample_deck.py
Generates a realistic course slide deck PDF for Day 6: AI Coding Techniques.
"""

import os
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from reportlab.lib import colors

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Day6_AI_Coding_Techniques_Slides.pdf")

SLIDES = [
    {
        "title": "Day 6: Building End-to-End Projects Using an Agent Harness",
        "subtitle": "AI Coding Techniques · deboistech",
        "bullets": [
            "Moving beyond simple code completion to autonomous agent orchestration",
            "Core components: Planning, Tools (MCP), Sub-Agents, Custom Skills",
            "Constraint: Single clean pass execution to keep token consumption light"
        ]
    },
    {
        "title": "Phase 1: The Planning Phase & Harness Modes",
        "subtitle": "Why Planning Saves Re-work",
        "bullets": [
            "Never jump straight into unstructured code edits",
            "Use Plan Mode or brainstorming skills before touching files",
            "Key decisions: Extraction strategy, summary structure, diagram format",
            "Rule: A 10-minute structured plan avoids 2 hours of refactoring later"
        ]
    },
    {
        "title": "Phase 2: Model Context Protocol (MCP) Integration",
        "subtitle": "Connecting the Harness to the Real World",
        "bullets": [
            "MCP provides standardized stdio/HTTP interfaces for tool augmentation",
            "Enables harnesses to call external parsers (e.g., PDF extraction, diagram validation)",
            "Command: opencode mcp add <name> -- <command>",
            "Anti-pattern: Do not bolt on fake MCP tools; solve a real workflow need"
        ]
    },
    {
        "title": "Phase 3: Multi-Agent Architecture & Sub-Agents",
        "subtitle": "Role Specialization & Isolated Context",
        "bullets": [
            "Primary Agent (Orchestrator): Handles main workflow, calls MCP tools, synthesizes recap",
            "Sub-Agent (Reviewer): Dedicated QA auditor with an independent checklist",
            "Defined via opencode.json or .opencode/agents/recap-reviewer.md",
            "Verifies factual fidelity against source slides and checks diagram syntax"
        ]
    },
    {
        "title": "Phase 4: Custom Agent Skills",
        "subtitle": "Teaching Your Harness Reusable Playbooks",
        "bullets": [
            "Skills provide procedural knowledge and formatting rules across projects",
            "Stored in .opencode/skills/<skill-name>/SKILL.md",
            "Structure: YAML frontmatter + concept distillation rules + Mermaid diagram styling",
            "Allows any future slide deck to be processed with identical high quality"
        ]
    },
    {
        "title": "Summary & Best Practices for Production Agents",
        "subtitle": "Day 6 Key Takeaways",
        "bullets": [
            "Keep credit usage light: Input -> MCP Extraction -> Summarize -> Review -> Output",
            "Prefer declarative Mermaid diagrams (flowchart TD, mindmap) over complex images",
            "Always include human-in-the-loop verification and testable artifact outputs"
        ]
    }
]

def create_slides(filename):
    c = canvas.Canvas(filename, pagesize=landscape(letter))
    width, height = landscape(letter)

    for i, slide in enumerate(SLIDES):
        # Background
        c.setFillColor(colors.HexColor("#0f172a"))
        c.rect(0, 0, width, height, fill=1, stroke=0)

        # Header bar
        c.setFillColor(colors.HexColor("#38bdf8"))
        c.rect(40, height - 60, width - 80, 4, fill=1, stroke=0)

        # Slide Number
        c.setFillColor(colors.HexColor("#94a3b8"))
        c.setFont("Helvetica-Bold", 12)
        c.drawRightString(width - 50, 40, f"Slide {i+1} of {len(SLIDES)}")

        # Title
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 26)
        c.drawString(50, height - 100, slide["title"])

        # Subtitle
        c.setFillColor(colors.HexColor("#38bdf8"))
        c.setFont("Helvetica-Bold", 15)
        c.drawString(50, height - 130, slide["subtitle"])

        # Bullets
        c.setFillColor(colors.HexColor("#e2e8f0"))
        c.setFont("Helvetica", 16)
        y = height - 180
        for b in slide["bullets"]:
            c.circle(65, y + 5, 3, fill=1, stroke=0)
            c.drawString(80, y, b)
            y -= 42

        c.showPage()

    c.save()
    print(f"Generated sample course slides at: {filename}")

if __name__ == "__main__":
    create_slides(OUT_PATH)
