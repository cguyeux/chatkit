# ChatKit Advanced Self-Hosted Integration Demo

This project shows how to run an OpenAI ChatKit experience with your own backend orchestration layer and custom widgets.

## Architecture

- `web/`: Next.js frontend with `@openai/chatkit-react`.
- `server/`: FastAPI backend hosting the ChatKit endpoint.
- `server/app/orchestrator.py`: Multi-agent workflow and learning logic.
- `server/app/widgets/`: Widget templates and Python builders (`qcm`, `study`, `map`, `plotly`, `radar`).
- `server/app/data_store.py`: In-memory thread/message store keyed by `userId`.

## Request Flow

1. Frontend generates/persists a stable `userId` in local storage.
2. Frontend sends ChatKit requests to `http://127.0.0.1:8000/chatkit` with `userId` header.
3. FastAPI forwards payload to `MyChatKitServer`.
4. `MyChatKitServer` loads thread history, calls `Orchestrator.handle(...)`, and emits:
   - assistant text, or
   - widget payloads (`qcm`, `study`, `map`, `plotly`, `radar`).
5. Frontend listens to widget actions:
   - `qcm.submit` goes to backend for evaluation/progression.
   - `map.show_inline`, `report.open`, `radar.click` are handled client-side in the right pane.

## Prerequisites

- Python 3.10+
- Node.js 18+
- `OPENAI_API_KEY` environment variable
- Optional: `VECTOR_STORE_ID` if you use file search in agents

## Run Locally

### Backend (PowerShell)

```powershell
cd server
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:OPENAI_API_KEY="sk-..."
uvicorn app.main:app --reload --port 8000
```

### Frontend (new terminal)

```powershell
cd web
npm install
npm run dev
```

Open `http://localhost:3000`.

## Common Commands in Chat

- `start diagnostic`
- `practice`
- `next`
- `radar`
- Answer quiz in widget submit, or text format like: `1A 2C 3B`

## Notes

- Current `MyDataStore` is in-memory only. Restarting backend resets history.
- Attachment persistence is not fully implemented by default in `data_store.py`.
- For production, replace `domainKey` and register your domain in OpenAI allowlist settings.

## Push This Project to GitHub (`helmi1105/chatkit.git`)

Run these commands from the project root:

```powershell
git init
git add .
git commit -m "Initial commit: ChatKit advanced integration demo"
git branch -M main
git remote add origin https://github.com/helmi1105/chatkit.git
git push -u origin main
```

If `origin` already exists:

```powershell
git remote set-url origin https://github.com/helmi1105/chatkit.git
git push -u origin main
```

If GitHub rejects push because remote already has commits:

```powershell
git pull origin main --rebase
git push -u origin main
```
