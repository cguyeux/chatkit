"""End-to-end smoke test of the tutoring loop against the REAL orchestrator
and provider (no ChatKit transport): diagnostic, answer sheet, lesson, quiz,
feedback, hints, free question, progress. Run inside the API image:

  docker run --rm -e MISTRAL_API_KEY -e STATE_LOCAL_DIR=/tmp/state \
     -v $PWD/server:/work -w /work chatkit-api:dev python smoke_its.py

Prints each block's type and a preview; exits non-zero on any failure."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from types import SimpleNamespace

os.environ.setdefault("STATE_LOCAL_DIR", "/tmp/its-smoke-state")
os.environ.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:8000")

from app.orchestrator import Orchestrator  # noqa: E402


def ctx(user: str = "smoke-user", provider: str = "mistral") -> SimpleNamespace:
    return SimpleNamespace(thread=SimpleNamespace(id="thread-smoke"), store=None, request_context={"userId": user, "provider": provider, "api_key": None})


def show(label: str, blocks: list, t0: float) -> None:
    print(f"\n=== {label} ({time.time() - t0:.1f}s) ===")
    for b in blocks:
        kind = b.get("type")
        if kind == "text":
            print("[text]", b["text"][:600].replace("\n", " | "))
        elif kind == "qcm":
            qs = b["data"]["questions"]
            print(f"[qcm] {b['data']['title']} -> {len(qs)} questions")
            for q in qs[:3]:
                print("   ", q["id"], q["prompt"][:120], "|", " / ".join(c["label"][:40] for c in q["choices"]))
        elif kind == "widget":
            print("[widget]", b.get("title"), type(b["widget"]).__name__)
        else:
            print("[?]", str(b)[:200])


def progress(text: str, icon: str = "") -> None:
    print(f"   … {text}")


async def main() -> int:
    orch = Orchestrator()
    c = ctx()
    failures = 0

    t0 = time.time()
    blocks = await orch.handle_command("commencer le diagnostic", c, progress)
    show("diagnostic", blocks, t0)
    qcm = next((b for b in blocks if b.get("type") == "qcm"), None)
    if not qcm:
        print("FAIL: no diagnostic qcm")
        return 1
    sess = orch.load_session_sync("smoke-user")
    # answer: right on the first half, wrong on the second half
    answers = {}
    for num_s, q in sess.quiz_questions.items():
        num = int(num_s)
        answers[num] = q["answer"] if num % 2 == 1 else ("A" if q["answer"] != "A" else "B")
    t0 = time.time()
    blocks = await orch.handle_qcm_submit(answers, c, progress)
    show("diagnostic submitted", blocks, t0)
    if not any(b.get("type") == "widget" for b in blocks):
        print("FAIL: no correction widget"); failures += 1

    t0 = time.time()
    blocks = await orch.handle_command("quiz", c, progress)
    show("practice", blocks, t0)
    qcm = next((b for b in blocks if b.get("type") == "qcm"), None)
    if not qcm:
        print("FAIL: no practice qcm"); return 1
    sess = orch.load_session_sync("smoke-user")
    answers = {int(k): ("A" if q["answer"] != "A" else "B") for k, q in sess.quiz_questions.items()}  # all wrong
    t0 = time.time()
    blocks = await orch.handle_qcm_submit(answers, c, progress)
    show("practice failed", blocks, t0)

    t0 = time.time()
    blocks = await orch.handle_command("indice", c, progress)
    show("hint", blocks, t0)

    t0 = time.time()
    blocks = await orch.handle_command("quiz", c, progress)
    show("practice 2", blocks, t0)
    sess = orch.load_session_sync("smoke-user")
    answers = {int(k): q["answer"] for k, q in sess.quiz_questions.items()}  # all right
    t0 = time.time()
    blocks = await orch.handle_qcm_submit(answers, c, progress)
    show("practice passed", blocks, t0)

    t0 = time.time()
    blocks = await orch.handle_command("Que signifie un triangle ?", c, progress)
    show("free question", blocks, t0)

    t0 = time.time()
    blocks = await orch.handle_command("ma progression", c, progress)
    show("progress", blocks, t0)
    print("\nprogress_summary:", json.dumps(orch.progress_summary("smoke-user"), ensure_ascii=False))
    sess = orch.load_session_sync("smoke-user")
    print("budget used:", sess.llm_budget_used, "validated:", sess.validated_kc_ids, "current:", sess.current_kc_id)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
