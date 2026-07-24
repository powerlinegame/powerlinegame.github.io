#!/usr/bin/env python3
"""
radiovoice_tts.py -- "good enough to understand" TTS built on a small
recorded word/phrase bank.

How it works
------------
1. It has ~181 real recorded clips (radio dispatch phrases/words) and a
   phrase_map.json saying what each one says.
2. Given input text, it greedily matches the LONGEST runs of words it can
   find real recordings for (so "all units apply forward pressure now"
   plays the real "all units apply forward pressure" clip, then
   synthesizes just "now").
3. Anything not covered by a recording is synthesized with espeak-ng
   (offline, always intelligible) and then run through a filter chain
   (bandpass EQ + soft distortion + light noise) tuned to sit closer to
   the recorded clips, so the two don't clash too hard.
4. All pieces are resampled to one rate, leveled, and concatenated with
   small gaps into a single output .wav.

This is NOT a trained neural voice -- it's a practical hybrid that
reuses your real voice wherever possible. Quality on fallback words is
"understandable", not "indistinguishable from the recordings".

Usage
-----
    python3 radiovoice_tts.py "all units, suspect is now 187 at sector 4" out.wav
    python3 radiovoice_tts.py --list-vocab          # see what's covered

Requires: espeak-ng and ffmpeg on PATH, numpy + scipy installed.
"""
import argparse
import json
import random
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt, resample_poly

SCRIPT_DIR = Path(__file__).resolve().parent
CLIPS_DIR = SCRIPT_DIR / "clips"
PHRASE_MAP_PATH = SCRIPT_DIR / "phrase_map.json"
TARGET_SR = 22050
GAP_SEC = 0.12


# ---------------------------------------------------------------- audio io

def load_wav_mono(path: Path) -> np.ndarray:
    """Load any wav (varying sample rate / bit depth) as float32 mono at TARGET_SR."""
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        sampwidth = w.getsampwidth()
        nchan = w.getnchannels()
        raw = w.readframes(n)

    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[sampwidth]
    data = np.frombuffer(raw, dtype=dtype).astype(np.float32)

    if sampwidth == 1:  # unsigned 8-bit
        data = (data - 128.0) / 128.0
    else:
        data = data / float(2 ** (8 * sampwidth - 1))

    if nchan > 1:
        data = data.reshape(-1, nchan).mean(axis=1)

    if sr != TARGET_SR:
        data = resample_poly(data, TARGET_SR, sr).astype(np.float32)

    return data


def write_wav(path: Path, audio: np.ndarray, sr: int = TARGET_SR):
    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def normalize(audio: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = np.max(np.abs(audio)) if audio.size else 0
    return audio * (peak / m) if m > 1e-6 else audio


# ---------------------------------------------------------- style filter

def radio_filter(audio: np.ndarray, sr: int = TARGET_SR) -> np.ndarray:
    """Push a clean espeak-ng clip toward the recorded clips' character:
    bandpass EQ, soft clip distortion, and a touch of noise/crackle."""
    sos = butter(4, [300, 3400], btype="bandpass", fs=sr, output="sos")
    audio = sosfilt(sos, audio).astype(np.float32)

    drive = 3.0
    audio = np.tanh(audio * drive) / np.tanh(drive)

    noise = (np.random.default_rng(0).standard_normal(audio.shape) * 0.012).astype(np.float32)
    audio = audio + noise

    return normalize(audio, peak=0.85)


# --------------------------------------------------------------- espeak

def espeak_synthesize(text: str) -> np.ndarray:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        result = subprocess.run(
            ["espeak-ng", "-v", "en-us", "-s", "150", "-p", "25", "-w", str(tmp_path), text],
            capture_output=True,
        )
        if result.returncode != 0:
            raise FileNotFoundError(
                "espeak-ng failed — install it and ensure it is on PATH "
                "(https://github.com/espeak-ng/espeak-ng/releases on Windows)"
            )
        audio = load_wav_mono(tmp_path)
    except FileNotFoundError:
        raise FileNotFoundError(
            "espeak-ng not found — install it and ensure it is on PATH "
            "(https://github.com/espeak-ng/espeak-ng/releases on Windows)"
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    return radio_filter(audio)


# ------------------------------------------------------------- word bank

class WordBank:
    def __init__(self, clips_dir: Path, phrase_map_path: Path):
        raw = json.loads(phrase_map_path.read_text())
        # phrase (tuple of lowercase tokens) -> list of candidate wav paths
        self.phrase_to_files: dict[tuple, list[Path]] = {}
        for fname, phrase in raw.items():
            tokens = tuple(self._tokenize(phrase))
            if not tokens:
                continue
            path = clips_dir / fname
            if not path.exists():
                continue
            self.phrase_to_files.setdefault(tokens, []).append(path)
        self.max_len = max((len(k) for k in self.phrase_to_files), default=1)

    @staticmethod
    def _tokenize(text: str):
        return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*|[,.!?]", text.lower())

    _DIGIT_WORD = {
        "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
        "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    }

    def lookup(self, tokens: tuple) -> Path | None:
        cands = self.phrase_to_files.get(tokens)
        if not cands and len(tokens) == 1 and tokens[0] in self._DIGIT_WORD:
            cands = self.phrase_to_files.get((self._DIGIT_WORD[tokens[0]],))
        return random.choice(cands) if cands else None

    def match_longest(self, tokens: list, start: int):
        """Try the longest possible run of tokens starting at `start`
        that exists in the bank. Returns (path, length) or (None, 0)."""
        for length in range(min(self.max_len, len(tokens) - start), 0, -1):
            chunk = tuple(tokens[start:start + length])
            path = self.lookup(chunk)
            if path:
                return path, length
        return None, 0


# ------------------------------------------------------------- pipeline

def synthesize(text: str, bank: WordBank, verbose: bool = True) -> np.ndarray:
    tokens = WordBank._tokenize(text)
    pieces = []
    gap = np.zeros(int(GAP_SEC * TARGET_SR), dtype=np.float32)

    i = 0
    while i < len(tokens):
        path, length = bank.match_longest(tokens, i)
        if path:
            if verbose:
                print(f"  [bank]    {' '.join(tokens[i:i+length])!r:40s} <- {path.name}")
            pieces.append(normalize(load_wav_mono(path)))
            i += length
        else:
            word = tokens[i]
            if verbose:
                print(f"  [espeak]  {word!r}")
            pieces.append(espeak_synthesize(word))
            i += 1
        pieces.append(gap)

    if not pieces:
        return np.zeros(1, dtype=np.float32)
    return np.concatenate(pieces)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", nargs="?", help="Text to speak")
    ap.add_argument("out", nargs="?", default="output.wav", help="Output wav path")
    ap.add_argument("--list-vocab", action="store_true", help="Print every phrase covered by real recordings")
    args = ap.parse_args()

    bank = WordBank(CLIPS_DIR, PHRASE_MAP_PATH)

    if args.list_vocab:
        for phrase in sorted(" ".join(k) for k in bank.phrase_to_files):
            print(phrase)
        return

    if not args.text:
        ap.error("text is required unless --list-vocab is given")

    print(f'Synthesizing: "{args.text}"')
    audio = synthesize(args.text, bank)
    write_wav(Path(args.out), audio)
    print(f"Wrote {args.out} ({len(audio) / TARGET_SR:.2f}s)")


if __name__ == "__main__":
    main()
