# PDF2ITS: PDF-Grounded LLM Intelligent Tutoring System

PDF2ITS is a self-hosted OpenAI ChatKit application that transforms PDF instructional material into an adaptive Intelligent Tutoring System (ITS).

The system is not only a PDF chatbot. It uses a knowledge-component graph, diagnostic screening, adaptive micro-lessons, adaptive QCM practice, feedback, remediation, mastery tracking, progress visualization, and visual symbol question answering.

## What It Does

```text
PDF course material
-> KC graph
-> diagnostic QCM
-> learner profile
-> adaptive micro-lesson
-> adaptive practice QCM
-> feedback and remediation
-> mastery tracking
-> next KC / module checkpoint
```

## Features

- PDF-grounded generation with OpenAI file search.
- KC-based course navigation using `server/app/kc_graph1.json`.
- Diagnostic QCM for learner-level estimation.
- Adaptive micro-lessons based on learner state.
- Adaptive QCM length based on KC targets, lesson content, mistakes, attempts, and difficulty.
- Cumulative practice with current KC plus previous KCs.
- Mistake explanation and misconception tracking.
- Hint ladder for remediation.
- KC and module mastery tracking.
- Radar progress visualization.
- Image upload for symbol interpretation.
- Follow-up visual questions using the same uploaded image.
- Evidence logging in JSONL.
- Benchmark runner for automatic ITS behavior checks.
- Learner guide available in chat and as a markdown document.

## Architecture

```text
web/
  Next.js frontend with @openai/chatkit-react

server/
  FastAPI backend

server/app/chatkit_server.py
  ChatKit server adapter, widget rendering, QCM submit handling, image conversion

server/app/orchestrator.py
  ITS workflow, agents, learner model, pedagogical controller

server/app/data_store.py
  In-memory threads/messages and local image attachment storage

server/app/widgets/
  ChatKit widgets for QCM, study cards, maps, Plotly, and radar

server/app/benchmark_runner.py
  Automatic benchmark using evidence_log.jsonl

docs/learner_guide.md
  Learner-facing usage guide
```

## Main Agents

- `DiagnosticQcmAgent`: creates the global diagnostic QCM.
- `KcEssentialTargetAgent`: extracts assessable KC targets from the PDF.
- `MicroLessonAgent`: creates adaptive PDF-grounded micro-lessons.
- `PracticeQcmAgent`: creates and repairs adaptive practice QCMs.
- `ExplainMistakeAgent`: explains wrong answers.
- `LearnerQuestionAgent`: answers text questions during lessons.
- `VisualQuestionAgent`: answers questions about uploaded symbol images.
- `TutorDecisionPolicy`: decides validate, retry, remediate, hint, or next.
- `MisconceptionTracker`: records simple misconception evidence from wrong answers.

## Requirements

- Python 3.10+
- Node.js 18+
- OpenAI API key
- OpenAI vector store containing the instructional PDF

Backend dependencies are listed in:

```text
server/requirements.txt
```

Frontend dependencies are listed in:

```text
web/package.json
```

## Configuration

Set environment variables before running the backend:

```powershell
$env:OPENAI_API_KEY="sk-..."
$env:PYTHONPATH="server"
```

Optional:

```powershell
$env:VECTOR_STORE_ID="vs_..."
$env:PUBLIC_BASE_URL="http://127.0.0.1:8000"
```

If `VECTOR_STORE_ID` is not provided, the default value in `server/app/orchestrator.py` is used.

## Installation

Backend:

```powershell
cd server
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd ..
```

Frontend:

```powershell
cd web
cmd.exe /c npm install
cd ..
```

## Run Locally

Backend:

```powershell
$env:PYTHONPATH="server"
server\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd web
cmd.exe /c npm run dev
```

Open:

```text
http://localhost:3000
```

If port `3000` is busy, Next.js may use another port such as `3001`.

## Learner Commands

```text
help
aide
start diagnostic
practice
hint
next
radar
clear image
```

Typical learner workflow:

```text
start diagnostic
-> answer diagnostic QCM
-> read micro-lesson
-> ask questions if needed
-> practice
-> answer adaptive QCM
-> read feedback / use hint if needed
-> retry practice or type next
-> radar
```

## Image Upload

The frontend enables ChatKit attachments with a two-phase upload strategy.

Uploaded images are stored locally in:

```text
server/app/uploads/
```

Example:

```text
Upload a symbol image
Ask: What does this symbol mean?
Ask: What about the color?
Ask: What about the form?
Type: clear image
```

The same image is reused for follow-up visual questions until `clear image` is used.

## Learner Guide

The learner guide is available at:

```text
docs/learner_guide.md
```

When the backend is running:

```text
http://127.0.0.1:8000/docs/learner_guide.md
```

The chat also supports:

```text
help
aide
guide
```

## Benchmark

Run the automatic ITS benchmark:

```powershell
server\.venv\Scripts\python.exe server/app/benchmark_runner.py
```

JSON output:

```powershell
server\.venv\Scripts\python.exe server/app/benchmark_runner.py --json
```

The benchmark reads:

```text
server/app/evidence_log.jsonl
```

It checks:

- diagnostic screening role
- diagnostic mastery cap
- adaptive practice length
- essential target coverage
- cumulative practice
- tutor decision consistency
- module checkpoint policy
- lesson and practice grounding

## Evidence Logs

The system records tutoring events in:

```text
server/app/evidence_log.jsonl
```

Examples of logged events:

- `diagnostic_started`
- `diagnostic_submitted`
- `micro_lesson_generated`
- `practice_started`
- `practice_submitted`
- `learner_question_answered`
- `visual_question_answered`
- `module_checkpoint_started`
- `module_checkpoint_submitted`

## Research Framing

PDF2ITS can be described as:

```text
A PDF-grounded LLM Intelligent Tutoring System that converts instructional material into KC-based adaptive tutoring workflows.
```

The central contribution is the orchestration layer that connects:

```text
PDF grounding
KC graph navigation
learner-state tracking
tutor decision policy
adaptive lessons
adaptive practice
feedback and remediation
mastery tracking
```

## Repository Hygiene

For a public GitHub repository, avoid committing:

- API keys or `.env` files
- runtime uploads in `server/app/uploads/`
- local logs if they contain private learner data
- generated `.next/` build artifacts
