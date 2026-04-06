#!/usr/bin/env python3
"""
chord_book_cli.py — Generate a self-contained chord book HTML from per-key JSON files.

Reads per-key voicing files
(a.json, bb.json, etc.) and writes a single interactive HTML file for
visual inspection of chord shapes.

Usage
-----
    python3 chord_book_cli.py [--input DIR] [--output FILE] [-q]

Options
-------
    --input  DIR   Directory containing a.json, bb.json … b.json  [default: same directory as this script]
    --output FILE  Output HTML path  [default: index.html in the script's directory]
    -q, --quiet    Suppress progress output

The script is self-contained: it bundles SVGuitar (fetched once from
unpkg.com and cached as svguitar.umd.js next to this script). No Python
packages beyond the standard library are required.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Chord type catalogue
# ---------------------------------------------------------------------------

# Display name for each internal chord_type key
CHORD_LABELS: dict[str, str] = {
    # Triads
    "major":         "Major",
    "minor":         "Minor",
    "dim":           "Diminished",
    "aug":           "Augmented",
    # Major family
    "maj7":          "Maj7",
    "maj9":          "Maj9",
    "maj6":          "Maj6",
    "maj6_9":        "Maj6/9",
    "major_cluster": "Maj Cluster",
    "maj7_shell":    "Maj7 Shell",
    "maj6_shell":    "Maj6 Shell",
    # Minor family
    "m7":            "m7",
    "m9":            "m9",
    "m6":            "m6",
    "m6_9":          "m6/9",
    "mmaj7":         "mMaj7",
    "m7b5":          "m7b5",
    "minor_cluster": "m Cluster",
    "m7_shell":      "m7 Shell",
    "m6_shell":      "m6 Shell",
    # Dominant family
    "7":             "Dom7",
    "dom9":          "Dom9",
    "dom11":         "Dom11",
    "7b9":           "7b9",
    "7#9":           "7#9",
    "7#5":           "7#5",
    "dom_cluster":   "Dom Cluster",
    "7_shell":       "Dom7 Shell",
    # Diminished family
    "dim7":          "Dim7",
    "dim7_shell":    "Dim7 Shell",
    # Augmented family
    "aug7":          "Aug7",
    "aug9":          "Aug9",
}

# Ordered groups for the chord type selector
CHORD_TYPE_GROUPS: list[tuple[str, list[str]]] = [
    ("Triads",     ["major", "minor", "dim", "aug"]),
    ("Major",      ["maj7", "maj9", "maj6", "maj6_9", "major_cluster",
                    "maj7_shell", "maj6_shell"]),
    ("Minor",      ["m7", "m9", "m6", "m6_9", "mmaj7", "minor_cluster",
                    "m7_shell", "m6_shell"]),
    ("Dominant",   ["7", "dom9", "dom11", "7b9", "7#9", "7#5", "dom_cluster",
                    "7_shell"]),
    ("Diminished", ["dim7", "m7b5", "dim7_shell"]),
    ("Augmented",  ["aug7", "aug9"]),
]

# Flat keys only, in circle-of-fifths order
KEYS: list[tuple[str, str]] = [
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

INV_HEADINGS = {
    0: "Root Position",
    1: "1st Inversion",
    2: "2nd Inversion",
    3: "3rd Inversion",
    4: "4th Inversion",
}

# ---------------------------------------------------------------------------
# SVGuitar bundle (cached locally)
# ---------------------------------------------------------------------------

_SVGUITAR_URL = "https://unpkg.com/svguitar@2.5.1/dist/svguitar.umd.js"
_SVGUITAR_CACHE = Path(__file__).parent / "svguitar.umd.js"


def _load_svguitar() -> str:
    if _SVGUITAR_CACHE.exists():
        return _SVGUITAR_CACHE.read_text(encoding="utf-8")
    print(f"Downloading SVGuitar from {_SVGUITAR_URL} …", file=sys.stderr)
    js = urllib.request.urlopen(_SVGUITAR_URL).read().decode("utf-8")  # noqa: S310
    _SVGUITAR_CACHE.write_text(js, encoding="utf-8")
    return js


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_key(input_dir: Path, filename: str) -> list[dict]:
    path = input_dir / filename
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def build_data(input_dir: Path) -> dict[str, dict[str, list[dict]]]:
    """Return {key_label: {chord_type: [diagram, ...]}} sorted by inversion."""
    result: dict[str, dict[str, list[dict]]] = {}

    for file_prefix, key_label in KEYS:
        diagrams = load_key(input_dir, f"{file_prefix}.json")

        by_type: dict[str, list[dict]] = defaultdict(list)
        for d in diagrams:
            ct = d.get("chord_type")
            if not ct:
                continue
            by_type[ct].append({
                "n":    d["notes"],
                "sf":   d.get("starting_fret", 1),
                "inv":  d.get("inversion_number"),   # int or None
                "r":    d.get("root"),               # root note name
                "ot":   d.get("omitted_chord_tones") or [],
                "sub":  d.get("substitution"),
                "dup":  d.get("duplicate_of"),
            })

        # Sort each chord type's voicings by inversion_number:
        # 0 → 1 → 2 → 3 → 4 → None/-1 (unknown) last
        # Then, sort in ascending fret order based on starting_fret
        def inv_sort_key(d: dict) -> tuple[int, int]:
            v = d["inv"]
            inv = 999 if v is None or v == -1 else v
            return (inv, d["sf"])

        result[key_label] = {
            ct: sorted(voicings, key=inv_sort_key)
            for ct, voicings in by_type.items()
        }

    return result


# ---------------------------------------------------------------------------
# Build chord type groups for selector (only include types present in data)
# ---------------------------------------------------------------------------

def build_groups(data: dict) -> list[tuple[str, list[str]]]:
    """Return groups containing only chord types that exist in the dataset."""
    present: set[str] = set()
    for key_data in data.values():
        present.update(key_data.keys())

    groups = []
    covered: set[str] = set()
    for group_name, types in CHORD_TYPE_GROUPS:
        filtered = [ct for ct in types if ct in present]
        if filtered:
            groups.append((group_name, filtered))
            covered.update(filtered)

    # Catch any chord types not in our catalogue
    extras = sorted(present - covered)
    if extras:
        groups.append(("Other", extras))

    return groups


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def _groups_js(groups: list[tuple[str, list[str]]]) -> str:
    return json.dumps([{"label": g, "types": t} for g, t in groups])


HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Book of Inversions</title>
<script>__SVGUITAR__</script>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, sans-serif; background: #f2f4f8; color: #222; }

/* ---- Header ---- */
#header {
  position: sticky; top: 0; z-index: 100;
  background: #1b2a3b; color: #dde6f0;
  padding: 10px 16px 8px; display: flex; flex-direction: column; gap: 8px;
  box-shadow: 0 2px 10px rgba(0,0,0,.35);
}
#header h1 { font-size: .9rem; font-weight: 700; letter-spacing: .06em;
             color: #7fb3e0; text-transform: uppercase; }

.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }

/* Key buttons */
#keys { display: flex; flex-wrap: wrap; gap: 4px; }
.key-btn {
  padding: 4px 12px; border-radius: 4px;
  border: 1px solid #3a5570; background: #243550; color: #b0cce8;
  cursor: pointer; font-size: .8rem; font-weight: 600;
  transition: background .12s, color .12s;
}
.key-btn:hover  { background: #2e4a6a; }
.key-btn.active { background: #1d6fbf; border-color: #5aaff0; color: #fff; }

/* Chord selector */
label.ctrl { font-size: .78rem; color: #8aa8c4; }
select#chord-type {
  padding: 5px 10px; border-radius: 4px;
  border: 1px solid #3a5570; background: #243550; color: #b0cce8;
  font-size: .82rem; cursor: pointer; min-width: 160px;
}
optgroup { font-weight: 700; }

/* Annotation buttons */
#annotation-btns { display: flex; gap: 0; border-radius: 4px; overflow: hidden; border: 1px solid #3a5570; }
.ann-btn {
  padding: 5px 11px; border: none; background: #243550; color: #b0cce8;
  font-size: .78rem; font-weight: 500; cursor: pointer;
  transition: background .12s, color .12s;
  border-right: 1px solid #3a5570;
}
.ann-btn:last-child { border-right: none; }
.ann-btn:hover  { background: #2e4a6a; }
.ann-btn.active { background: #1d6fbf; color: #fff; }

/* Count */
#count { font-size: .72rem; color: #5a80a0; padding-top: 2px; }

/* ---- Content ---- */
#content { padding: 16px; }

/* Inversion section */
.inv-section { margin-bottom: 24px; }
.inv-heading {
  font-size: .72rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: .08em; color: #5a80b0; border-bottom: 1px solid #d0d8e8;
  padding-bottom: 4px; margin-bottom: 10px;
}

/* Card grid */
.card-grid { display: flex; flex-wrap: wrap; gap: 10px; }

/* Chord card */
.card {
  background: #fff; border-radius: 8px; width: 190px;
  padding: 10px 10px 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,.10);
  display: flex; flex-direction: column; align-items: center;
}
.card.dup { opacity: .5; }
.diagram  { width: 170px; }

.card-meta {
  margin-top: 4px; font-size: .64rem; color: #666;
  text-align: center; display: flex; flex-wrap: wrap;
  justify-content: center; gap: 3px; line-height: 1.6;
}
.pill {
  display: inline-block; padding: 0 5px; border-radius: 3px;
  font-size: .62rem; font-weight: 600;
}
.pill.omit { background: #ede9fe; color: #5b21b6; }
.pill.sub  { background: #fef3c7; color: #92400e; }
.pill.dup  { background: #f1f5f9; color: #94a3b8; }
</style>
</head>
<body>

<div id="header">
  <div class="row">
    <h1>Book of Inversions</h1>
    <div id="keys"></div>
  </div>
  <div class="row">
    <label class="ctrl" for="chord-type">Chord type:</label>
    <select id="chord-type"></select>
    <span style="width:16px"></span>
    <label class="ctrl">Dots:</label>
    <div id="annotation-btns">
      <button class="ann-btn active" data-mode="fingering">Fingering</button>
      <button class="ann-btn" data-mode="notes">Notes</button>
      <button class="ann-btn" data-mode="intervals">Intervals</button>
    </div>
  </div>
  <div id="count"></div>
</div>

<div id="content"></div>

<script>
// ---- Data ----------------------------------------------------------------
const DATA   = __DATA__;
const GROUPS = __GROUPS__;
const KEYS   = __KEYS__;
const INV_HEADINGS = __INV_HEADINGS__;

// ---- State ---------------------------------------------------------------
let currentKey        = KEYS[0][1];
let currentType       = null;
let annotationMode    = 'fingering';  // 'fingering' | 'notes' | 'intervals'

// ---- Music theory (for interval annotation) ------------------------------
const CHROMATIC = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"];
const FLAT_CHROMATIC = ["C","Db","D","Eb","E","F","Gb","G","Ab","A","Bb","B"];
const ENHARMONICS = { Bb:"A#", Eb:"D#", Ab:"G#", Db:"C#", Gb:"F#", Cb:"B", Fb:"E" };
const INTERVAL_NAMES = ["R","b2","2","b3","3","4","#4","5","#5","6","b7","7"];
const DEGREE_NAMES = {"R":"root","b2":"b2nd","2":"2nd","b3":"b3rd","3":"3rd","4":"4th","#4":"#4th","5":"5th","#5":"#5th","6":"6th","b7":"b7th","7":"7th"};
// Keys that prefer flat spellings for note display
const FLAT_KEYS = new Set(["C","F","Bb","Eb","Ab","Db","Gb"]);

function toSharp(name) { return ENHARMONICS[name] || name; }

function displayNote(noteName, key) {
  const sharp = toSharp(noteName);
  const idx = CHROMATIC.indexOf(sharp);
  if (idx < 0) return noteName;
  return FLAT_KEYS.has(key) ? FLAT_CHROMATIC[idx] : CHROMATIC[idx];
}

function noteToInterval(noteName, rootName) {
  const ni = CHROMATIC.indexOf(toSharp(noteName));
  const ri = CHROMATIC.indexOf(toSharp(rootName));
  if (ni < 0 || ri < 0) return '?';
  return INTERVAL_NAMES[(ni - ri + 12) % 12];
}

function omitLabel(ot, root) {
  return 'No ' + ot.map(n => DEGREE_NAMES[noteToInterval(n, root)] || n).join(', ');
}

// ---- Key buttons ---------------------------------------------------------
const keysEl = document.getElementById('keys');
KEYS.forEach(([, label]) => {
  const btn = document.createElement('button');
  btn.className = 'key-btn';
  btn.textContent = label;
  btn.onclick = () => selectKey(label);
  keysEl.appendChild(btn);
});

function selectKey(label) {
  currentKey = label;
  document.querySelectorAll('.key-btn')
    .forEach(b => b.classList.toggle('active', b.textContent === label));
  render();
}

// ---- Chord type selector -------------------------------------------------
const selectEl = document.getElementById('chord-type');
GROUPS.forEach(({ label, types }) => {
  const og = document.createElement('optgroup');
  og.label = label;
  types.forEach(ct => {
    const opt = document.createElement('option');
    opt.value = ct;
    opt.textContent = ct;  // will be overwritten below if label available
    og.appendChild(opt);
  });
  selectEl.appendChild(og);
});

// Set display labels from CHORD_LABELS (embedded below)
const CHORD_LABELS = __CHORD_LABELS__;
selectEl.querySelectorAll('option').forEach(o => {
  if (CHORD_LABELS[o.value]) o.textContent = CHORD_LABELS[o.value];
});

selectEl.onchange = () => { currentType = selectEl.value; render(); };

// ---- Annotation mode buttons ---------------------------------------------
document.querySelectorAll('.ann-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    annotationMode = btn.dataset.mode;
    document.querySelectorAll('.ann-btn').forEach(b => b.classList.toggle('active', b === btn));
    render();
  });
});

function setType(ct) {
  currentType = ct;
  selectEl.value = ct;
}

// ---- SVGuitar helpers ----------------------------------------------------
function getDotText(n, root, mode, displayKey) {
  if (!n) return undefined;
  if (mode === 'notes')     return displayNote(n.note_name, displayKey);
  if (mode === 'intervals') return noteToInterval(n.note_name, root);
  if (mode === 'fingering') {
    const f = parseInt(n.finger);
    return (f > 0) ? String(f) : undefined;
  }
  return undefined;
}

function buildSVGuitarArgs(diag, mode, displayKey) {
  const sf   = diag.sf || 1;
  const root = diag.r;
  const noteMap = {};
  diag.n.forEach(n => { noteMap[n.string] = n; });

  const fingers = [];
  for (let s = 1; s <= 6; s++) {
    const n    = noteMap[s];
    const text = getDotText(n, root, mode, displayKey);
    if (!n) {
      fingers.push([s, 'x']);
    } else if (n.fret === 0) {
      fingers.push(text !== undefined ? [s, 0, text] : [s, 0]);
    } else {
      const rf = n.fret - sf + 1;
      fingers.push(text !== undefined ? [s, rf, text] : [s, rf]);
    }
  }

  // Barre: 2+ adjacent strings with same non-zero finger at same relative fret
  const byFinger = {};
  fingers.forEach(([s, rf]) => {
    const n = noteMap[s];
    const g = n ? (parseInt(n.finger) || 0) : 0;
    if (g > 0 && typeof rf === 'number' && rf > 0) {
      const k = g + '_' + rf;
      (byFinger[k] = byFinger[k] || []).push(s);
    }
  });

  // Barre: same non-zero finger at the same relative fret on 2+ strings.
  // Adjacency is not required — a partial barre behind other fingers (which
  // press intermediate strings at a higher fret) is a standard technique.
  const barres = [];
  Object.entries(byFinger).forEach(([k, strings]) => {
    if (strings.length < 2) return;
    const rf = parseInt(k.split('_')[1]);
    if (!barres.find(b => b.fret === rf))
      barres.push({ fromString: Math.max(...strings), toString: Math.min(...strings), fret: rf });
  });

  const relFrets = fingers.filter(([,f]) => typeof f === 'number' && f > 0).map(([,f]) => f);
  const numFrets = relFrets.length ? Math.max(4, Math.max(...relFrets)) : 4;

  return { fingers, barres, numFrets, position: sf };
}

let renderSeq = 0;  // cancel stale renders

// ---- Render --------------------------------------------------------------
function render() {
  const seq = ++renderSeq;
  const content = document.getElementById('content');
  content.innerHTML = '';

  const keyData = DATA[currentKey] || {};
  const types = Object.keys(keyData);

  // Pick a valid currentType
  if (!currentType || !keyData[currentType]) {
    // Prefer first type in group order
    outer:
    for (const { types: gts } of GROUPS)
      for (const ct of gts)
        if (keyData[ct]) { setType(ct); break outer; }
    if (!currentType && types.length) setType(types[0]);
  }
  if (!currentType) { document.getElementById('count').textContent = ''; return; }
  selectEl.value = currentType;

  const voicings = keyData[currentType] || [];

  // Group by inversion_number: Map<inv, [voicing]>
  // inv=null/-1 → placed last under "Unknown"
  const INV_UNKNOWN = 9999;
  const invGroups = new Map();
  voicings.forEach(v => {
    const k = (v.inv === null || v.inv === undefined || v.inv === -1) ? INV_UNKNOWN : v.inv;
    if (!invGroups.has(k)) invGroups.set(k, []);
    invGroups.get(k).push(v);
  });

  // Sort groups: 0,1,2,3,4 … then unknown
  const sortedKeys = [...invGroups.keys()].sort((a, b) => a - b);

  let totalShown = 0;
  const frag = document.createDocumentFragment();
  const diagramIds = [];

  sortedKeys.forEach(invKey => {
    const group = invGroups.get(invKey);
    totalShown += group.length;

    const section = document.createElement('div');
    section.className = 'inv-section';

    const heading = document.createElement('div');
    heading.className = 'inv-heading';
    heading.textContent = invKey === INV_UNKNOWN
      ? `Unknown inversion (${group.length})`
      : `${INV_HEADINGS[invKey] || invKey + 'th Inversion'} — ${group.length} voicing${group.length !== 1 ? 's' : ''}`;
    section.appendChild(heading);

    const grid = document.createElement('div');
    grid.className = 'card-grid';

    group.forEach((diag, localIdx) => {
      const globalId = `d_${seq}_${invKey}_${localIdx}`;
      const card = document.createElement('div');
      card.className = 'card' + (diag.dup !== null && diag.dup !== undefined ? ' dup' : '');

      const diagramEl = document.createElement('div');
      diagramEl.className = 'diagram';
      diagramEl.id = globalId;
      card.appendChild(diagramEl);

      const meta = document.createElement('div');
      meta.className = 'card-meta';

      if (diag.ot && diag.ot.length) {
        const p = document.createElement('span');
        p.className = 'pill omit';
        p.textContent = omitLabel(diag.ot, diag.r);
        meta.appendChild(p);
      }
      if (diag.sub) {
        const p = document.createElement('span');
        p.className = 'pill sub';
        p.textContent = diag.sub;
        meta.appendChild(p);
      }
      if (diag.dup !== null && diag.dup !== undefined) {
        const p = document.createElement('span');
        p.className = 'pill dup';
        p.textContent = 'dup';
        meta.appendChild(p);
      }

      if (meta.children.length) card.appendChild(meta);
      grid.appendChild(card);
      diagramIds.push({ id: globalId, diag });
    });

    section.appendChild(grid);
    frag.appendChild(section);
  });

  document.getElementById('count').textContent =
    `${currentKey} / ${CHORD_LABELS[currentType] || currentType} — ${totalShown} voicing${totalShown !== 1 ? 's' : ''}`;

  content.appendChild(frag);

  // Draw SVGuitar diagrams in next animation frame (DOM must be attached first)
  requestAnimationFrame(() => {
    if (seq !== renderSeq) return;  // superseded
    diagramIds.forEach(({ id, diag }) => {
      if (seq !== renderSeq) return;
      const el = document.getElementById(id);
      if (!el) return;
      const { fingers, barres, numFrets, position } = buildSVGuitarArgs(diag, annotationMode, currentKey);
      try {
        new svguitar.SVGuitarChord(el)
          .chord({ fingers, barres })
          .configure({ position, strings: 6, frets: numFrets, strokeWidth: 1.5,
                       fingerSize: 0.7,
                       fingerTextSize: annotationMode === 'fingering' ? 22 : 16 })
          .draw();
      } catch (e) {
        el.innerHTML = '<span style="color:#c00;font-size:.65rem">' + e.message + '</span>';
      }
    });
  });
}

// ---- Init ----------------------------------------------------------------
selectKey(currentKey);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build(input_dir: Path, output_path: Path, quiet: bool = False) -> None:
    if not quiet:
        print(f"Loading voicings from {input_dir}/ …")

    data = build_data(input_dir)
    groups = build_groups(data)

    keys_js    = json.dumps([[p, l] for p, l in KEYS])
    groups_js  = _groups_js(groups)
    labels_js  = json.dumps({ct: lbl for ct, lbl in CHORD_LABELS.items()})
    data_js    = json.dumps(data, separators=(",", ":"))
    headings_js = json.dumps(INV_HEADINGS)
    svguitar   = _load_svguitar()

    html = (HTML
        .replace("__SVGUITAR__",     svguitar)
        .replace("__DATA__",         data_js)
        .replace("__GROUPS__",       groups_js)
        .replace("__KEYS__",         keys_js)
        .replace("__INV_HEADINGS__", headings_js)
        .replace("__CHORD_LABELS__", labels_js)
    )

    output_path.write_text(html, encoding="utf-8")

    if not quiet:
        total = sum(len(v) for kd in data.values() for v in kd.values())
        size_kb = output_path.stat().st_size // 1024
        print(f"Wrote {output_path} ({size_kb} KB, {total} voicings, {len(groups)} chord groups)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chord_book_cli.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input", metavar="DIR", default=".",
        help="Directory containing a.json, bb.json … b.json  (default: .)",
    )
    parser.add_argument(
        "--output", metavar="FILE", default="index.html",
        help="Output HTML file path  (default: index.html)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress output")
    args = parser.parse_args(argv)

    script_dir = Path(__file__).parent
    input_dir  = (script_dir / args.input).resolve()
    out_path   = Path(args.output) if Path(args.output).is_absolute() else script_dir / args.output

    if not input_dir.is_dir():
        print(f"ERROR: input directory not found: {input_dir}", file=sys.stderr)
        return 1

    build(input_dir, out_path, quiet=args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
