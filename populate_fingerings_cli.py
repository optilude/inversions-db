#!/usr/bin/env python3
"""Populate missing finger data in guitar chord voicing JSON files.

Reads one or more per-key JSON files (e.g. a.json, bb.json) and fills in
finger assignments for any voicing where all finger fields are null. Uses a
gap-aware algorithmic fingering approach that assigns playable fingers based
on fret position and string layout.

The algorithm
-------------
Fretted notes are processed in ascending fret order, maintaining a ``next_finger``
counter. Two passes are attempted:

  Pass 1 (gap formula): ``finger = max(next_finger, fret - min_fret + 1)``
  This spaces fingers naturally across the fretboard — e.g. a note at
  min_fret+2 gets finger 3, giving room for a lower-fret note to use finger 1.

  Pass 2 (consecutive): ``finger = next_finger``
  Pure sequential assignment. Used as fallback when the gap formula over-allocates
  (e.g. three notes spanning 4 frets would require fingers 1, 3, 5 — impossible).

Special cases:
  - Adjacent strings at the lowest fret → all share finger 1 (index barre)
  - Non-adjacent strings at the same fret → each gets its own consecutive finger
  - String gap > 4 on same fret → rejected (unplayable stretch)
  - Span > 4 frets or any required finger > 4 → no fingering assigned (None)

After assignment, a barre-gap check fixes any voicings where the same finger
spans non-adjacent strings with an unplayed string in the gap (which would
press an unintended note).

Usage
-----
    # Populate fingerings in specific files:
    python3 populate_fingerings_cli.py a.json bb.json

    # Populate all .json files in a directory:
    python3 populate_fingerings_cli.py --dir /path/to/key/files/

    # Preview what would change without writing:
    python3 populate_fingerings_cli.py --dry-run a.json

    # Populate all files in the current directory:
    python3 populate_fingerings_cli.py --dir .

No external dependencies — requires only Python 3.8+.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Fingering algorithm
# ---------------------------------------------------------------------------

def _has_fingering(notes: list[dict]) -> bool:
    """Return True if at least one note has a non-null, non-zero finger."""
    return any(n.get("finger") not in (None, 0, "0", "") for n in notes)


def _compute_algorithmic_fingers(notes: list[dict]) -> dict[int, int] | None:
    """Assign playable fingers to fretted notes using a greedy gap-aware approach.

    Parameters
    ----------
    notes:
        List of note dicts, each with at least ``"string"`` (int) and
        ``"fret"`` (int) keys. Fret conventions: > 0 = fretted, 0 = open,
        < 0 = muted/invalid (skipped).

    Returns
    -------
    dict mapping string number → finger (0 = open/muted, 1–4 = finger),
    or None when no playable assignment exists.
    """
    fretted = [n for n in notes if n.get("fret", 0) > 0]
    playable = [n for n in notes if n.get("fret", -1) >= 0]
    if not fretted:
        return {n["string"]: 0 for n in playable}

    # Group fretted strings by absolute fret.
    fret_to_strings: dict[int, list[int]] = {}
    for n in fretted:
        fret_to_strings.setdefault(n["fret"], []).append(n["string"])

    min_fret = min(fret_to_strings)
    max_fret = max(fret_to_strings)
    if max_fret - min_fret > 4:
        return None  # span too wide

    def _try_assign(use_gap: bool) -> dict[int, int] | None:
        """One assignment pass.

        use_gap=True  → gap formula (wider spans → higher fingers)
        use_gap=False → pure consecutive (1, 2, 3, 4 in fret order)
        """
        res: dict[int, int] = {}
        nf = 1  # next available finger

        for fret in sorted(fret_to_strings):
            strings = fret_to_strings[fret]
            n_str = len(strings)
            strings_desc = sorted(strings, reverse=True)
            all_adjacent = (max(strings) - min(strings) == n_str - 1)

            if n_str > 1 and nf == 1 and all_adjacent:
                # Index barre at the lowest fret — all share finger 1.
                for s in strings:
                    res[s] = 1
                nf = 2

            elif n_str == 1 or all_adjacent:
                if use_gap:
                    # Gap formula: wider fret offset → higher finger, capped at 4.
                    base = max(nf, min(fret - min_fret + 1, 4))
                else:
                    base = nf
                needed = base + n_str - 1
                if needed > 4:
                    return None
                for s, f in zip(strings_desc, range(base, base + n_str)):
                    res[s] = f
                nf = needed + 1

            else:
                # Non-adjacent strings at the same fret: consecutive fingers.
                if max(strings) - min(strings) > 4:
                    return None  # unplayable string-gap
                needed = nf + n_str - 1
                if needed > 4:
                    return None
                for s, f in zip(strings_desc, range(nf, nf + n_str)):
                    res[s] = f
                nf = needed + 1

        return res

    # Try gap formula first; fall back to consecutive if it can't fit.
    result = _try_assign(use_gap=True) or _try_assign(use_gap=False)
    if result is None:
        return None

    # Open strings get finger 0.
    for n in playable:
        if n["string"] not in result:
            result[n["string"]] = 0

    return result


def _has_barre_gap(notes: list[dict]) -> bool:
    """Return True if any finger barres non-adjacent strings with an unplayed gap.

    A barre (same finger on 2+ strings) is physically invalid when an
    intermediate string is absent from the voicing: pressing across the gap
    would sound an unintended note.
    """
    played_strings = {n["string"] for n in notes if n.get("fret", -1) >= 0}
    finger_to_strings: dict[int, list[int]] = {}
    _LETTER_FINGER = {"i": 1, "m": 2, "a": 3, "T": 0}

    for n in notes:
        raw = n.get("finger")
        if raw is None:
            continue
        try:
            fg = _LETTER_FINGER.get(str(raw), int(raw))
        except (ValueError, TypeError):
            continue
        if fg > 0:
            finger_to_strings.setdefault(fg, []).append(n["string"])

    for fg, strings in finger_to_strings.items():
        if len(strings) < 2:
            continue
        s_min, s_max = min(strings), max(strings)
        for s in range(s_min + 1, s_max):
            if s not in played_strings:
                return True
    return False


# ---------------------------------------------------------------------------
# File processing
# ---------------------------------------------------------------------------

def process_file(
    path: Path,
    dry_run: bool = False,
    quiet: bool = False,
) -> tuple[int, int]:
    """Apply algorithmic fingering to diagrams with no finger data in *path*.

    Two passes per file:
      1. Apply fingering to diagrams with all-null fingers.
      2. Fix any barre-gap errors introduced by pass 1 (or pre-existing).

    Returns
    -------
    (total_diagrams, fingerings_added)
    """
    text = path.read_text(encoding="utf-8")
    diagrams: list[dict] = json.loads(text)

    modified = False
    added = 0

    # Pass 1: populate missing fingerings.
    for d in diagrams:
        notes = d.get("notes", [])
        if not notes:
            continue
        if _has_fingering(notes):
            continue  # already fingered

        fmap = _compute_algorithmic_fingers(notes)
        if fmap is None:
            continue  # no playable assignment exists

        for n in notes:
            n["finger"] = fmap.get(n["string"], 0)
        d["fingering_source"] = "algorithmic"
        modified = True
        added += 1

    # Pass 2: fix barre-gap errors in any fingered diagram.
    for d in diagrams:
        notes = d.get("notes", [])
        if not _has_fingering(notes):
            continue
        if not _has_barre_gap(notes):
            continue
        fmap = _compute_algorithmic_fingers(notes)
        if fmap is None:
            continue
        for n in notes:
            n["finger"] = fmap.get(n["string"], 0)
        d["fingering_source"] = "algorithmic"
        modified = True

    if modified and not dry_run:
        path.write_text(json.dumps(diagrams, indent=2), encoding="utf-8")

    if not quiet and added:
        tag = " [dry run]" if dry_run else ""
        print(f"  {path.name}: added {added}/{len(diagrams)} fingerings{tag}")

    return len(diagrams), added


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="populate_fingerings_cli.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "files", nargs="*", metavar="FILE",
        help="JSON file(s) to process (e.g. a.json bb.json)",
    )
    parser.add_argument(
        "--dir", metavar="DIR",
        help="Process all *.json files in this directory",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would change without writing files",
    )
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress per-file output")
    args = parser.parse_args(argv)

    paths: list[Path] = []

    if args.dir:
        d = Path(args.dir).resolve()
        if not d.is_dir():
            print(f"ERROR: not a directory: {d}", file=sys.stderr)
            return 1
        paths.extend(sorted(d.glob("*.json")))

    for f in args.files:
        p = Path(f).resolve()
        if not p.exists():
            print(f"ERROR: file not found: {p}", file=sys.stderr)
            return 1
        paths.append(p)

    if not paths:
        parser.print_help()
        return 1

    total_diag = total_added = 0
    for path in paths:
        n_diag, n_added = process_file(path, dry_run=args.dry_run, quiet=args.quiet)
        total_diag += n_diag
        total_added += n_added

    if not args.quiet:
        tag = " [dry run]" if args.dry_run else ""
        print(
            f"\nTotal: {total_added} fingerings added across "
            f"{len(paths)} file(s) ({total_diag} diagrams){tag}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
