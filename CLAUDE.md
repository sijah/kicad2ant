# kicad2ant: notes for working on this repo

kicad2ant simulates the printed antenna on a KiCad board: `.kicad_pcb` → geometry (Python) → model and run
(Octave + openEMS FDTD) → S11, Zin, band, gain, pattern, `.s1p`. Users run it from a KiCad 10 plugin, the
command line, or the Claude Code skill. README.md is the user guide, docs/USAGE.md the model in detail,
SKILL.md the skill (including the tuning loop).

## Flow

1. `scripts/kicad2ant.py`: CLI front end. Picks the antenna footprint, finds Octave and openEMS, calls the
   extractor, writes `run_sim.m`, runs Octave.
2. `scripts/extract_antenna.py`: parses the `.kicad_pcb` text itself (no pcbnew) → `antenna_geom.m`.
   Antenna footprint copper on any layer, ground net zone fills / tracks / vias on every copper layer,
   stackup, Edge.Cuts outline with cutouts, feed port.
3. `scripts/antenna_sim.m`: mesh, openEMS run, post-processing, plots, `.s1p`.
4. `kicad_plugin/kicad2ant_plugin/`: the KiCad IPC plugin: `kicad2ant_ipc.py` (entry, from `plugin.json`), the
   window (`dialog.py`, wx), `host.py` (all kipy calls) and its pure-Python helpers
   (`core.py`). It saves a board copy, then runs the same `kicad2ant.py`.
5. `scripts/fp_tools.py`: plain Python for the tuning flow: refill zones (through `kicad-cli`), save a
   footprint to a library (text edit, checked against KiCad's own save in `scripts/test_fp_tools.py`).

## Tests

```
python scripts/test_extract.py     # extractor, hand-written fixtures in scripts/fixtures/ (prints OK)
python scripts/test_fp_tools.py    # footprint save against KiCad's own output (prints OK)
python kicad_plugin/test_core.py   # plugin helpers (prints OK)
python kicad_plugin/build_pcm.py   # PCM zip -> dist/, checks plugin version == metadata.json version
```

Plain Python 3 with no dependencies. CI (`.github/workflows/test.yml`) runs all of them on Linux, Windows and
macOS. A real simulation needs Octave and openEMS and is not in CI. To check a change end to end, use
`--mode dry` on `examples/ti_ifa` (seconds), then a coarse run (about 10 minutes).

## Rules and gotchas

- **IPC plugin, KiCad 10 and later** (since 2.0.0; 1.0.0 was the last SWIG one). Only `host.py` talks to KiCad
  (kipy, `kicad-python==0.8.0`, imported inside functions so CI runs without it). The user must turn on Enable
  KiCad API. kipy 0.8.0's `refill_zones(block=True)` never times out: keep the unblocked fill + retried save.
  Nothing imports `pcbnew` any more (KiCad 11 drops it). KiCad 10 files
  have no net table, and items carry `(net "GND")` by name. Keep the older `fp_text reference` syntax
  working in the extractor.
- **The plugin must never change the user's board.** It refills zones and saves a copy into the run folder.
- **No spaces in openEMS or run folder paths** (openEMS limit). The code falls back to app-data/home.
- Model conventions: y up, z = 0 at the bottom copper, copper as zero-thickness PEC sheets, ground vias as
  PEC lines, air = max(5 mm, λ/4) with PML_8, excitation extends 30 % of the band past the top.
- Only the antenna footprint and the ground net are modelled. Modelling other nets is out of scope.
- When you bump the version, change `kicad_plugin/metadata.json`, `VERSION` in the plugin's `dialog.py`,
  `VERSION` in `scripts/kicad2ant.py` (it goes on every plot) and CHANGELOG.md together (the build checks the
  first three).
- GPL-3.0-or-later. Don't copy code from projects with incompatible licences. Ideas taken from kicad2ems
  and gerber2ems are credited in the README.

## Known open issues

- Far field at resonance looks wrong on the IFA example: directivity jumps and radiation efficiency drops
  right at resonance. Suspects are the NF2FF box position, the −40 dB end criterion and the multi-frequency
  `CalcNF2FF`. Not resolved yet.
- Not tested: `--mode fine`, Linux and macOS end to end, back-side antennas in the tuning flow.
