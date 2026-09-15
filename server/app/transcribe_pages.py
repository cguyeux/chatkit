# app/transcribe_pages.py
"""One-off, offline: transcribe every rendered doctrine page (pages/page-N.png)
into a STRUCTURED French description with a vision model, written to
doctrine_pages.json. Why: the Tesseract OCR baked at build time keeps only the
running text and loses exactly what this memento is about -- the mapping
between a shape / a colour swatch and its meaning (page 3: the table
"Formes élémentaires -> Signification" comes out as bare labels, page 4: the
six colour names are swatches, so they are simply absent from the OCR).
Measured 2026-09-15 on doctrine_chunks.json. The vision transcription is the
grounding source the tutor should use; the OCR remains a fallback.

Not run at Docker build (needs a key and human review afterwards): run it once
locally, review the JSON with the trainers, commit it. Goes through LiteLLM so
the same script works with Mistral (pixtral, free tier, 2026-09-15: the only
provider with credit left on this account) or OpenAI.

Usage:
  MISTRAL_API_KEY=... python transcribe_pages.py --model mistral/pixtral-large-latest
  OPENAI_API_KEY=...  python transcribe_pages.py --model gpt-4.1
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

import litellm

APP_DIR = Path(__file__).resolve().parent
PAGES_DIR = APP_DIR / "pages"
OUT_PATH = APP_DIR / "doctrine_pages.json"

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "page": {"type": "integer"},
        "title": {"type": "string", "description": "Titre principal de la page (chapitre / section), tel qu'imprimé."},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "heading": {"type": "string"},
                    "text": {"type": "string", "description": "Texte courant transcrit fidèlement, sans résumer."},
                },
                "required": ["heading", "text"],
            },
        },
        "symbols": {
            "type": "array",
            "description": "Chaque symbole, pictogramme, pastille ou forme figurant sur la page.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string", "description": "Libellé officiel imprimé à côté (ou vide)."},
                    "shape": {"type": "string", "description": "Forme géométrique ou pictogramme : carré, rectangle, cercle, triangle, étoile, polygone, ligne, flèche, drapeau…"},
                    "color": {"type": "string", "description": "Couleur dominante en français (bleu, rouge, vert, noir, orange, violet, jaune, gris, blanc…), 'contour seul' si non rempli."},
                    "style": {"type": "string", "description": "Trait plein, pointillé, hachuré, rempli, double trait, barré…"},
                    "meaning": {"type": "string", "description": "Signification opérationnelle exacte donnée par la page."},
                    "text_inside": {"type": "string", "description": "Texte ou abréviation inscrit dans le symbole, sinon vide."},
                },
                "required": ["label", "shape", "color", "style", "meaning", "text_inside"],
            },
        },
        "tables": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "columns": {"type": "array", "items": {"type": "string"}},
                    "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                },
                "required": ["title", "columns", "rows"],
            },
        },
        "rules": {
            "type": "array",
            "description": "Règles doctrinales explicites énoncées sur la page, une par entrée, formulées de façon testable.",
            "items": {"type": "string"},
        },
    },
    "required": ["page", "title", "sections", "symbols", "tables", "rules"],
}

PROMPT = (
    "Tu transcris une page du « Mémento gestion opérationnelle et commandement, outils graphiques » "
    "(ENSOSP, sapeurs-pompiers). Transcris FIDÈLEMENT et en français tout le contenu de la page : "
    "le texte courant (sans le résumer), chaque tableau, et surtout CHAQUE symbole ou pastille avec sa forme, "
    "sa couleur exacte, son style de trait et la signification imprimée à côté. Conserve les termes officiels "
    "tels quels (majuscules, abréviations comme PI, BI, ASP, CIT, PC, PRV…). N'invente rien : si une signification "
    "n'est pas lisible, écris 'illisible'. Le numéro de page est {page}.\n\n"
    "Réponds UNIQUEMENT par un objet JSON conforme à ce schéma (pas de texte autour, pas de bloc de code) :\n"
    "{schema}"
)

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _parse_json(text: str) -> dict:
    m = _FENCE_RE.search(text)
    raw = m.group(1) if m else text
    start = raw.find("{")
    end = raw.rfind("}")
    return json.loads(raw[start : end + 1])


def transcribe_page(model: str, page: int) -> dict:
    img = PAGES_DIR / f"page-{page}.png"
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": PROMPT.format(page=page, schema=json.dumps(SCHEMA, ensure_ascii=False))},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64(img)}"}},
        ],
    }]
    kwargs: dict = {}
    if model.startswith("mistral/"):
        kwargs["response_format"] = {"type": "json_object"}
    else:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "doctrine_page", "schema": SCHEMA, "strict": True},
        }
    resp = litellm.completion(model=model, messages=messages, temperature=0, **kwargs)
    data = _parse_json(resp.choices[0].message.content or "")
    data["page"] = page
    data["model"] = model
    return data


def parse_range(spec: str, n_max: int) -> list[int]:
    if not spec:
        return list(range(1, n_max + 1))
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return [p for p in out if 1 <= p <= n_max]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.getenv("TRANSCRIBE_MODEL", "mistral/pixtral-large-latest"))
    ap.add_argument("--pages", default="")
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--sleep", type=float, default=1.5, help="pause between pages (free-tier rate limit)")
    args = ap.parse_args()

    n_pages = len(list(PAGES_DIR.glob("page-*.png")))
    if not n_pages:
        print("No rendered pages in", PAGES_DIR, "-- run build_doctrine_index.py first", file=sys.stderr)
        return 2
    out_path = Path(args.out)
    existing: dict[int, dict] = {}
    if out_path.exists():
        for item in json.loads(out_path.read_text(encoding="utf-8")):
            existing[int(item["page"])] = item

    failures = 0
    for page in parse_range(args.pages, n_pages):
        data = None
        for attempt in range(3):
            try:
                data = transcribe_page(args.model, page)
                break
            except Exception as exc:  # rate limit / malformed JSON: retry, then report
                print(f"page {page}: attempt {attempt + 1} failed: {exc}", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        if data is None:
            failures += 1
            continue
        existing[page] = data
        print(f"page {page}: {len(data.get('symbols', []))} symbols, {len(data.get('rules', []))} rules, title={data.get('title')!r}")
        out_path.write_text(
            json.dumps([existing[k] for k in sorted(existing)], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        time.sleep(args.sleep)
    print("wrote", out_path, "pages:", sorted(existing), "failures:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
