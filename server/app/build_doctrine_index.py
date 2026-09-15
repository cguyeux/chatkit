# app/build_doctrine_index.py
"""Run at Docker BUILD time (see Dockerfile) to precompute the OCR'd
doctrine index into doctrine_chunks.json, baked into the image. Keeps the
deployed container (140 mvCPU on Scaleway) from having to OCR 24 pages on a
user's first real request -- that took long enough live (2026-09-15) to look
hung. Re-run manually (`python build_doctrine_index.py`) after swapping the
bundled PDF, or just rebuild the image."""

from local_search import APP_DIR, CHUNKS_CACHE_NAME, DOCTRINE_PDF_NAME, extract_chunks, save_chunks_cache


def main() -> None:
    pdf_path = APP_DIR / DOCTRINE_PDF_NAME
    cache_path = APP_DIR / CHUNKS_CACHE_NAME
    print(f"Extracting (native text + OCR fallback) from {pdf_path} ...")
    chunks = extract_chunks(pdf_path)
    save_chunks_cache(chunks, cache_path)
    print(f"Wrote {len(chunks)} chunks to {cache_path}")


if __name__ == "__main__":
    main()
