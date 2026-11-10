---
name: kicad2ant
description: Simulates a printed PCB antenna footprint from a KiCad board in openEMS (FDTD) via Octave - extracts the antenna footprint's copper on any layer, the GND net's zone fills, tracks and vias on every copper layer, the full stackup, the board outline with cutouts and the feed port from the .kicad_pcb, builds the model, runs it, and reports S11, Zin, Smith chart, the -10 dB band, directivity / radiation efficiency / gain / realized gain over the band, pattern cuts, a Touchstone .s1p for matching-network design and an overlay of a VNA measurement. Use when the user wants to simulate, check or tune a PCB antenna (IFA, MIFA, meander, loop, monopole, patch) from KiCad, see its S11 or pattern, compare it with a measurement, or get an .s1p for the match.
---

# kicad2ant: KiCad antenna -> openEMS

One command, run from anywhere: `python <skill>/scripts/kicad2ant.py BOARD.kicad_pcb [REF] [options]`
(`<skill>` = this file's folder). It extracts the geometry into `BOARD_kicad2ant/` next to the board,
finds Octave and openEMS, runs, and writes `BOARD_kicad2ant/results/`. `--help` lists the options;
docs/USAGE.md has the install and the model. Do not copy the scripts.

| option | default |
|---|---|
| `REF` | the one AE*/ANT* / RF_Antenna footprint (error lists candidates if not exactly one) |
| `--mode dry\|fast\|coarse\|fine` | `fast` (S11 / Zin / -10 dB band only, no far field) |
| `--f0 MHz`, `--band LO HI` | 2440, 2400..2483.5; another f0 -> band f0 -/+ 2 % |
| `--feed PAD`, `--gnd NET` | pad 1; the net of pad 2, else GND, else the largest ground-named zone net (printed as `ground net: ...`) |
| `--out DIR` | `BOARD_kicad2ant` (no spaces) |
| `--post` | post-processing only, on saved fields (refuses if the board / parameters / mesh changed) |

## Workflow

1. **Board ready:** GND zones filled (press B) and the board saved; stackup set in Board Setup >
   Physical Stackup (else 2-layer FR4 4.5, with a warning). The extractor stops naming what is missing.
2. **Ask the user** (together, once): design frequency and target band; the antenna reference if
   the board has several; feed pad / ground net if not pad 1 / pad 2's net; enclosure or bare board
   (only bare is modelled).
3. **Dry run:** `--mode dry`, then show `results/<REF>_geometry.png` (each copper layer, whole board
   and zoomed: GND grey, antenna orange, port magenta, PEC lines blue). Check the port is on the
   feed and the ground is where the user expects.
4. **Fast, coarse, fine:** fast (no thirds rule, MUR, -30 dB, no far field; seconds to a minute,
   resonance about 1-2 % below coarse) to see where it resonates; coarse (0.5 mm at the antenna, -40 dB end; a 30x36 mm 2-layer IFA board is
   0.4 Mcells, ~10 min) in the background; fine (0.2 mm, -50 dB) for numbers to quote; it needs
   several GB of RAM on large boards. If the system kills a run for memory, report it, do not restart.
5. **Measured data:** a VNA 1-port file saved as `BOARD_kicad2ant/measured.s1p` is overlaid on the
   S11 and Smith plots and its resonance compared in the summary; rerun with `--post`.
6. **Report** from `results/<REF>_<mode>_summary.txt`, show `_s11_zin.png`, `_smith.png`,
   `_pattern.png`: resonance and min S11 (a minimum at the sweep edge is flagged), the -10 dB band
   vs the target, Zin at f0, reactance zero crossings, the run line (converged? mesh neighbour
   ratio), and the D / efficiency / gain / realized-gain table. Resonance off f0 -> retune the
   antenna length; close but mismatched -> match network from the `.s1p`.

After editing `extract_antenna.py` run `python scripts/test_extract.py` (prints OK).

## Tuning: try antenna changes without touching the user's board or results

Each shape change needs a new FDTD run (`--post` only redraws the same shape). Keep every try apart:

1. **Baseline:** the existing run folder (`BOARD_kicad2ant/`, or the plugin's Output in folder). Read its
   `results/<REF>_<mode>_summary.txt` and note its mode; never write into it.
2. **Variant:** copy the run folder's `board.kicad_pcb` (the exact board that was simulated) to a new
   folder, e.g. `BOARD_try1/board.kicad_pcb`. Edit only the antenna footprint in that copy: its
   `fp_line` / `fp_poly` / `fp_arc` on copper layers and its pads, in footprint-local mm (unrotated, as in
   the `.kicad_mod`). Keep the pad numbers (the feed pad stays the feed pad). One change per variant
   (arm length, short-pin position, meander count, feed gap); write down what and by how much.
   At coarse (0.5 mm cells at the antenna) steps under ~0.5 mm are mostly mesh noise: tune in bigger
   steps, confirm small ones at fine.
3. **Refill the zones in the copy.** The extractor reads the *saved* zone fills, which were made around
   the old antenna: a bigger antenna would sit in stale ground copper, a smaller one would leave a gap.
   With KiCad's Python (Windows `C:\Program Files\KiCad\10.0\bin\python.exe`, Linux/macOS the
   python3 that imports `pcbnew`; called KPY below):
   `KPY <skill>/scripts/fp_tools.py refill BOARD_try1/board.kicad_pcb`
   If a moved short-pin pad no longer touches GND copper after the refill, the variant is not
   connected: say so, do not run it.
4. **Run it into its own folder,** with the baseline's `REF`, `--f0`, `--band`, `--feed`, `--gnd` and mode:
   `--out BOARD_try1_kicad2ant --mode dry` first and show the geometry picture, then the run.
   Use `--mode fast` for each variant (under a minute on a small board): it gives the resonance shift.
   One variant at a time, not in parallel; two runs in one run folder are refused.
5. **Compare** with the baseline run in the same mode: resonance, S11 at f0, -10 dB band against the target.
6. **Coarse** for the variant the user picks (adds gain and pattern), **fine** for numbers to quote.

Do not edit `antenna_geom.m` to make a variant: it also holds the mesh lines snapped to the old copper
edges. Change the board copy and extract again.

## Applying the chosen variant in KiCad

Never edit KiCad's own libraries (`RF_Antenna`), and never the user's `.kicad_pcb` while KiCad has it open.
The source of truth is the variant's footprint in `BOARD_tryN/board.kicad_pcb` (what was simulated), not
the library file.

1. **Footprint file.** Let KiCad write it from the simulated board copy, do not convert it by hand:
   `KPY <skill>/scripts/fp_tools.py save-footprint BOARD_tryN/board.kicad_pcb REF LIB.pretty NAME`
   (unplaced, unrotated, pads without nets; front-side footprints only). Which `LIB.pretty` and `NAME`:
   find REF's library id, `(footprint "Lib:Name"` in the board.
   - `Lib` is a project library (the user's own): back up `Name.kicad_mod` as `Name_orig.kicad_mod`, then
     save over `Name`. The id is unchanged, so step 2 works.
   - `Lib` is KiCad's or another shared library: save as a new footprint in the project's library
     (e.g. `Name_tuned`; a new `.pretty` folder must be added in Preferences > Manage Footprint
     Libraries, or with Konnect `register_footprint_library`). The user then does, once, PCB editor >
     right-click REF > Change Footprint, and sets the same id in the schematic symbol's Footprint field
     (else Update PCB from Schematic puts the old antenna back).
2. **Into the open board** with the Konnect MCP (KiCad 10 open on the board, Preferences > Plugins >
   Enable IPC API): `load_toolset("pcb_components")`, then `update_footprints_from_library` with
   `references: [REF]`, dry run first, show the plan, apply only when the user agrees (one KiCad undo
   step; position, rotation and nets are kept). Without Konnect: the user runs Tools > Update Footprints
   from Library on REF, or edits the copper by hand from your exact old/new coordinates.
3. **Check (seconds, no simulation):** the user refills zones (B) and saves. Run
   `python <skill>/scripts/extract_antenna.py BOARD.kicad_pcb REF check.m` (plus the run's `--feed` /
   `--gnd`) and compare `check.m` with the variant run folder's `antenna_geom.m`: apart from the first
   line (the source path) they must be identical. Identical = the board now holds exactly what was
   simulated, no new run needed. Different = the swap is wrong (rotation, feed pad number, wrong
   footprint, zones not refilled) or other GND copper changed since; show the differing `geom.` lines.

## Limits to state with every result

- Only the antenna footprint and the GND net are modelled: other nets, components and any
  enclosure are not. Bare board in air.
- Copper is lossless (PEC): radiation efficiency counts dielectric loss only.
- Lumped port at the feed pad, not de-embedded: S11 is at the pad, without matching network and
  feed line. Chip antennas (a component, not copper) cannot be modelled.
- f0 below 100 MHz (NFC loops) is refused: not practical in FDTD.
- Fast and coarse are for trends; final tuning is on the real board with a VNA.
