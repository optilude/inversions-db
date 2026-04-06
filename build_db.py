#!/usr/bin/env python3
"""
build_db.py — Build inversions-db.json from per-key chord voicing files.

Reads the 12 flat-key JSON files (a.json, bb.json … b.json) in the input
directory and writes a single inversions-db.json suitable for programmatic
consumption.  No third-party dependencies required.

Output schema
-------------
{
  "C": [
    {
      "key": "C",
      "suffix": "major",
      "positions": [
        {
          "frets":     [int, ...],   // 6 elements; -1=muted 0=open 1+=relative fret
          "fingers":   [int, ...],   // 6 elements; 0=none/thumb 1-4=finger number
          "baseFret":  int,          // lowest absolute fret played (≥1)
          "barres":    [int, ...],   // relative fret(s) with a barre (usually [] or [1])
          "inversion": int           // 0=root 1=1st 2=2nd … -1=unknown
        }
      ]
    }
  ],
  "Db": [...],
  ...
}

Fret encoding
-------------
  -1  muted string
   0  open string
  1+  fret number relative to baseFret (so baseFret itself → 1)

Usage
-----
    # Regenerate from the bundled key files:
    python3 build_db.py

    # Custom paths:
    python3 build_db.py --input /path/to/key/files --output /path/to/out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Key / suffix configuration
# ---------------------------------------------------------------------------

# Source filename prefix → display key name
_KEYS: list[tuple[str, str]] = [
    ("c",  "C"),
    ("c#", "C#"),
    ("db", "Db"),
    ("d",  "D"),
    ("d#", "D#"),
    ("eb", "Eb"),
    ("e",  "E"),
    ("f",  "F"),
    ("f#", "F#"),
    ("gb", "Gb"),
    ("g",  "G"),
    ("g#", "G#"),
    ("ab", "Ab"),
    ("a",  "A"),
    ("a#", "A#"),
    ("bb", "Bb"),
    ("b",  "B"),
]

# Internal chord_type → output suffix label
_SUFFIX_MAP: dict[str, str] = {
    "major":         "major",
    "minor":         "minor",
    "maj7":          "maj7",
    "m7":            "m7",
    "7":             "7",
    "mmaj7":         "mmaj7",
    "m9":            "m9",
    "minor_cluster": "m_cluster",
    "maj6":          "6",
    "maj9":          "maj9",
    "major_cluster": "maj_cluster",
    "maj6_9":        "69",
    "m6":            "m6",
    "m6_9":          "m69",
    "dom9":          "9",
    "7#5":           "7#5",
    "7#9":           "7#9",
    "7b9":           "7b9",
    "dom11":         "11",
    "dom_cluster":   "dom_cluster",
    "dim":           "dim",
    "dim7":          "dim7",
    "m7b5":          "m7b5",
    "aug":           "aug",
    "aug7":          "aug7",
    "aug9":          "aug9",
    "maj7_shell":    "maj7_shell",
    "maj6_shell":    "6_shell",
    "m7_shell":      "m7_shell",
    "m6_shell":      "m6_shell",
    "7_shell":       "7_shell",
    "dim7_shell":    "dim7_shell",
}

# Canonical suffix order for output (controls sort order within each key)
_SUFFIX_ORDER: list[str] = [
    "major", "minor", "dim", "dim7", "aug",
    "maj7", "maj9", "6", "69", "maj_cluster",
    "maj7_shell", "6_shell",
    "m7", "m9", "m6", "m69", "mmaj7", "m7b5", "m_cluster",
    "m7_shell", "m6_shell",
    "7", "9", "11", "7b9", "7#9", "7#5", "dom_cluster",
    "7_shell",
    "aug7", "aug9",
    "dim7_shell",
]

# Canonical string-set sort order (descending string numbers = lowest→highest pitch)
_STRING_SET_ORDER: list[str] = [
    "6-5-4", "5-4-3", "4-3-2", "3-2-1",
    "6-5-3", "6-4-3", "5-4-2", "5-3-2", "4-3-1", "4-2-1",
]

# Finger letter → integer (PDF extraction sometimes stores letters)
_FINGER_MAP: dict[str, int] = {"i": 1, "m": 2, "a": 3, "T": 0}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_finger_int(raw: object) -> int:
    if raw is None:
        return 0
    if isinstance(raw, int):
        return raw
    s = str(raw).strip()
    if s in _FINGER_MAP:
        return _FINGER_MAP[s]
    try:
        return int(s)
    except ValueError:
        return 0


def _suffix_sort_key(suffix: str) -> int:
    try:
        return _SUFFIX_ORDER.index(suffix)
    except ValueError:
        return len(_SUFFIX_ORDER)


def _string_set_sort_key(ss: str) -> int:
    try:
        return _STRING_SET_ORDER.index(ss)
    except ValueError:
        return len(_STRING_SET_ORDER)


def _build_position(diagram: dict) -> dict | None:
    """Convert a key-file diagram to the output position format."""
    notes = diagram.get("notes", [])
    if not notes:
        return None

    note_by_string: dict[int, dict] = {n["string"]: n for n in notes}

    # 6-element arrays; index 0 = string 6 (low E), index 5 = string 1 (high e)
    frets_abs  = [-1] * 6
    fingers_arr = [0]  * 6
    for string_num in range(1, 7):
        idx = 6 - string_num
        if string_num in note_by_string:
            n = note_by_string[string_num]
            frets_abs[idx]   = n["fret"]
            fingers_arr[idx] = _to_finger_int(n.get("finger"))

    fretted  = [f for f in frets_abs if f > 0]
    base_fret = min(fretted) if fretted else 1

    frets_rel = []
    for f in frets_abs:
        if f == -1:
            frets_rel.append(-1)
        elif f == 0:
            frets_rel.append(0)
        else:
            frets_rel.append(f - base_fret + 1)

    # Barre: same non-zero finger at the same relative fret on 2+ strings.
    # Adjacency not required — a partial barre behind other fingers is valid.
    barre_groups: dict[tuple[int, int], list[int]] = {}
    for idx in range(6):
        fg = fingers_arr[idx]
        rf = frets_rel[idx]
        if fg != 0 and rf > 0:
            barre_groups.setdefault((fg, rf), []).append(idx)
    barres: list[int] = []
    for (fg, rf), indices in barre_groups.items():
        if len(indices) >= 2 and rf not in barres:
            barres.append(rf)

    inv = diagram.get("inversion_number")
    inversion = inv if isinstance(inv, int) else -1

    sounding   = sorted(note_by_string.keys(), reverse=True)
    string_set = "-".join(str(s) for s in sounding)

    return {
        "frets":            frets_rel,
        "fingers":          fingers_arr,
        "baseFret":         base_fret,
        "barres":           barres,
        "inversion":        inversion,
        "fingering_source": diagram.get("fingering_source"),
        "_string_set":      string_set,  # stripped before output
    }


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def build(input_dir: Path, output_path: Path, quiet: bool = False) -> None:
    """Read per-key JSON files and write inversions-db.json."""
    db: dict[str, list[dict]] = {}

    for file_prefix, key_name in _KEYS:
        path = input_dir / f"{file_prefix}.json"
        if not path.exists():
            if not quiet:
                print(f"  WARNING: {path} not found — skipping", file=sys.stderr)
            continue

        diagrams: list[dict] = json.loads(path.read_text(encoding="utf-8"))

        # Group by suffix
        by_suffix: dict[str, list[dict]] = {}
        for d in diagrams:
            ct     = d.get("chord_type", "")
            suffix = _SUFFIX_MAP.get(ct, ct)
            by_suffix.setdefault(suffix, []).append(d)

        # Build position entries sorted by suffix → string set → baseFret
        entries: list[dict] = []
        for suffix in sorted(by_suffix, key=_suffix_sort_key):
            positions = []
            for d in by_suffix[suffix]:
                pos = _build_position(d)
                if pos is not None:
                    positions.append(pos)

            positions.sort(
                key=lambda p: (_string_set_sort_key(p["_string_set"]), p["baseFret"])
            )
            for pos in positions:
                del pos["_string_set"]

            if positions:
                entries.append({"key": key_name, "suffix": suffix, "positions": positions})

        db[key_name] = entries

    output_path.write_text(json.dumps(db, indent=2), encoding="utf-8")

    if not quiet:
        total_types     = sum(len(v) for v in db.values())
        total_positions = sum(
            len(e["positions"]) for entries in db.values() for e in entries
        )
        size_kb = output_path.stat().st_size // 1024
        print(
            f"Wrote {output_path}  "
            f"({size_kb} KB · {len(db)} keys · {total_types} chord types · "
            f"{total_positions} positions)"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_db.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input", metavar="DIR",
        default=str(Path(__file__).parent),
        help="Directory containing a.json … b.json  (default: same directory as this script)",
    )
    parser.add_argument(
        "--output", metavar="FILE",
        default=str(Path(__file__).parent / "inversions-db.json"),
        help="Output file path  (default: inversions-db.json in the same directory)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress output")
    args = parser.parse_args(argv)

    input_dir   = Path(args.input).resolve()
    output_path = Path(args.output).resolve()

    if not input_dir.is_dir():
        print(f"ERROR: input directory not found: {input_dir}", file=sys.stderr)
        return 1

    build(input_dir, output_path, quiet=args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
