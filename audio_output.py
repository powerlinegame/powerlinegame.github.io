"""
Audio playback: default speakers plus optional radio interface (channel 1).

Configure the radio output device name or index in config.json under
"radio_device". When set and the device is available, synthesized audio
plays to both the default speakers and the radio interface simultaneously.
"""
from __future__ import annotations

import threading
from typing import Any

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None  # type: ignore


def list_output_devices() -> list[dict[str, Any]]:
    """Return available output (playback) devices."""
    if sd is None:
        return []
    devices = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] > 0:
            devices.append(
                {
                    "index": idx,
                    "name": dev["name"],
                    "channels": dev["max_output_channels"],
                    "default_samplerate": dev["default_samplerate"],
                }
            )
    return devices


def resolve_device(spec: str | int | None) -> int | None:
    """Resolve a device spec (index, name substring, or None for default)."""
    if spec is None or sd is None:
        return None
    if isinstance(spec, int):
        return spec
    spec_lower = str(spec).lower()
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] > 0 and spec_lower in dev["name"].lower():
            return idx
    return None


def _play_on_device(audio: np.ndarray, sr: int, device: int | None) -> None:
    if sd is None:
        raise RuntimeError("sounddevice is not installed")
    sd.play(audio, sr, device=device)
    sd.wait()


def play_audio(
    audio: np.ndarray,
    sr: int = 22050,
    speaker_device: str | int | None = None,
    radio_device: str | int | None = None,
    radio_channel: int = 1,
) -> dict[str, Any]:
    """
    Play audio to speakers and, if configured, to the radio interface.

    Returns a status dict describing where audio was routed.
    """
    if sd is None:
        raise RuntimeError("sounddevice is not installed — pip install sounddevice")

    speaker_idx = resolve_device(speaker_device)
    radio_idx = resolve_device(radio_device)

    targets: list[tuple[str, int | None]] = [("speakers", speaker_idx)]
    radio_connected = radio_idx is not None
    if radio_connected:
        targets.append((f"radio_channel_{radio_channel}", radio_idx))

    threads = []
    for label, device in targets:
        t = threading.Thread(
            target=_play_on_device,
            args=(audio, sr, device),
            name=f"playback-{label}",
            daemon=True,
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    return {
        "played_to": [label for label, _ in targets],
        "radio_connected": radio_connected,
        "radio_channel": radio_channel if radio_connected else None,
        "duration_sec": len(audio) / sr,
    }
