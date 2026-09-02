r"""
Second dictation engine: faster-whisper running Whisper large-v3-turbo.

CrisperWhisper (the default engine) is the best tool for verbatim English,
but it understands only English and its model weights carry a
non-commercial licence. Whisper large-v3-turbo is weaker at verbatim
transcription, but it understands 99 languages - including te reo Māori -
runs several times faster through CTranslate2, and its weights are
permissively licensed (the commercial path noted in PRODUCT_RESEARCH.md).

This module hides the difference between the two engines behind one
transcribe(model, path, language) -> text call so hotkey.py can treat
either engine the same way. It deliberately uses ctranslate2 directly
(already installed) rather than pulling in another copy of anything.
"""

import os
from pathlib import Path

# The community CTranslate2 conversion of Whisper large-v3-turbo: ~1.6 GB,
# fp16 on the GPU. Systran publishes conversions of the smaller models but
# not of turbo; this is the widely used one.
MODEL_ID = "deepdml/faster-whisper-large-v3-turbo-ct2"


def load_model(profile_device="auto"):
    """Load the model on the best device for this PC.

    profile_device mirrors the hardware profile's forced-CPU override:
    "cpu" stays on CPU even when a GPU exists.
    """
    import ctranslate2
    from faster_whisper import WhisperModel

    use_cuda = (ctranslate2.get_cuda_device_count() > 0
                and profile_device != "cpu")
    if use_cuda:
        # ctranslate2 needs CUDA/cuDNN DLLs on the system path. Windows
        # machines rarely have them globally, but Flow's PyTorch install
        # bundles matching ones (CUDA 12.4) in torch/lib - point the DLL
        # search there before creating the model.
        import torch

        torch_lib = Path(torch.__file__).parent / "lib"
        if torch_lib.is_dir():
            os.add_dll_directory(str(torch_lib))
            os.environ["PATH"] = str(torch_lib) + os.pathsep + \
                os.environ.get("PATH", "")
        # float16 halves GPU memory against float32 with no accuracy cost
        # on supported cards; int8 is the CPU fallback.
        return WhisperModel(MODEL_ID, device="cuda", compute_type="float16")
    return WhisperModel(MODEL_ID, device="cpu", compute_type="int8")


def transcribe(model, path, language):
    """Transcribe one audio file and return clean text.

    language None means detect automatically - the right default for this
    engine, because a NZ sentence can legitimately mix English, te reo
    Māori and Chinese in one breath. VAD filtering skips silence so short
    dictation clips cannot come back with hallucinated filler.
    """
    segments, _info = model.transcribe(
        str(path), language=language, vad_filter=True, beam_size=5)
    return " ".join(segment.text.strip() for segment in segments).strip()
