# app/eval_generation.py
"""Offline quality evaluation of quiz generation, per provider, WITHOUT any
learner: for a sample of notions, generate a quiz, then measure

  - validity rate: questions that survive normalisation (4 distinct choices,
    resolvable key) over questions produced;
  - answer-letter distribution BEFORE shuffling (LLM bias toward A/B);
  - duplicate rate (normalised text);
  - "answer visible in the stem" rate (the correct choice text appears in
    the question);
  - groundedness, judged by a second model call against the page text
    (grounded / partly / not) -- a judge, not a proof;
  - latency per generation.

  MISTRAL_API_KEY=... python eval_generation.py --provider mistral --n 6 --out eval_mistral.tsv
  OPENAI_API_KEY=...  python eval_generation.py --provider openai  --n 6 --out eval_openai.tsv"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("STATE_LOCAL_DIR", "/tmp/its-eval-state")

from pydantic import BaseModel  # noqa: E402

from app.content import doctrine  # noqa: E402
from app.orchestrator import INSTR_QCM, KC_GRAPH_PATH, KcGraph  # noqa: E402
from app.providers import ProviderChoice, current_provider, run_structured  # noqa: E402
from app.schemas import QcmList, normalize_questions  # noqa: E402


class Verdict(BaseModel):
    grounded: str  # oui | partiel | non
    reason: str = ""


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


async def judge(kc_title: str, page_text: str, q: dict) -> Verdict:
    prompt = (
        f"Notion : {kc_title}. Extrait du mémento :\n{page_text}\n\nQuestion : {q['text']}\nPropositions : {q['choices']}\nRéponse annoncée : {q['answer']}\n"
        "La réponse annoncée est-elle la seule correcte ET démontrable à partir de l'extrait ? grounded = oui / partiel / non, reason = une phrase."
    )
    return await run_structured("Judge", "Tu es un vérificateur strict de questions d'examen. Tu réponds en JSON.", prompt, Verdict, None)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="mistral", choices=["mistral", "openai"])
    ap.add_argument("--n", type=int, default=6, help="number of notions sampled")
    ap.add_argument("--per-kc", type=int, default=4)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    current_provider.set(ProviderChoice(provider=args.provider))
    graph = KcGraph.load(KC_GRAPH_PATH)
    doc = doctrine()
    ids = graph.kc_ids()
    step = max(1, len(ids) // args.n)
    sample = ids[::step][: args.n]
    rows: list[dict] = []
    letters = Counter()
    produced = valid = dup = visible = 0
    latencies: list[float] = []
    for kc_id in sample:
        kc = graph.nodes[kc_id]
        pages = graph.kc_pages(kc)
        text = doc.pages_text(pages, max_chars=7000)
        prompt = (
            f"Rédige {args.per_kc} questions à choix multiples sur la notion « {kc.title} », pages {pages} :\n\n{text}\n\n"
            "Contraintes : question < 240 caractères, 4 propositions courtes et distinctes, une seule juste, answer = lettre, explanation avec la page, pas de doublon."
        )
        t0 = time.time()
        try:
            out = await run_structured("Eval-QCM", INSTR_QCM, prompt, QcmList, None)
        except Exception as exc:  # noqa: BLE001
            print(f"{kc_id}: FAILED {exc}", file=sys.stderr)
            continue
        latencies.append(time.time() - t0)
        raw_qs = [q.model_dump() for q in out.questions]
        produced += len(raw_qs)
        for q in raw_qs:
            letters[str(q.get("answer", "")).strip().upper()[:1]] += 1
        clean = normalize_questions(raw_qs, kc.id, shuffle=False)
        valid += len(clean)
        seen: set[str] = set()
        for q in clean:
            key = _fold(q["text"])
            if key in seen:
                dup += 1
            seen.add(key)
            correct_text = _fold(q["choices"]["ABCD".index(q["answer"])])
            if len(correct_text) >= 4 and correct_text in _fold(q["text"]):
                visible += 1
            verdict = None
            if not args.no_judge:
                try:
                    verdict = await judge(kc.title, text, q)
                except Exception as exc:  # noqa: BLE001
                    verdict = Verdict(grounded="?", reason=str(exc)[:80])
            rows.append({"kc_id": kc.id, "notion": kc.title, "question": q["text"], "answer": q["answer"], "grounded": verdict.grounded if verdict else "", "reason": verdict.reason if verdict else "", "latency_s": round(latencies[-1], 1)})
        print(f"{kc.id} {kc.title}: {len(clean)}/{len(raw_qs)} valid, {latencies[-1]:.1f}s")
    grounded = Counter(r["grounded"] for r in rows)
    print("\n=== Résumé", args.provider, "===")
    print(f"questions produites {produced}, valides {valid} ({valid / max(1, produced):.0%}), doublons {dup}, réponse visible dans l'énoncé {visible}")
    print("lettres de réponse avant mélange :", dict(letters))
    print("ancrage (juge) :", dict(grounded))
    print(f"latence moyenne par génération : {sum(latencies) / max(1, len(latencies)):.1f}s sur {len(latencies)} générations")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("kc_id\tnotion\tquestion\tanswer\tgrounded\treason\tlatency_s\n")
            for r in rows:
                f.write("\t".join(str(r[k]).replace("\t", " ") for k in ["kc_id", "notion", "question", "answer", "grounded", "reason", "latency_s"]) + "\n")
        print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
