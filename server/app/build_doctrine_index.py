# app/build_doctrine_index.py
"""Run at Docker BUILD time (see Dockerfile): precompute what the deployed
container (140 mvCPU on Scaleway) must never do at request time.

1. OCR of the doctrine PDF into doctrine_chunks.json (Tesseract, fra): the
   PDF's content pages have no usable text layer -- measured 2026-09-15.
2. Page images pages/page-N.png (110 dpi) shown next to lessons and used by
   transcribe_pages.py for the structured vision transcription.

Re-run manually after swapping the bundled PDF, or just rebuild the image."""
from __future__ import annotations

from pathlib import Path

from local_search import APP_DIR, CHUNKS_CACHE_NAME, DOCTRINE_PDF_NAME, extract_chunks, save_chunks_cache

PAGES_DIR = APP_DIR / "pages"
PAGE_DPI = 110


def render_pages(pdf_path: Path) -> int:
    import pymupdf as fitz

    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    try:
        for i in range(len(doc)):
            out = PAGES_DIR / f"page-{i + 1}.png"
            if out.exists():
                continue
            doc[i].get_pixmap(dpi=PAGE_DPI).save(str(out))
        return len(doc)
    finally:
        doc.close()


def main() -> None:
    pdf_path = APP_DIR / DOCTRINE_PDF_NAME
    cache_path = APP_DIR / CHUNKS_CACHE_NAME
    if cache_path.exists():
        print(f"{cache_path} already present, OCR skipped")
    else:
        print(f"Extracting (native text + OCR fallback) from {pdf_path} ...")
        chunks = extract_chunks(pdf_path)
        save_chunks_cache(chunks, cache_path)
        print(f"Wrote {len(chunks)} chunks to {cache_path}")
    n = render_pages(pdf_path)
    print(f"Rendered {n} page images in {PAGES_DIR}")


if __name__ == "__main__":
    main()
