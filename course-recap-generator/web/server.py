#!/usr/bin/env python3
"""
server.py
Web API Server for the Course Recap Generator.
Connects the web UI to the OpenCode agent harness, MCP server, and sub-agent workflow.
"""

import os
import sys
import json
import shutil
import subprocess
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import recap

app = FastAPI(title="Course Recap Generator API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = os.path.join(PROJECT_ROOT, "output", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


class ProcessSampleRequest(BaseModel):
    sample_id: str


def run_pipeline(pdf_path: str):
    """Executes the 4-stage single clean pass on the given PDF path."""
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file not found")

    # Step 1: Call MCP Server
    slide_res = recap.call_mcp_cli("--extract", pdf_path)
    if "error" in slide_res:
        raise HTTPException(status_code=400, detail=f"MCP Extraction failed: {slide_res['error']}")

    meta_res = recap.call_mcp_cli("--metadata", pdf_path)

    # Step 2: Apply Custom Skill Playbook
    primary_recap = recap.synthesize_primary_recap(slide_res, meta_res)

    # Step 3: Invoke Sub-Agent Audit
    audit_res = recap.invoke_recap_reviewer(primary_recap, slide_res.get("slides", []))

    # Step 4: Render Markdown and Output Artifacts
    markdown_recap = recap.render_markdown_recap(primary_recap, audit_res)

    # Persist to output folder
    out_dir = os.path.join(PROJECT_ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "recap.md"), "w", encoding="utf-8") as f:
        f.write(markdown_recap)

    with open(os.path.join(out_dir, "diagram.mmd"), "w", encoding="utf-8") as f:
        f.write(primary_recap["mermaid_code"])

    return {
        "success": True,
        "deck_title": primary_recap["deck_title"],
        "filename": primary_recap["filename"],
        "total_slides": primary_recap["total_slides"],
        "total_characters": slide_res.get("total_characters", 0),
        "topics": primary_recap["topics"],
        "commands": primary_recap["commands"],
        "takeaways": primary_recap.get("takeaways", []),
        "mermaid_code": primary_recap["mermaid_code"],
        "audit": audit_res,
        "markdown": markdown_recap,
        "pipeline_stages": [
            {
                "id": "mcp",
                "name": "MCP Server: pdf-slides-mcp",
                "status": "completed",
                "details": f"Extracted {slide_res.get('total_slides', 0)} slides ({slide_res.get('total_characters', 0)} chars)"
            },
            {
                "id": "skill",
                "name": "Custom Skill: course-recap Playbook",
                "status": "completed",
                "details": f"Synthesized {len(primary_recap['topics'])} topics & generated Mermaid architecture"
            },
            {
                "id": "subagent",
                "name": "Sub-Agent: @recap-reviewer Audit Pass",
                "status": "completed",
                "details": f"Status: {audit_res['status']} ({len(audit_res['findings'])} checks passed)"
            },
            {
                "id": "output",
                "name": "Output Generation: Single Clean Pass",
                "status": "completed",
                "details": "Generated recap.md, diagram.mmd, and interactive preview"
            }
        ]
    }


@app.get("/api/samples")
def get_samples():
    """Returns available course slide sample decks."""
    samples = []
    
    day6_sample = os.path.join(PROJECT_ROOT, "examples", "Day6_AI_Coding_Techniques_Slides.pdf")
    if os.path.exists(day6_sample):
        samples.append({
            "id": "day6",
            "title": "Day 6: AI Coding Techniques Slides",
            "description": "Building End-to-End Projects with Agent Harnesses (Planning, MCP, Sub-agents, Skills)",
            "slides_count": 6,
            "path": day6_sample
        })

    opencode_guide = "/Users/sahilnagare/Downloads/OpenCode_Windows_Student_Guide.pdf"
    if os.path.exists(opencode_guide):
        samples.append({
            "id": "opencode_guide",
            "title": "OpenCode Windows Student Setup Guide",
            "description": "Student guide for installing OpenCode CLI, configuring OpenRouter, and troubleshooting",
            "slides_count": 3,
            "path": opencode_guide
        })

    return {"samples": samples}


@app.post("/api/process-sample")
def process_sample(req: ProcessSampleRequest):
    """Processes a pre-packaged sample deck."""
    if req.sample_id == "day6":
        pdf_path = os.path.join(PROJECT_ROOT, "examples", "Day6_AI_Coding_Techniques_Slides.pdf")
    elif req.sample_id == "opencode_guide":
        pdf_path = "/Users/sahilnagare/Downloads/OpenCode_Windows_Student_Guide.pdf"
    else:
        raise HTTPException(status_code=400, detail="Unknown sample ID")

    return run_pipeline(pdf_path)


@app.post("/api/upload")
async def upload_and_process(file: UploadFile = File(...)):
    """Receives a user-uploaded PDF deck and runs the recap pipeline."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    dest_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return run_pipeline(dest_path)


@app.get("/api/health")
def health_check():
    """Health check and MCP status verification."""
    # Test MCP server
    mcp_test = recap.call_mcp_cli("--metadata", os.path.join(PROJECT_ROOT, "examples", "Day6_AI_Coding_Techniques_Slides.pdf"))
    mcp_ok = "error" not in mcp_test
    return {
        "status": "healthy",
        "harness": "OpenCode v2.0.20",
        "mcp_server": "pdf-slides-mcp",
        "mcp_connected": mcp_ok
    }


# Mount static files directory
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=5050, reload=True)
