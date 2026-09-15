# app/trainer_report.py
"""Trainer-side usage report from the evidence events (state store
events/<date>/*.json, or a local evidence_log.jsonl): learners, quizzes,
per-notion pass rates, the questions most often failed (bad question or hard
notion?), reported questions and thumbs feedback.

  python trainer_report.py                  # reads the state store (STATE_S3_* or STATE_LOCAL_DIR)
  python trainer_report.py --log evidence_log.jsonl
  python trainer_report.py --json > report.json"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_events(log: str | None) -> list[dict]:
    events: list[dict] = []
    if log:
        for line in Path(log).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return events
    from app.storage import store

    st = store()
    for key in st.list_keys("events/"):
        ev = st.get_json(key, None)
        if isinstance(ev, dict):
            events.append(ev)
    return events


def build_report(events: list[dict]) -> dict:
    users = {e.get("user_id") for e in events if e.get("user_id")}
    by_kind = Counter(str(e.get("event")) for e in events)
    per_kc_pass: dict[str, list[int]] = defaultdict(list)
    kc_titles: dict[str, str] = {}
    failed_questions: Counter = Counter()
    question_text: dict[str, str] = {}
    for e in events:
        if e.get("event") == "practice_submitted":
            kc = str(e.get("kc_id"))
            kc_titles[kc] = str(e.get("kc_title") or kc)
            per_kc_pass[kc].append(1 if e.get("passed") else 0)
            for wi in e.get("wrong_items") or []:
                qid = str(wi.get("id") or f"{kc}:{wi.get('question', '')[:40]}")
                failed_questions[qid] += 1
                question_text[qid] = str(wi.get("question") or "")
        elif e.get("event") == "diagnostic_submitted":
            for wi in e.get("wrong_items") or []:
                pass
    reported = [e for e in events if e.get("event") == "question_reported"]
    feedback = Counter(str(e.get("kind")) for e in events if e.get("event") == "item_feedback")
    kc_rows = []
    for kc, results in sorted(per_kc_pass.items(), key=lambda kv: sum(kv[1]) / max(1, len(kv[1]))):
        kc_rows.append({"kc_id": kc, "notion": kc_titles.get(kc, kc), "attempts": len(results), "pass_rate": round(sum(results) / max(1, len(results)), 2)})
    return {
        "learners": len(users),
        "events": dict(by_kind),
        "notions_by_pass_rate": kc_rows,
        "most_failed_questions": [{"id": q, "failures": n, "question": question_text.get(q, "")} for q, n in failed_questions.most_common(15)],
        "reported_questions": [{"quiz_id": e.get("quiz_id"), "question_id": e.get("question_id"), "kc_id": e.get("kc_id"), "user": e.get("user_id"), "at": e.get("timestamp")} for e in reported],
        "feedback": dict(feedback),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = build_report(load_events(args.log))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0
    print(f"Apprenants distincts : {report['learners']}")
    print("Événements :", ", ".join(f"{k}={v}" for k, v in sorted(report["events"].items())))
    print("\nNotions par taux de réussite (les plus dures d'abord) :")
    for r in report["notions_by_pass_rate"]:
        print(f"  {r['pass_rate']:.0%}  {r['attempts']:>3} essais  {r['notion']}")
    print("\nQuestions les plus ratées :")
    for q in report["most_failed_questions"]:
        print(f"  {q['failures']:>3}  {q['question'][:100]}")
    print(f"\nQuestions signalées : {len(report['reported_questions'])}")
    for r in report["reported_questions"][:20]:
        print(f"  {r['at']}  {r['kc_id']}  {r['question_id']}")
    print("Pouces :", report["feedback"] or "aucun")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
