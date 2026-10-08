---
name: course-recap
description: Reusable playbook for extracting high-yield technical concepts from course slide decks and generating consistent structured markdown recaps with Mermaid diagrams.
---

# Course Recap Skill Playbook

Use this skill whenever you need to process a slide deck (PDF format) and generate a comprehensive, highly structured course study guide and visual architecture.

## Workflow

```
[PDF Slides] -> [Call MCP extract_pdf_slides] -> [Distill Concepts] -> [Generate Mermaid Diagram] -> [Invoke Sub-agent @recap-reviewer] -> [Emit Final Recap]
```

---

## 1. Concept Extraction Guidelines

When reading extracted slide data from `extract_pdf_slides`:
1. **Identify the Core Objective:** What is the one thing a student must be able to accomplish after this lecture?
2. **Filter Out Slide Noise:** Ignore boilerplate slides (title cards, Q&A slides, duplicate logos/watermarks).
3. **Capture Commands & Code:** Keep exact CLI commands, parameters, configuration keys, and error mitigation advice intact.
4. **Link to Slides:** For each key concept, cite the source slide number(s) (e.g. `[Slide 2]`, `[Slides 5-7]`) for provenance.

---

## 2. Diagram Generation Rules (Mermaid.js)

To produce clean, error-free diagrams that render across GitHub, IDEs, and browser viewers:
- **Choose Diagram Type:**
  - For progressive workflows / pipelines / installation: use `flowchart TD` or `flowchart LR`.
  - For mental models / taxonomies: use `mindmap` or `classDiagram`.
- **Node Escaping:** Always wrap node labels in double quotes if they contain punctuation, parentheses, or spaces:
  ```mermaid
  flowchart TD
      A["Step 1: Install Package"] --> B["Step 2: Configure Keys"]
  ```
- **Clarity over Complexity:** Limit nodes to 7–15 meaningful entities.
- **Styling:** Use meaningful node IDs (`install`, `config`, `execute`) instead of random letters.

---

## 3. Standard Recap Output Template

Every generated recap must adhere to this exact 5-section layout:

```markdown
# 📚 Course Recap: [Lecture / Deck Title]

> **Source:** `[Filename]` | **Total Slides:** `[N]` | **Audited by:** `@recap-reviewer`

---

## 🎯 1. Executive Summary
- Brief 2-3 sentence distillation of what was covered and why it matters.

---

## 📊 2. Visual Architecture & Workflow

\`\`\`mermaid
flowchart TD
    ... [Mermaid Diagram] ...
\`\`\`

---

## 🧩 3. Core Concept Architecture Matrix

| Concept / Tool | Source Slides | Summary & Purpose | Critical Caveat / Gotcha |
| :--- | :--- | :--- | :--- |
| Concept A | Slide 1-2 | Description | Common mistake to avoid |
| Concept B | Slide 3 | Description | Configuration tip |

---

## 🛠️ 4. Step-by-Step Technical Guide & Command Reference
- Concrete steps, code snippets, or configuration files explained in the slides.
- Exact syntax blocks with copy-pasteable commands.

---

## 💡 5. High-Yield Takeaways & Quick Review
- 4-5 bulleted rapid-fire memory anchors for exam or assignment preparation.
```
