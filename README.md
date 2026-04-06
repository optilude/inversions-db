# Guitar Inversions Database

A comprehensive dataset of guitar chord voicings focusing on inversions across all 17 chromatic keys and 32 chord types — nearly 11,000 voicings in total.

Includes a self-contained interactive chord book viewer (`index.html`) and scripts to regenerate both the database and the viewer from the raw data. Also includes standalone tools to generate diminished/augmented voicings and populate fingerings algorithmically.

**Note:** The focus here is inversions with no repeated notes, rather than standard chords, which often have the same note repeated more than once.

The format is similar to [chords-db](https://github.com/tombatossals/chords-db), which focuses more on traditional chord shapes.

---

## Contents

| File | Description |
|---|---|
| `a.json` … `b.json` | Per-key voicing data (17 keys: all naturals, flats, and sharps) |
| `inversions-db.json` | All keys combined in a single file (pre-built) |
| `index.html` | Interactive chord browser (pre-built, self-contained) |
| `build_db.py` | Regenerates `inversions-db.json` from the key files |
| `chord_book_cli.py` | Regenerates `index.html` from the key files |
| `generate_inversions.py` | Standalone generator for diminished/augmented voicings |
| `populate_fingerings_cli.py` | Standalone tool to add algorithmic fingerings to voicing files |
| `test_standalone.py` | Tests for the two standalone tools above |
| `.nojekyll` | Tells GitHub Pages to serve the site as plain HTML (no Jekyll processing) |
| `svguitar.umd.js` | Bundled [SVGuitar](https://github.com/omnibrain/svguitar) library (v2.5.1) |

---

## Quick start

Open `index.html` in any browser — no server or installation required.

Or visit the hosted version at **https://optilude.github.io/inversions-db/**

---

## Chord coverage

**32 chord types** across **17 keys** (all 12 naturals/flats plus C#, D#, F#, G#, A#):

| Family | Types |
|---|---|
| Triads | `major`, `minor`, `dim`, `aug` |
| Major | `maj7`, `maj9`, `maj6` (6), `maj6_9` (6/9), `major_cluster`, `maj7_shell`, `maj6_shell` |
| Minor | `m7`, `m9`, `m6`, `m6_9`, `mmaj7`, `m7b5`, `minor_cluster`, `m7_shell`, `m6_shell` |
| Dominant | `7`, `dom9` (9), `dom11` (11), `7b9`, `7#9`, `7#5`, `dom_cluster`, `7_shell` |
| Diminished | `dim7`, `dim7_shell` |
| Augmented | `aug7`, `aug9` |

All voicings are provided in all inversions (root position, 1st, 2nd, 3rd inversion as applicable) across practical string groups.

Note annotations in `index.html` use the correct enharmonic spelling per key — flat keys display Eb, Bb etc.; sharp keys display D#, A# etc.

---

## Data format

### Per-key files (`a.json` etc.)

17 files, one per key (C, C#, Db, D, D#, Eb, E, F, F#, Gb, G, G#, Ab, A, A#, Bb, B).
Each file contains an array of voicing objects:

```json
{
  "chord_type":       "major",
  "inversion_number": 0,
  "starting_fret":    5,
  "root":             "A",
  "notes": [
    { "string": 5, "fret": 7, "note_name": "E", "finger": "3" },
    { "string": 4, "fret": 7, "note_name": "A", "finger": "4" },
    { "string": 3, "fret": 6, "note_name": "C#", "finger": "2" }
  ],
  "omitted_chord_tones": [],
  "substitution":        null,
  "duplicate_of":        null
}
```

`inversion_number`: 0 = root position, 1 = 1st inversion, 2 = 2nd inversion, -1 = unknown (bass note is an extension tone).

### `inversions-db.json`

Structured for programmatic consumption, compatible with the [chords-db](https://github.com/tombatossals/chords-db) schema:

```json
{
  "C": [
    {
      "key": "C",
      "suffix": "major",
      "positions": [
        {
          "frets":     [-1, 3, 2, 0, 1, 0],
          "fingers":   [0, 3, 2, 0, 1, 0],
          "baseFret":  1,
          "barres":    [],
          "inversion": 0
        }
      ]
    }
  ]
}
```

**Fret encoding:** `-1` = muted, `0` = open string, `1+` = fret relative to `baseFret` (so `baseFret` itself → 1).  
Index 0 = string 6 (low E), index 5 = string 1 (high e).

---

## Standalone tools

Two self-contained scripts are provided for downstream use. Neither requires any
external packages beyond Python 3.8+, and neither depends on the rest of the
source repository.

### `generate_inversions.py` — Diminished / augmented voicing generator

Algorithmically generates all practical guitar voicings for diminished and
augmented chord types across all 12 chromatic roots.

**Chord types generated:**

| Type | Tones | Strategy |
|---|---|---|
| `dim` | R, b3, d5 | Full 3-note voicings on all 10 string groups |
| `dim7` | R, b3, d5, d7 | Full 4-note + partial (root omitted) 3-note |
| `m7b5` | R, b3, d5, m7 | Full 4-note + partial (root omitted) 3-note |
| `aug` | R, M3, #5 | Full 3-note voicings on all 10 string groups |
| `aug7` | R, M3, #5, m7 | Full 4-note + partial (root omitted) 3-note |
| `aug9` | R, M9, M3, #5, m7 | Partial (root omitted) 4-note voicings only |

Each voicing has one chord tone per string (no repeated pitch classes), all
inversions covered per string group, and fret spans ≤ 5 frets. Closed-position
voicings are preferred over open-string equivalents.

**Usage:**

```bash
# Generate to ./output/ subdirectory:
python3 generate_inversions.py

# Custom output directory:
python3 generate_inversions.py --output /path/to/dir

# Show per-chord-type counts:
python3 generate_inversions.py --summary

python3 generate_inversions.py --help
```

**Output files** (one per root per family):
- `{root}_diminished.json` — dim, dim7, m7b5 voicings
- `{root}_augmented.json` — aug, aug7, aug9 voicings

Each file follows the same schema as the per-key files in this directory.

---

### `populate_fingerings_cli.py` — Algorithmic fingering tool

Reads one or more per-key JSON files and fills in finger assignments for any
voicing where all finger fields are `null`. Useful for post-processing
algorithmically generated voicings that have no fingering data.

**The algorithm:**

Fretted notes are processed in ascending fret order. Two passes are tried:

1. **Gap formula** (`finger = max(next_finger, fret - min_fret + 1)`, capped at 4):
   spaces fingers naturally across the fretboard.
2. **Consecutive fallback** (1, 2, 3, 4 in fret order): used when the gap
   formula over-allocates (e.g. three notes with equal 2-fret gaps).

Special cases:
- Adjacent strings at the lowest fret → index barre (all finger 1)
- Non-adjacent strings at the same fret → consecutive fingers
- String gap > 4 on same fret, or any finger > 4 → no assignment (`null`)

A final pass fixes any barre-gap errors (same finger assigned to non-adjacent
strings with an unplayed string in the gap).

**Usage:**

```bash
# Populate specific files:
python3 populate_fingerings_cli.py a.json bb.json

# Populate all *.json files in a directory:
python3 populate_fingerings_cli.py --dir /path/to/key/files/

# Preview without writing:
python3 populate_fingerings_cli.py --dry-run a.json

python3 populate_fingerings_cli.py --help
```

---

### `test_standalone.py` — Tests

36 unit tests covering both standalone tools. Run with:

```bash
python3 test_standalone.py           # stdlib unittest
python3 -m pytest test_standalone.py # pytest (optional)
```

Tests verify: fingering algorithm correctness, barre-gap detection, file
processing (including dry-run), voicing generation (valid chord tones, no
repeated pitch classes, all inversions), transposition, and cross-key
consistency.

---

## Regenerating the outputs

No dependencies beyond Python 3.8+.

```bash
# Rebuild inversions-db.json from the key files:
python3 build_db.py

# Rebuild index.html from the key files:
python3 chord_book_cli.py

# Custom paths:
python3 build_db.py --input . --output inversions-db.json
python3 chord_book_cli.py --input . --output index.html

# Help:
python3 build_db.py --help
python3 chord_book_cli.py --help
```

### Testing in a clean environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python3 build_db.py
python3 chord_book_cli.py
# Open index.html in your browser
```

---

## Chord book viewer

`index.html` is a fully self-contained single-page application — open it directly in any modern browser, no server required.

Features:
- Browse all 17 keys (naturals, flats, and sharps) and 32 chord types
- Voicings grouped by inversion (root position first)
- Three dot-annotation modes: **Fingering**, **Notes**, **Intervals**
- Correct enharmonic spelling per key (Eb not D# in flat keys, D# not Eb in sharp keys)
- Chord types organised in logical groups (Triads, Major, Minor, Dominant, Diminished, Augmented)

---

## Publishing on GitHub Pages

The chord book is hosted at **https://optilude.github.io/inversions-db/** via GitHub Pages.
This section explains how to set that up from scratch if you fork or recreate the repository.

### First-time setup

**1. Create the repository**

Create a new public repository on GitHub named `inversions-db` under your account or organisation.

**2. Initialise from this directory**

From inside the `output/inversions-db/` directory (this folder):

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/optilude/inversions-db.git
git push -u origin main
```

**3. Enable GitHub Pages**

In the repository on GitHub:
- Go to **Settings → Pages**
- Under **Source**, choose **Deploy from a branch**
- Select branch **`main`**, folder **`/ (root)`**
- Click **Save**

GitHub will build and deploy the site. After a minute or two the chord book
will be live at `https://<your-username>.github.io/inversions-db/`.

The `.nojekyll` file already in this directory tells GitHub Pages to serve
the HTML directly without running it through Jekyll — this is required for
plain static sites and avoids any build step.

---

### Updating the site

After regenerating data or rebuilding the HTML:

```bash
# Rebuild index.html (picks up any data changes):
python3 chord_book_cli.py

# Rebuild the combined database:
python3 build_db.py

# Commit and push — GitHub Pages deploys automatically:
git add .
git commit -m "Rebuild chord book"
git push
```

Deployment typically completes within 1–2 minutes. Progress is visible under
**Actions** in the GitHub repository.

---

### Keeping the standalone repo in sync with the source project

If you are working from the parent `projects/inversions/` repository, you can
push just this subdirectory to the standalone repo using `git subtree`:

```bash
# From the root of the parent repository:
git subtree push --prefix=projects/inversions/output/inversions-db \
    https://github.com/optilude/inversions-db.git main
```

Or maintain it manually by copying changed files and committing in the
`inversions-db` repo.

---

## License

Data and code are released under the [MIT License](LICENSE).

SVGuitar (bundled as `svguitar.umd.js`) is © [omnibrain](https://github.com/omnibrain/svguitar), also MIT licensed.
