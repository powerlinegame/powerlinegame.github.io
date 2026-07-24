#!/usr/bin/env python3
"""
build_phrase_map.py

Scans the word-bank of .wav clips and guesses what phrase each clip says,
based on its filename (e.g. "allunitsapplyforwardpressure.wav" ->
"all units apply forward pressure"). Writes phrase_map.json.

The guesses are NOT perfect (see printed warnings) -- open phrase_map.json
afterward and fix any entries that look wrong. radiovoice_tts.py reads
that file, so your corrections are picked up automatically next run.
"""
import json
import re
import sys
from pathlib import Path

import wordninja

CLIPS_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("extracted")
OUT_PATH = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("phrase_map.json")

# Filenames that are numbered variants of the same line (pick randomly at
# playback time instead of treating "die1"/"die2"/"die3" as different words).
VARIANT_RE = re.compile(r"^(?P<base>[a-zA-Z_]+?)(?P<n>\d+)$")

# Hand overrides for names wordninja will mangle or that are pure codes.
MANUAL = {
    "_comma": ",",
    "upi": "upi",
    "xray": "x-ray",
    "cp": "cp",
    "fmil_region 073": "fmil region 073",
    "innoculate": "inoculate",
    "preparetoinnoculate": "prepare to inoculate",
    "sociocide": "sociocide",
    "incitingpopucide": "inciting popucide",
    "devisivesociocidal": "divisive sociocidal",
    "deservicedarea": "deserviced area",
    "unitdeserviced": "unit deserviced",
    "disassociationfromcivic": "disassociation from civic",
    "beginscanning10-0": "begin scanning 10-0",
    "politistablizationmarginal": "politi stabilization marginal",
    "recalibratesocioscan": "recalibrate socioscan",
    "recievingconflictingdata": "receiving conflicting data",
    "posession69": "possession 69",
    "destrutionofcpt": "destruction of cpt",
    "workforceintake": "workforce intake",
    "confirmupialert": "confirm upi alert",
}


def split_digits(token: str):
    """Split a token into alpha / digit / punctuation runs, e.g.
    'statuson243suspect' -> ['statuson', '243', 'suspect']"""
    return re.findall(r"[A-Za-z]+|\d+|[^A-Za-z\d]+", token)


def guess_phrase(stem: str) -> str:
    if stem in MANUAL:
        return MANUAL[stem]

    words = []
    for chunk in split_digits(stem):
        if chunk.isdigit() or not chunk.isalpha():
            words.append(chunk)
        else:
            words.extend(wordninja.split(chunk))
    return " ".join(words).strip()


def main():
    if not CLIPS_DIR.exists():
        sys.exit(f"Clips directory not found: {CLIPS_DIR}")

    entries = {}
    ambiguous = []

    for wav in sorted(CLIPS_DIR.glob("*.wav")):
        stem = wav.stem
        phrase = guess_phrase(stem)
        entries[wav.name] = phrase
        # flag anything wordninja split into lots of tiny fragments --
        # usually a sign the guess is wrong and needs a human look.
        if len(phrase.split()) >= 4 and len(stem) / max(len(phrase.split()), 1) < 3:
            ambiguous.append((wav.name, phrase))

    OUT_PATH.write_text(json.dumps(entries, indent=2, sort_keys=True))
    print(f"Wrote {len(entries)} entries to {OUT_PATH}")

    if ambiguous:
        print(f"\n{len(ambiguous)} entries look uncertain -- worth a manual check in {OUT_PATH}:")
        for name, phrase in ambiguous:
            print(f"  {name:45s} -> {phrase!r}")


if __name__ == "__main__":
    main()
