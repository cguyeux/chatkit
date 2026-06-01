import argparse
import os

from outline_only_pipeline import (
    build_from_existing_outline,
    run_pipeline,
)
from build_clean_ecg_from_outline import build_clean_ecg


def resolve_chat_model(provider: str, chat_model: str | None) -> str:
    if chat_model:
        return chat_model
    if provider == "openai":
        return os.environ.get("OPENAI_CHAT_MODEL", "gpt-4.1")
    return os.environ.get("MISTRAL_CHAT_MODEL", "mistral-large-latest")


def run_end_to_end(
    outdir: str,
    pdf: str | None = None,
    outline_json: str | None = None,
    provider: str = "mistral",
    chat_model: str | None = None,
) -> None:
    provider = (provider or "mistral").lower()
    model = resolve_chat_model(provider, chat_model)

    if not pdf and not outline_json:
        raise SystemExit("Provide either --pdf or --outline_json")

    os.makedirs(outdir, exist_ok=True)
    outline_stage_dir = os.path.join(outdir, "outline")
    ecg_stage_dir = os.path.join(outdir, "ecg")
    os.makedirs(outline_stage_dir, exist_ok=True)
    os.makedirs(ecg_stage_dir, exist_ok=True)

    if outline_json:
        print("[Stage 1/2] Building normalized outline from existing outline JSON")
        build_from_existing_outline(outline_json, outline_stage_dir)
    else:
        print("[Stage 1/2] Running OCR + outline pipeline from PDF")
        run_pipeline(
            pdf_path=pdf,
            outdir=outline_stage_dir,
            chat_model=model,
            provider=provider,
        )

    outline_clean_path = os.path.join(outline_stage_dir, "outline_clean.json")
    if not os.path.exists(outline_clean_path):
        raise RuntimeError(f"Missing expected file: {outline_clean_path}")

    print("[Stage 2/2] Building ECG bundle")
    build_clean_ecg(outline_clean_path, ecg_stage_dir)

    print("\nAll done.")
    print(f"Root output folder: {outdir}")
    print(f"Outline outputs: {outline_stage_dir}")
    print(f"ECG outputs: {ecg_stage_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ECG main entrypoint: PDF/outline JSON -> normalized outline -> ECG bundle"
    )
    parser.add_argument("--pdf", help="Path to input PDF")
    parser.add_argument("--outline_json", help="Path to existing outline JSON")
    parser.add_argument("--outdir", required=True, help="Output root directory")
    parser.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "mistral"), help="mistral or openai")
    parser.add_argument("--chat_model", default=None, help="Chat model (provider-specific)")
    args = parser.parse_args()

    run_end_to_end(
        outdir=args.outdir,
        pdf=args.pdf,
        outline_json=args.outline_json,
        provider=args.provider,
        chat_model=args.chat_model,
    )


if __name__ == "__main__":
    main()
