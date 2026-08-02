"""Detect this PC and choose Flow's safest default speech model.

The profile is deliberately stored under Local AppData.  It describes the
current computer, is not personal content, and is never copied into Git.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
from pathlib import Path


APP_DATA_DIR = Path(os.environ.get(
    "LOCALAPPDATA", str(Path.home() / "AppData" / "Local")
)) / "Flow"
PROFILE_NAME = "hardware.json"
MODEL_CHOICE_NAME = "recommended_model.txt"
SETTINGS_NAME = "settings.json"
VALID_MODELS = {"small", "turbo", "large"}


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ulong),
        ("memory_load", ctypes.c_ulong),
        ("total_physical", ctypes.c_ulonglong),
        ("available_physical", ctypes.c_ulonglong),
        ("total_page_file", ctypes.c_ulonglong),
        ("available_page_file", ctypes.c_ulonglong),
        ("total_virtual", ctypes.c_ulonglong),
        ("available_virtual", ctypes.c_ulonglong),
        ("available_extended_virtual", ctypes.c_ulonglong),
    ]


def total_memory_gb() -> float:
    """Return installed physical memory without adding another dependency."""
    if os.name == "nt":
        status = _MemoryStatus()
        status.length = ctypes.sizeof(_MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return round(status.total_physical / (1024 ** 3), 1)
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return round(pages * page_size / (1024 ** 3), 1)
    except (AttributeError, OSError, ValueError):
        return 0.0


def cpu_name() -> str:
    if os.name == "nt":
        try:
            import winreg

            path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor().strip() or "Unknown CPU"


def build_profile(
    *,
    cuda_available: bool,
    gpu_name: str = "",
    gpu_memory_gb: float = 0.0,
    memory_gb: float,
    logical_processors: int,
    processor_name: str,
) -> dict:
    """Build a deterministic, testable recommendation from detected hardware."""
    logical_processors = max(1, int(logical_processors or 1))
    memory_gb = max(0.0, float(memory_gb or 0.0))

    gpu_memory_gb = max(0.0, float(gpu_memory_gb or 0.0))

    if cuda_available and (not gpu_memory_gb or gpu_memory_gb >= 3.5):
        return {
            "device": "cuda",
            "device_name": gpu_name or "NVIDIA GPU",
            "gpu_memory_gb": gpu_memory_gb,
            "cuda_available": True,
            "cpu_name": processor_name,
            "memory_gb": memory_gb,
            "logical_processors": logical_processors,
            "recommended_model": "turbo",
            "performance": "fast",
            "warning": "",
        }

    if cuda_available:
        return {
            "device": "cuda",
            "device_name": gpu_name or "NVIDIA GPU",
            "gpu_memory_gb": gpu_memory_gb,
            "cuda_available": True,
            "cpu_name": processor_name,
            "memory_gb": memory_gb,
            "logical_processors": logical_processors,
            "recommended_model": "small",
            "performance": "constrained_gpu",
            "warning": (
                f"The NVIDIA graphics card has only {gpu_memory_gb:.1f} GB of "
                "graphics memory. Flow selected its smaller speech model to "
                "avoid running out of memory."
            ),
        }

    limited = memory_gb and memory_gb < 8 or logical_processors < 4
    if limited:
        performance = "possibly_unusable"
        warning = (
            "This computer has no supported NVIDIA graphics card and has "
            "limited memory or processor capacity. Flow will use its smallest "
            "speech model, but transcription may take a long time and may not "
            "be useful on this computer."
        )
    else:
        performance = "slow"
        warning = (
            "This computer has no supported NVIDIA graphics card. Flow will "
            "use its smallest speech model, but there may still be a noticeable "
            "wait after every recording."
        )

    return {
        "device": "cpu",
        "device_name": "CPU",
        "gpu_memory_gb": 0.0,
        "cuda_available": False,
        "cpu_name": processor_name,
        "memory_gb": memory_gb,
        "logical_processors": logical_processors,
        "recommended_model": "small",
        "performance": performance,
        "warning": warning,
    }


def detect_profile(force_device: str | None = None) -> dict:
    import torch

    cuda_available = force_device != "cpu" and torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if cuda_available else ""
    gpu_memory_gb = (
        round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 1)
        if cuda_available else 0.0
    )
    return build_profile(
        cuda_available=cuda_available,
        gpu_name=gpu_name,
        gpu_memory_gb=gpu_memory_gb,
        memory_gb=total_memory_gb(),
        logical_processors=os.cpu_count() or 1,
        processor_name=cpu_name(),
    )


def save_profile(profile: dict, app_data_dir: Path) -> None:
    app_data_dir.mkdir(parents=True, exist_ok=True)
    profile_path = app_data_dir / PROFILE_NAME
    profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    (app_data_dir / MODEL_CHOICE_NAME).write_text(
        profile["recommended_model"], encoding="ascii")

    settings_path = app_data_dir / SETTINGS_NAME
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            settings = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        settings = {}

    # Older Flow versions defaulted every PC to Turbo. Migrate that old default
    # to Small on CPU-only computers, but preserve a model the user explicitly
    # chose after hardware-aware settings became available.
    old_cpu_default = (
        profile["device"] == "cpu"
        and settings.get("size") == "turbo"
        and not settings.get("hardware_choice_confirmed", False)
    )
    if settings.get("size") not in VALID_MODELS or old_cpu_default:
        settings["size"] = profile["recommended_model"]
    settings["hardware_recommended_model"] = profile["recommended_model"]
    if settings:
        settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Choose Flow settings for this PC")
    parser.add_argument("--force-device", choices=["cpu"], help=argparse.SUPPRESS)
    parser.add_argument("--expected-nvidia", action="store_true")
    parser.add_argument("--app-data", type=Path, default=APP_DATA_DIR)
    args = parser.parse_args()

    profile = detect_profile(force_device=args.force_device)
    if args.expected_nvidia and not profile.get("cuda_available", False):
        raise RuntimeError(
            "An NVIDIA GPU was detected, but Flow could not enable CUDA. "
            "Setup stopped instead of silently installing a slow configuration."
        )

    save_profile(profile, args.app_data)
    print(f"Device: {profile['device_name']}")
    print(f"Memory: {profile['memory_gb']} GB")
    print(f"Recommended speech model: {profile['recommended_model']}")
    if profile["warning"]:
        print(f"WARNING: {profile['warning']}")
    else:
        print("Hardware acceleration is ready.")


if __name__ == "__main__":
    main()
