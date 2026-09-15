# app/local_search.py
"""Keyword search over the bundled doctrine PDF, used as the grounding tool
whenever OpenAI's hosted FileSearchTool/vector store isn't reachable: the
Mistral path, and an OpenAI call made with a trainer's own foreign API key
(their key has no access to this app's private vector store).

The bundled PDF ("Charte graphique 2025 - Impression.pdf") turned out to be
a design/layout export with almost no extractable text layer: pypdf and
PyMuPDF both recover only the running header on content pages (~41 chars),
never the actual doctrine text -- confirmed 2026-09-15 by dumping raw
per-page extraction. Rendering each page to an image and OCR-ing it recovers
the real content.

OCR is precomputed at Docker BUILD time (see build_doctrine_index.py, run
from the Dockerfile) into doctrine_chunks.json, not lazily on the first
search request: a live test on the deployed container (140 mvCPU on
Scaleway, far less CPU than a dev machine) showed a first real diagnostic
request hanging for minutes -- OCR-ing 24 pages on that little CPU is slow
enough to look broken. If the cache file is missing (PDF swapped without
regenerating it), this module falls back to extracting live, which will be
just as slow but at least won't silently serve stale content."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

from agents import function_tool
from rank_bm25 import BM25Okapi

APP_DIR = Path(__file__).resolve().parent
DOCTRINE_PDF_NAME = os.getenv("DOCTRINE_PDF_NAME", "Charte graphique 2025 - Impression.pdf")
CHUNKS_CACHE_NAME = os.getenv("DOCTRINE_CHUNKS_CACHE", "doctrine_chunks.json")
OCR_LANG = os.getenv("DOCTRINE_OCR_LANG", "fra")
OCR_DPI = int(os.getenv("DOCTRINE_OCR_DPI", "200"))
# Below this many characters, a page's native text layer is assumed to be
# just a running header/footer, not real content -> render + OCR instead.
NATIVE_TEXT_MIN_CHARS = 150


def _page_text(page) -> str:
    native = (page.get_text() or "").strip()
    if len(native) >= NATIVE_TEXT_MIN_CHARS:
        return native
    import io
    import pytesseract
    from PIL import Image

    pix = page.get_pixmap(dpi=OCR_DPI)
    image = Image.open(io.BytesIO(pix.tobytes("png")))
    return (pytesseract.image_to_string(image, lang=OCR_LANG) or "").strip()


def extract_chunks(pdf_path: Path) -> List[Tuple[int, str]]:
    """Live extraction (native text layer, OCR fallback per page). Slow on a
    CPU-constrained container -- only meant to run at Docker build time via
    build_doctrine_index.py, or as a last-resort fallback if the precomputed
    cache is missing."""
    import pymupdf as fitz

    chunks: List[Tuple[int, str]] = []
    doc = fitz.open(str(pdf_path))
    try:
        for page_num in range(len(doc)):
            text = _page_text(doc[page_num])
            if not text:
                continue
            for para in re.split(r"\n\s*\n", text):
                para = re.sub(r"\s+", " ", para).strip()
                if len(para) >= 20:
                    chunks.append((page_num + 1, para))
    finally:
        doc.close()
    return chunks


def _load_cached_chunks(cache_path: Path) -> List[Tuple[int, str]] | None:
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return [(int(item["page"]), str(item["text"])) for item in data]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def save_chunks_cache(chunks: List[Tuple[int, str]], cache_path: Path) -> None:
    payload = [{"page": page, "text": text} for page, text in chunks]
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")


class _DocIndex:
    def __init__(self, pdf_path: Path, cache_path: Path) -> None:
        self.chunks: List[Tuple[int, str]] = (
            _load_cached_chunks(cache_path) or extract_chunks(pdf_path)
        )
        tokenized = [self._tokenize(text) for _, text in self.chunks]
        self.bm25 = BM25Okapi(tokenized) if tokenized else None

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"[a-zà-ÿœæ0-9]+", text.lower())

    def search(self, query: str, top_k: int) -> List[Tuple[int, str]]:
        if not self.bm25 or not self.chunks:
            return []
        scores = self.bm25.get_scores(self._tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [self.chunks[i] for i in ranked[:top_k] if scores[i] > 0]


_INDEX_CACHE: Dict[str, _DocIndex] = {}


def _get_index() -> _DocIndex:
    pdf_path = APP_DIR / DOCTRINE_PDF_NAME
    cache_path = APP_DIR / CHUNKS_CACHE_NAME
    key = str(pdf_path)
    if key not in _INDEX_CACHE:
        _INDEX_CACHE[key] = _DocIndex(pdf_path, cache_path)
    return _INDEX_CACHE[key]


def build_local_search_tool(*, max_results: int = 8):
    """Returns a fresh FunctionTool bound to the given result count. Cheap to
    call per-request: the index itself is built once (from the precomputed
    cache, normally) and kept in the process.

    Named `file_search` on purpose: every agent's instructions in
    orchestrator.py say "use file_search" by that literal name, written back
    when the only grounding tool was OpenAI's FileSearchTool. Matching the
    name lets the same instructions work unchanged for the Mistral / local
    path instead of forking every prompt in the file."""

    @function_tool(name_override="file_search")
    def file_search(query: str) -> str:
        """Search the reference doctrine PDF for passages relevant to the query.

        Args:
            query: What to look for (a concept, a term, a KC title).
        """
        hits = _get_index().search(query, max_results)
        if not hits:
            return "No matching passage found in the doctrine PDF."
        return "\n\n".join(f"[p.{page}] {text}" for page, text in hits)

    return file_search
