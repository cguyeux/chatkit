# app/bank.py
"""Validated question bank, served WITHOUT any LLM call.

Flow: `generate_bank.py` (offline) asks the model for candidate questions per
notion and writes a spreadsheet for the trainers; they mark each row
« validé » / « rejeté » and fix wording; `import_bank.py` turns the reviewed
sheet into question_bank.json (bundled in the image) and/or the shared store
key bank/questions.json (hot-updatable without a rebuild). At runtime the
tutor draws from the validated pool for a notion when it holds enough
questions, and only falls back to live generation otherwise. Every question
served from the bank is instant, free and already reviewed."""
from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_DIR = Path(__file__).resolve().parent
BUNDLED_BANK = APP_DIR / os.getenv("QUESTION_BANK_FILE", "question_bank.json")
STORE_KEY = "bank/questions.json"
VALID_STATUSES = {"validé", "valide", "validated", "ok", "oui", "yes"}


def _load_bundled() -> List[Dict[str, Any]]:
    try:
        data = json.loads(BUNDLED_BANK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [q for q in data if isinstance(q, dict)]


class QuestionBank:
    def __init__(self, store: Any = None) -> None:
        self._store = store
        self._questions: Dict[str, Dict[str, Any]] = {}
        for q in _load_bundled():
            self._add(q)
        if store is not None:
            for q in store.get_json(STORE_KEY, []) or []:
                if isinstance(q, dict):
                    self._add(q)

    def _add(self, q: Dict[str, Any]) -> None:
        status = str(q.get("status") or "").strip().lower()
        if status and status not in VALID_STATUSES:
            return
        qid = str(q.get("id") or "").strip()
        kc_id = str(q.get("kc_id") or "").strip()
        choices = q.get("choices")
        if not qid or not kc_id or not isinstance(choices, list) or len(choices) != 4:
            return
        if str(q.get("answer") or "").upper() not in {"A", "B", "C", "D"}:
            return
        self._questions[qid] = dict(q)

    # ---- queries ---------------------------------------------------------
    def count(self, kc_id: str) -> int:
        return sum(1 for q in self._questions.values() if q.get("kc_id") == kc_id)

    def all_for(self, kc_id: str) -> List[Dict[str, Any]]:
        return [dict(q) for q in self._questions.values() if q.get("kc_id") == kc_id]

    def draw(
        self,
        kc_id: str,
        n: int,
        *,
        exclude_ids: Optional[set[str]] = None,
        difficulty: Optional[str] = None,
        rng: Optional[random.Random] = None,
    ) -> List[Dict[str, Any]]:
        """Up to n validated questions for the notion, unseen ones first,
        preferring the requested difficulty when the row carries one."""
        rng = rng or random.Random()
        pool = self.all_for(kc_id)
        if not pool:
            return []
        exclude_ids = exclude_ids or set()
        fresh = [q for q in pool if q["id"] not in exclude_ids]
        seen = [q for q in pool if q["id"] in exclude_ids]
        rng.shuffle(fresh)
        rng.shuffle(seen)
        if difficulty:
            fresh.sort(key=lambda q: 0 if str(q.get("difficulty") or "") == difficulty else 1)
        picked = (fresh + seen)[:n]
        out: List[Dict[str, Any]] = []
        for i, q in enumerate(picked, start=1):
            item = dict(q)
            item["number"] = i
            item["from_bank"] = True
            out.append(item)
        return out

    def stats(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for q in self._questions.values():
            out[q["kc_id"]] = out.get(q["kc_id"], 0) + 1
        return out
