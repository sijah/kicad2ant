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
| `--mode dry\|coarse\|fine` | `coarse` |
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
4. **Coarse, then fine:** coarse (0.5 mm at the antenna, -40 dB end; a 30x36 mm 2-layer IFA board is
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
   `results/<REF>_<mode>_summary.txt`; never write into it.
2. **Variant:** copy the run folder's `board.kicad_pcb` (the exact board that was simulated, zones filled)
   to a new folder, e.g. `BOARD_try1/board.kicad_pcb`. Edit only the antenna footprint's copper in that
   copy: its `fp_line` / `fp_poly` / `fp_arc` on copper layers and its pads, in footprint-local mm.
   Change one thing per variant (arm length, short-pin position, meander count, feed gap) and write
   down what and by how much.
3. **Run it into its own folder:** `--out BOARD_try1_kicad2ant --mode dry` first and show the geometry
   picture, then coarse. Same `REF`, `--f0`, `--band`, `--feed`, `--gnd` as the baseline.
4. **Compare** with the baseline: resonance, S11 at f0, -10 dB band against the target, gain. A coarse run
   of a small 2-layer board is about 10-20 min; run variants one after another, not in parallel.
5. **Fine** only for the variant the user picks.

Do not edit `antenna_geom.m` to make a variant: it also holds the mesh lines snapped to the old copper
edges. Change the board copy and extract again.

## Applying the chosen variant in KiCad

Never edit KiCad's own libraries (`RF_Antenna`), and never the user's `.kicad_pcb` while KiCad has it open.

1. **Footprint:** find ANT's library id (`(footprint "Lib:Name"` in the board). Copy that `.kicad_mod`
   into the project's own footprint library as a new name, keep the old one, and put the variant's
   copper and pads in the copy.
2. **Into the board,** with the Konnect MCP if it is available (KiCad 10 open on the board, Preferences >
   Plugins > Enable IPC API): `load_toolset(["library", "pcb_components"])`; `set_footprint_graphics`
   (replace on the copper layer) and `edit_footprint_pad` write the `.kicad_mod`; then
   `update_footprints_from_library` with `references: [REF]`, dry run first, show the plan, apply only
   when the user agrees (one KiCad undo step; position, rotation and nets are kept). Test
   `set_footprint_graphics` on a copper layer on a throwaway copy first; it is documented for
   graphic layers.
   If REF still points at another library's footprint, Konnect cannot swap it: the user does PCB editor >
   right-click > Change Footprint once, and sets the same footprint in the schematic symbol's Footprint
   field (else Update PCB from Schematic puts the old antenna back).
   Without Konnect: give the user the exact changes (which segment, old and new coordinates) to make
   in the Footprint Editor.
3. **Check:** the user refills zones (B) and saves; check the GND keep-out still clears the antenna; run
   kicad2ant once on the real board. The result must match the chosen variant; if not, the swap is wrong
   (rotation, feed pad number).

## Limits to state with every result

- Only the antenna footprint and the GND net are modelled: other nets, components and any
  enclosure are not. Bare board in air.
- Copper is lossless (PEC): radiation efficiency counts dielectric loss only.
- Lumped port at the feed pad, not de-embedded: S11 is at the pad, without matching network and
  feed line. Chip antennas (a component, not copper) cannot be modelled.
- f0 below 100 MHz (NFC loops) is refused: not practical in FDTD.
- Coarse is for trends; final tuning is on the real board with a VNA.
