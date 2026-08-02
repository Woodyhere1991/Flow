"""Download and verify Flow's selected speech model during installation."""

import argparse
import os

from huggingface_hub import snapshot_download


MODELS = {
    size: f"nyralabs/CrisperWhisper2.0_{size}"
    for size in ("small", "turbo", "large")
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        choices=sorted(MODELS),
        default=os.environ.get("FLOW_DEFAULT_MODEL", "turbo"),
    )
    args = parser.parse_args()
    model_id = MODELS[args.model]

    print(f"Downloading {model_id}...")
    model_path = snapshot_download(repo_id=model_id)
    verified_path = snapshot_download(repo_id=model_id, local_files_only=True)
    if model_path != verified_path:
        raise RuntimeError("The offline model cache could not be verified.")
    print("Speech model ready for offline use.")


if __name__ == "__main__":
    main()
