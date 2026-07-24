#!/usr/bin/env python3
"""
Radio Voice TTS — web server.

Serves the dispatch entry webpage and exposes an API that synthesizes
spoken dispatch messages from form inputs, then plays them through
speakers and radio channel 1 (when a radio output device is configured).

Usage:
    python server.py
    python server.py --port 8080
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"

app = Flask(__name__, static_folder=str(SCRIPT_DIR), static_url_path="")


def load_config() -> dict:
    defaults = {
        "host": "127.0.0.1",
        "port": 5000,
        "speaker_device": None,
        "radio_device": None,
        "radio_channel": 1,
    }
    if CONFIG_PATH.exists():
        defaults.update(json.loads(CONFIG_PATH.read_text()))
    return defaults


CONFIG = load_config()

# Lazy-init the word bank so startup is fast even with many clips.
_bank = None


def get_bank():
    global _bank
    if _bank is None:
        from radiovoice_tts import WordBank, CLIPS_DIR, PHRASE_MAP_PATH

        _bank = WordBank(CLIPS_DIR, PHRASE_MAP_PATH)
    return _bank


def build_dispatch_text(answers: dict[str, str], incident_type: str | None = None) -> str:
    """Turn webpage answers into a spoken dispatch message."""
    incident_prefix = {
        "crime": "crime emergency",
        "medical": "medical emergency",
        "fire": "fire emergency",
    }

    parts = []
    if incident_type in incident_prefix:
        parts.append(incident_prefix[incident_type])

    for key, value in answers.items():
        value = (value or "").strip()
        if value:
            parts.append(f"{key.lower()} {value}")

    if not parts:
        return "Attention, no dispatch information received."

    return "Attention, " + ", ".join(parts) + "."


@app.route("/")
def index():
    return send_from_directory(SCRIPT_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(SCRIPT_DIR, filename)


@app.route("/api/health")
def health():
    from radiovoice_tts import CLIPS_DIR, PHRASE_MAP_PATH

    bank = get_bank()
    return jsonify(
        {
            "status": "ok",
            "clips_dir": str(CLIPS_DIR),
            "clips_found": CLIPS_DIR.exists() and any(CLIPS_DIR.glob("*.wav")),
            "vocab_size": len(bank.phrase_to_files),
            "radio_device": CONFIG.get("radio_device"),
            "radio_channel": CONFIG.get("radio_channel", 1),
        }
    )


@app.route("/api/devices")
def devices():
    from audio_output import list_output_devices

    return jsonify({"devices": list_output_devices()})


@app.route("/api/speak", methods=["POST"])
def speak():
    """Synthesize text and play through speakers + radio."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400

    return _synthesize_and_play(text)


@app.route("/api/dispatch", methods=["POST"])
def dispatch():
    """Build dispatch message from form answers, synthesize, and play."""
    data = request.get_json(silent=True) or {}
    answers = data.get("answers") or {}
    incident_type = data.get("incident_type")
    if not isinstance(answers, dict):
        return jsonify({"error": "answers must be an object"}), 400

    text = build_dispatch_text(answers, incident_type=incident_type)
    return _synthesize_and_play(text, answers=answers, incident_type=incident_type)


def _synthesize_and_play(text: str, answers: dict | None = None, incident_type: str | None = None):
    from radiovoice_tts import synthesize, TARGET_SR, write_wav
    from audio_output import play_audio

    try:
        bank = get_bank()
        audio = synthesize(text, bank, verbose=False)

        # Save a copy for debugging / replay
        out_path = SCRIPT_DIR / "last_dispatch.wav"
        write_wav(out_path, audio)

        playback = play_audio(
            audio,
            sr=TARGET_SR,
            speaker_device=CONFIG.get("speaker_device"),
            radio_device=CONFIG.get("radio_device"),
            radio_channel=CONFIG.get("radio_channel", 1),
        )

        return jsonify(
            {
                "text": text,
                "incident_type": incident_type,
                "answers": answers,
                "duration_sec": playback["duration_sec"],
                "played_to": playback["played_to"],
                "radio_connected": playback["radio_connected"],
                "radio_channel": playback["radio_channel"],
                "wav": "last_dispatch.wav",
            }
        )
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc), "hint": "Install espeak-ng and ensure clips/ exists."}), 500
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Synthesis or playback failed"}), 500


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default=CONFIG.get("host", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=CONFIG.get("port", 5000))
    args = ap.parse_args()

    print(f"Radio Voice TTS server  http://{args.host}:{args.port}")
    print(f"  clips dir : {SCRIPT_DIR / 'clips'}")
    print(f"  radio dev : {CONFIG.get('radio_device') or '(not configured)'}")
    print(f"  channel   : {CONFIG.get('radio_channel', 1)}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
