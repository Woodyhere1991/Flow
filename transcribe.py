"""
Transcribe an audio file with CrisperWhisper.

Usage:
    python transcribe.py path\to\audio.wav
    python transcribe.py path\to\audio.mp3 --timestamps
    python transcribe.py path\to\audio.mp3 --model medium
"""

import argparse
import sys
import time

import torch
from crisperwhisper import CrisperWhisperModel

# Same NZ dictionary the dictation app applies, so file transcripts get the
# same te reo and place-name fixes (e.g. every mangling of Tauranga).
from hotkey import apply_nz_dictionary


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio with CrisperWhisper")
    parser.add_argument("audio", help="Path to the audio file")
    parser.add_argument(
        "--model",
        default="large",
        choices=["large", "medium", "small", "turbo"],
        help="Model size. Smaller = faster, less accurate (default: large)",
    )
    parser.add_argument("--language", default="en", help="Language code (default: en)")
    parser.add_argument(
        "--timestamps",
        action="store_true",
        help="Print per-word start/end times",
    )
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        print(f"Using GPU: {torch.cuda.get_device_name(0)}")
    else:
        print("No GPU detected - falling back to CPU (much slower)")

    print(f"Loading '{args.model}' model...")
    # backend="transformers" is required on Windows: the fast CT2 backend needs
    # the ctranslate2-crisperwhisper fork, which only ships Linux x86_64 wheels.
    # Stock ctranslate2 is installed purely to satisfy an unconditional import
    # in crisperwhisper/hallucination.py - leaving backend on "auto" would make
    # it wrongly select CT2 and fail on the missing fork APIs.
    model = CrisperWhisperModel(args.model, device=device, backend="transformers")

    print(f"Transcribing {args.audio}...")
    started = time.perf_counter()
    result = model.transcribe(
        args.audio,
        language=args.language,
        word_timestamps=args.timestamps,
    )
    elapsed = time.perf_counter() - started

    print(f"\n--- Transcript ({elapsed:.1f}s) ---")
    print(apply_nz_dictionary(result.text))

    if args.timestamps:
        print("\n--- Word timings ---")
        for w in result.words:
            print(f"{w.start:7.2f} - {w.end:7.2f}  {w.word}")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as exc:
        print(f"Audio file not found: {exc}", file=sys.stderr)
        sys.exit(1)
