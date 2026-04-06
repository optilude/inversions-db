#!/usr/bin/env python3
"""Tests for populate_fingerings_cli.py and generate_inversions.py.

Run with:
    python3 test_standalone.py            # stdlib unittest
    python3 -m pytest test_standalone.py  # pytest (optional)

No external dependencies beyond Python 3.8+.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make the scripts importable from the same directory.
sys.path.insert(0, str(Path(__file__).parent))

from populate_fingerings_cli import (
    _compute_algorithmic_fingers,
    _has_barre_gap,
    _has_fingering,
    process_file,
)
from generate_inversions import (
    CHROMATIC,
    _chord_tones_for,
    _full_voicings,
    _generate_voicings,
    _inversion_label,
    _partial_voicings,
    _prefer_closed,
    _transpose_diagram,
    generate,
    note_from_fret,
    validate_chord,
)


# ===========================================================================
# Tests for populate_fingerings_cli.py
# ===========================================================================

class TestHasFingering(unittest.TestCase):
    def test_all_null(self):
        notes = [{"string": 4, "fret": 5, "finger": None},
                 {"string": 3, "fret": 5, "finger": None}]
        self.assertFalse(_has_fingering(notes))

    def test_has_real_finger(self):
        notes = [{"string": 4, "fret": 5, "finger": 2},
                 {"string": 3, "fret": 5, "finger": None}]
        self.assertTrue(_has_fingering(notes))

    def test_zero_finger_is_not_fingering(self):
        notes = [{"string": 4, "fret": 0, "finger": 0},
                 {"string": 3, "fret": 5, "finger": None}]
        self.assertFalse(_has_fingering(notes))


class TestComputeAlgorithmicFingers(unittest.TestCase):

    def _notes(self, *string_fret_pairs):
        return [{"string": s, "fret": f} for s, f in string_fret_pairs]

    def test_single_fretted_note(self):
        # One fretted note on string 4, fret 5.
        notes = self._notes((4, 5))
        result = _compute_algorithmic_fingers(notes)
        self.assertEqual(result, {4: 1})

    def test_open_string_only(self):
        # All open strings → all get finger 0.
        notes = self._notes((4, 0), (3, 0))
        result = _compute_algorithmic_fingers(notes)
        self.assertEqual(result, {4: 0, 3: 0})

    def test_adjacent_lowest_fret_barre(self):
        # Strings 4,3,2 all at fret 5 → index barre, finger 1 for all.
        notes = self._notes((4, 5), (3, 5), (2, 5))
        result = _compute_algorithmic_fingers(notes)
        self.assertEqual(result[4], 1)
        self.assertEqual(result[3], 1)
        self.assertEqual(result[2], 1)

    def test_span_too_wide(self):
        # Frets 5 and 10 → span of 5, exceeds max.
        notes = self._notes((4, 5), (3, 10))
        result = _compute_algorithmic_fingers(notes)
        self.assertIsNone(result)

    def test_three_note_equal_spacing(self):
        # Frets [4, 6, 8] — equal 2-fret gaps. Gap formula would give fingers
        # 1, 3, 5 (impossible). Consecutive fallback gives 1, 2, 3.
        notes = self._notes((4, 4), (3, 6), (2, 8))
        result = _compute_algorithmic_fingers(notes)
        self.assertIsNotNone(result)
        # All fingers should be 1-4.
        for s, f in result.items():
            self.assertLessEqual(f, 4)

    def test_with_open_string(self):
        # Open string + two fretted strings.
        notes = self._notes((6, 0), (5, 5), (4, 7))
        result = _compute_algorithmic_fingers(notes)
        self.assertIsNotNone(result)
        self.assertEqual(result[6], 0)   # open → finger 0
        self.assertGreater(result[5], 0)  # fretted → has a finger

    def test_m7b5_1st_inv_v3(self):
        # Specific regression test: strings 5,4,3,2,1 at frets 6,x,5,7,6.
        # Expected: fingering 020143 (finger order: s5=0,s4=-,s3=2,s2=0... wait)
        # The real case: strings [5,3,2,1] at frets [6,5,7,6], with s5=0 pattern.
        # Actually the specific case is: notes on strings 5,1 at same fret with gap.
        # This tests that string gap > 4 rejection doesn't fire for gap=4.
        notes = [
            {"string": 5, "fret": 6},
            {"string": 3, "fret": 5},
            {"string": 2, "fret": 7},
            {"string": 1, "fret": 6},
        ]
        result = _compute_algorithmic_fingers(notes)
        # Should find a valid fingering (gap=4 is now accepted).
        self.assertIsNotNone(result)
        for f in result.values():
            self.assertLessEqual(f, 4)


class TestHasBarreGap(unittest.TestCase):

    def test_no_barre(self):
        notes = [
            {"string": 4, "fret": 5, "finger": 1},
            {"string": 3, "fret": 6, "finger": 2},
        ]
        self.assertFalse(_has_barre_gap(notes))

    def test_adjacent_barre_ok(self):
        # Strings 4,3 both at fret 5 with finger 1 — adjacent, no gap.
        notes = [
            {"string": 4, "fret": 5, "finger": 1},
            {"string": 3, "fret": 5, "finger": 1},
        ]
        self.assertFalse(_has_barre_gap(notes))

    def test_non_adjacent_barre_gap(self):
        # Strings 4,2 with same finger but string 3 is absent → gap.
        notes = [
            {"string": 4, "fret": 5, "finger": 1},
            {"string": 2, "fret": 5, "finger": 1},
        ]
        self.assertTrue(_has_barre_gap(notes))

    def test_non_adjacent_all_played(self):
        # Strings 4,3,2 all played with finger 1 on 4 and 2, finger 2 on 3.
        # Same finger (1) on strings 4 and 2, but string 3 IS played.
        notes = [
            {"string": 4, "fret": 5, "finger": 1},
            {"string": 3, "fret": 6, "finger": 2},
            {"string": 2, "fret": 5, "finger": 1},
        ]
        # String 3 is in played_strings, so no gap.
        self.assertFalse(_has_barre_gap(notes))


class TestProcessFile(unittest.TestCase):

    def _write_json(self, path: Path, data: list[dict]) -> None:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _read_json(self, path: Path) -> list[dict]:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_adds_fingering_to_unfingered(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.json"
            diagrams = [
                {
                    "chord_type": "dim",
                    "root": "A",
                    "notes": [
                        {"string": 4, "fret": 7, "note_name": "A", "finger": None},
                        {"string": 3, "fret": 8, "note_name": "C", "finger": None},
                        {"string": 2, "fret": 9, "note_name": "Eb", "finger": None},
                    ],
                }
            ]
            self._write_json(path, diagrams)

            n_diag, n_added = process_file(path)

            self.assertEqual(n_diag, 1)
            self.assertEqual(n_added, 1)
            result = self._read_json(path)
            fingers = [n["finger"] for n in result[0]["notes"]]
            self.assertTrue(any(f and f > 0 for f in fingers))

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.json"
            original_data = [
                {
                    "chord_type": "aug",
                    "root": "C",
                    "notes": [
                        {"string": 3, "fret": 5, "note_name": "C", "finger": None},
                        {"string": 2, "fret": 5, "note_name": "E", "finger": None},
                        {"string": 1, "fret": 5, "note_name": "G#", "finger": None},
                    ],
                }
            ]
            self._write_json(path, original_data)
            original_text = path.read_text()

            process_file(path, dry_run=True)

            # File should be unchanged.
            self.assertEqual(path.read_text(), original_text)

    def test_skips_already_fingered(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.json"
            diagrams = [
                {
                    "chord_type": "major",
                    "root": "C",
                    "fingering_source": "chords_db",
                    "notes": [
                        {"string": 4, "fret": 5, "note_name": "C", "finger": 3},
                        {"string": 3, "fret": 5, "note_name": "E", "finger": 2},
                        {"string": 2, "fret": 5, "note_name": "G", "finger": 1},
                    ],
                }
            ]
            self._write_json(path, diagrams)

            _, n_added = process_file(path, quiet=True)
            self.assertEqual(n_added, 0)


# ===========================================================================
# Tests for generate_inversions.py
# ===========================================================================

class TestMusicTheory(unittest.TestCase):

    def test_note_from_fret(self):
        # Open strings.
        self.assertEqual(note_from_fret(6, 0), "E")   # low E
        self.assertEqual(note_from_fret(5, 0), "A")
        self.assertEqual(note_from_fret(1, 0), "E")   # high e
        # Fretted.
        self.assertEqual(note_from_fret(6, 1), "F")
        self.assertEqual(note_from_fret(6, 12), "E")  # octave

    def test_chord_tones_dim(self):
        tones = _chord_tones_for("A", "dim")
        self.assertEqual(tones, ["A", "C", "D#"])

    def test_chord_tones_aug(self):
        tones = _chord_tones_for("C", "aug")
        self.assertEqual(tones, ["C", "E", "G#"])

    def test_validate_chord_dim(self):
        valid, expected = validate_chord(["A", "C", "D#"], "A", "dim")
        self.assertTrue(valid)
        self.assertEqual(expected, {"A", "C", "D#"})

    def test_validate_chord_invalid(self):
        valid, _ = validate_chord(["A", "C", "D"], "A", "dim")
        self.assertFalse(valid)   # D not in A dim


class TestGenerateVoicings(unittest.TestCase):

    def test_dim_generates_voicings(self):
        tones = _chord_tones_for("A", "dim")
        voicings = _generate_voicings("dim", [4, 3, 2], tones, "A")
        self.assertGreater(len(voicings), 0)

    def test_each_voicing_has_correct_structure(self):
        tones = _chord_tones_for("A", "dim")
        voicings = _generate_voicings("dim", [4, 3, 2], tones, "A")
        for v in voicings:
            self.assertIn("notes", v)
            self.assertIn("chord_type", v)
            self.assertEqual(v["chord_type"], "dim")
            self.assertEqual(v["root"], "A")
            self.assertTrue(v["valid"])
            # Check no repeated pitch classes.
            pitch_classes = [CHROMATIC.index(n["note_name"]) for n in v["notes"]]
            self.assertEqual(len(pitch_classes), len(set(pitch_classes)),
                             f"Repeated pitch class in {v['notes']}")

    def test_dim_has_all_inversions(self):
        tones = _chord_tones_for("A", "dim")
        voicings = _generate_voicings("dim", [4, 3, 2], tones, "A")
        labels = {v["inversion_label"] for v in voicings}
        # Should have at least root position and one inversion.
        self.assertIn("Root Position", labels)
        self.assertTrue(len(labels) >= 2)

    def test_fret_span_within_limit(self):
        tones = _chord_tones_for("A", "aug7")
        voicings = _generate_voicings("aug7", [6, 5, 4, 3], tones, "A")
        for v in voicings:
            frets = [n["fret"] for n in v["notes"] if n["fret"] > 0]
            if frets:
                self.assertLessEqual(max(frets) - min(frets), 5,
                                     f"Span too wide: {frets}")


class TestPreferClosed(unittest.TestCase):

    def _make_voicing(self, cat, label, omitted, frets, has_open):
        notes = [{"string": i + 1, "fret": f} for i, f in enumerate(frets)]
        return {
            "category": cat,
            "inversion_label": label,
            "omitted_chord_tones": omitted,
            "notes": notes,
            "starting_fret": min(f for f in frets if f > 0) if any(f > 0 for f in frets) else 0,
        }

    def test_prefers_closed_over_open(self):
        closed = self._make_voicing("A", "Root Position", [], [5, 7, 9], False)
        open_v = self._make_voicing("A", "Root Position", [], [0, 2, 4], True)
        result = _prefer_closed([open_v, closed])
        self.assertEqual(len(result), 1)
        # Should keep closed (no open strings).
        kept = result[0]
        self.assertFalse(any(n["fret"] == 0 for n in kept["notes"]))

    def test_picks_lowest_fret_among_closed(self):
        high = self._make_voicing("A", "Root Position", [], [10, 11, 12], False)
        low = self._make_voicing("A", "Root Position", [], [2, 3, 4], False)
        result = _prefer_closed([high, low])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["starting_fret"], 2)


class TestFullAndPartialVoicings(unittest.TestCase):

    def test_dim_full_voicings(self):
        voicings = _full_voicings("dim", "A", [[4, 3, 2]])
        self.assertGreater(len(voicings), 0)
        for v in voicings:
            # Full voicings have no omitted tones.
            played = {n["note_name"] for n in v["notes"]}
            expected = set(_chord_tones_for("A", "dim"))
            self.assertEqual(played, expected)

    def test_dim7_partial_voicings(self):
        voicings = _partial_voicings("dim7", "A", [[4, 3, 2]])
        self.assertGreater(len(voicings), 0)
        for v in voicings:
            # Partial voicings omit the root.
            self.assertIn("A", v["omitted_chord_tones"])


class TestTransposeVoicings(unittest.TestCase):

    def test_transpose_preserves_chord_type(self):
        tones = _chord_tones_for("A", "dim")
        voicings = _generate_voicings("dim", [4, 3, 2], tones, "A")
        self.assertTrue(voicings)
        v = voicings[0]
        transposed = _transpose_diagram(v, 3, "C")
        self.assertEqual(transposed["chord_type"], "dim")
        self.assertEqual(transposed["root"], "C")

    def test_transpose_to_c_dim(self):
        # A dim transposed +3 = C dim. Notes should match C dim chord tones.
        tones = _chord_tones_for("A", "dim")
        voicings = _full_voicings("dim", "A", [[4, 3, 2]])
        self.assertTrue(voicings)
        transposed = _transpose_diagram(voicings[0], 3, "C")
        played = {n["note_name"] for n in transposed["notes"]}
        c_dim_tones = set(_chord_tones_for("C", "dim"))
        self.assertTrue(played.issubset(c_dim_tones),
                        f"{played} not a subset of {c_dim_tones}")


class TestGenerate(unittest.TestCase):

    def test_generates_expected_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            generate(out, quiet=True)

            # Should have one file per root per family for both families.
            for family in ("diminished", "augmented"):
                for root in ["a", "bb", "c#", "c", "g"]:
                    path = out / f"{root}_{family}.json"
                    self.assertTrue(path.exists(), f"Missing: {path.name}")

    def test_all_voicings_are_valid(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            generate(out, quiet=True)

            for path in out.glob("*_diminished.json"):
                data = json.loads(path.read_text())
                for d in data:
                    self.assertTrue(d.get("valid"), f"Invalid in {path.name}: {d}")

            for path in out.glob("*_augmented.json"):
                data = json.loads(path.read_text())
                for d in data:
                    self.assertTrue(d.get("valid"), f"Invalid in {path.name}: {d}")

    def test_no_repeated_pitch_classes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            generate(out, quiet=True)

            for path in list(out.glob("*_diminished.json"))[:3]:
                data = json.loads(path.read_text())
                for d in data:
                    pcs = [CHROMATIC.index(n["note_name"]) for n in d["notes"]]
                    self.assertEqual(len(pcs), len(set(pcs)),
                                     f"Repeated pitch class in {path.name}")

    def test_voicing_counts_consistent_across_keys(self):
        """All keys should have the same number of voicings per chord type."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            generate(out, quiet=True)

            for family in ("diminished", "augmented"):
                counts_by_root: dict[str, dict[str, int]] = {}
                for path in sorted(out.glob(f"*_{family}.json")):
                    data = json.loads(path.read_text())
                    root = path.stem.split("_")[0]
                    by_type: dict[str, int] = {}
                    for d in data:
                        ct = d["chord_type"]
                        by_type[ct] = by_type.get(ct, 0) + 1
                    counts_by_root[root] = by_type

                # All roots should have the same type-counts as the A root.
                a_counts = counts_by_root.get("a", {})
                for root, counts in counts_by_root.items():
                    self.assertEqual(
                        counts, a_counts,
                        f"{family} count mismatch: a vs {root}: {a_counts} vs {counts}",
                    )


# ===========================================================================
# Runner
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
