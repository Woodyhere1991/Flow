"""Download and verify Flow's default speech model during installation."""

from huggingface_hub import snapshot_download


MODEL_ID = "nyralabs/CrisperWhisper2.0_turbo"


def main() -> None:
    print(f"Downloading {MODEL_ID}...")
    model_path = snapshot_download(repo_id=MODEL_ID)
    verified_path = snapshot_download(repo_id=MODEL_ID, local_files_only=True)
    if model_path != verified_path:
        raise RuntimeError("The offline model cache could not be verified.")
    print("Speech model ready for offline use.")


if __name__ == "__main__":
    main()
