# kicad2ant

Simulate the PCB antenna on your KiCad board in [openEMS](https://openems.de), with no geometry entered
by hand. Point it at the `.kicad_pcb` file and you get:

- S11, input impedance and a Smith chart; the band where S11 is below the match limit (−10 dB, or −6 dB below 2 GHz) and whether it covers your target band
- directivity, radiation efficiency, gain and realized gain across the band
- pattern cuts at resonance, plus a 3-D pattern for ParaView
- a Touchstone `.s1p` file for designing the match network
- your VNA measurement overlaid on the plots, if you have one

It reads the antenna footprint's copper on any layer and any shape (IFA, MIFA, meander, loop,
monopole, patch), the ground net's filled zones and tracks on every copper layer, the GND vias, the
full stackup, and the board outline with its cutouts. Written for and tested with KiCad 10 files.

This page is about the command line. The KiCad toolbar plugin is in the [README](../README.md).

## Install (once)

1. **Python 3** on PATH. Nothing to pip install.
2. **[GNU Octave](https://octave.org/download)** (tested with 11.1 on Windows).
3. **[openEMS](https://github.com/thliebig/openEMS-Project/releases)** v0.37 or newer. On Windows,
   unzip it to a folder **without spaces**, e.g. `C:\openEMS`. Then in Octave, run once:
   `cd C:\openEMS\matlab; setup` (this builds the HDF5 readers for your Octave).

`kicad2ant.py` looks for Octave and openEMS by itself (on PATH, in `C:\Program Files\GNU Octave`,
and in `openEMS*` folders up to two levels deep on drives C to H). If it can't find them, set
`OCTAVE` (path to `octave-gui.exe` or `octave`) and `OPENEMS`: the folder that holds `matlab/` on
Windows, the install prefix (with `bin/` and `share/`) on Linux and macOS. There, openEMS can also be
on the Octave path through `~/.octaverc`.

## Use

In KiCad, **fill the zones (press B) and save the board.** Set the stackup in Board Setup >
Physical Stackup. Without one, the board is taken as 2 layers of FR4 εr 4.5. Then:

```
python ../scripts/kicad2ant.py myboard.kicad_pcb --mode dry                 # check the model first
python ../scripts/kicad2ant.py myboard.kicad_pcb                            # fast: S11 only, minutes
python ../scripts/kicad2ant.py myboard.kicad_pcb --mode coarse              # adds gain and pattern, minutes
python ../scripts/kicad2ant.py myboard.kicad_pcb --mode fine                # numbers you quote
python ../scripts/kicad2ant.py myboard.kicad_pcb AE2 --f0 868 --band 863 870   # other antenna / band
```

On Windows you can also drag the `.kicad_pcb` file onto `../scripts/kicad2ant.bat`. That runs a fast
2.4 GHz simulation.

| option | default |
|---|---|
| `REF` | the one footprint whose reference is AE*/ANT* or whose library name contains "antenna" |
| `--mode dry\|fast\|coarse\|fine` | `fast`. `dry` builds the model and the geometry picture only; `fast` gives S11, Zin and the −10 dB band but no gain or pattern; `coarse` adds those; `fine` is the finer mesh |
| `--f0 MHz`, `--band LO HI` | 2440 and 2400 to 2483.5 (2.4 GHz ISM). For another f0, the band defaults to f0 ± 2 % |
| `--feed PAD` | pad `1` of the antenna footprint |
| `--gnd NET` | the net of pad `2`, else `GND`, else the largest zone net with a ground name (`AGND`, `GNDA`, `VSS`, `0V`, ...). A name is matched exactly, then without its sheet path, then without case |
| `--case ER TAND WALL SIDE TOP BOTTOM` | none: the board in air. A plastic case as a box shell around the board: εr, loss tangent, wall thickness and the gaps to the board at the sides, on top (F.Cu side) and below, mm; e.g. `--case 3 0.01 2 1 1 1` for ABS. In the plugin: **Around the board: Plastic case** |
| `--out DIR` | `myboard_kicad2ant/` next to the board. The path must not contain spaces |
| `--post` | redo only the post-processing on saved fields, e.g. after adding `measured.s1p` |

Results go to `myboard_kicad2ant/results/`:
- `<REF>_<mode>_summary.txt`
- the plots: `_s11_zin.png`, `_smith.png`, `_pattern.png` and `<REF>_geometry.png`
- `.s1p` and `.vtk`

To compare with a measurement, drop your VNA's 1-port file in the run folder as **`measured.s1p`**
and run again with `--post`. `measured1.s1p`, `measured2.s1p`, … are overlaid too, each in its own colour;
each run also keeps the result it replaces in `history/` and overlays the last two earlier runs of
the same mode, so antenna versions are compared without copying anything.

**Check the dry run first.** `<REF>_geometry.png` shows each copper layer: GND in grey, the antenna
in orange, the port in magenta. The port must sit on the feed pad, and the ground must be where you
expect it.

## How it models the board

- Copper is perfect conductor sheets: the antenna, the GND zone fills and the GND tracks. GND vias
  and plated holes are wires. One dielectric is
  extruded over the outline between each pair of copper layers, as thick as the stackup's dielectric
  there; the copper sheets lie on its faces and add no height (a 0.035 / 0.73 / 0.035 mm board is
  modelled 0.73 mm thick). The board sits in air (λ/4 at f0,
  at least 5 mm) with PML absorbing boundaries.
- The feed is a 50 Ω lumped port:
  - **vertical** from the feed pad to the GND fill under it, when another layer has GND there;
  - otherwise **in-plane**, from the pad edge to the nearest GND fill edge on the same layer. That
    edge must be straight across from the pad (not diagonal), or the extractor stops.
- The mesh (`scripts/mesher.py`, docs/MESHER.md) puts a line on every straight antenna edge, gives every
  trace and gap at least 2 / 3 / 4 cells (fast / coarse / fine) with cells up to 0.5 / 0.25 / 0.15 mm at
  the antenna, and grades by at most 1.3 to λ/15 (fine λ/20) in air.
- Fast uses the coarser mesh, stops at −30 dB and skips the far field; the air (λ/4) and PML_8 are as in
  coarse. On the printed IFA and AN043 its resonance came within 0.5 % of coarse, in about a quarter of the
  time.

## Limits: state them with every result

- Only the antenna footprint and the ground net are modelled. Other nets and components are left
  out. The board is in air, or in a box-shaped plastic case (`--case`): one material, flat walls, the
  box around the board outline's bounding box; ribs, bosses and curved walls are not modelled.
- Copper is lossless, so radiation efficiency counts dielectric loss only.
- S11 is at the feed pad, without the matching network or the feed line.
- Chip antennas can't be modelled: they are a part, not copper.
- Below 100 MHz (NFC and other low-frequency loops) it refuses to run: the solver would need
  millions of steps.
- Use fast and coarse runs for trends. Do the final tuning on the real board with a VNA.

## Files

| file | does |
|---|---|
| `../scripts/kicad2ant.py` | the command line: extracts, finds Octave and openEMS, runs |
| `../scripts/kicad2ant.bat` | Windows drag-and-drop wrapper |
| `../scripts/extract_antenna.py` | `.kicad_pcb` -> `antenna_geom.m` (also usable alone) |
| `../scripts/antenna_sim.m` | model, mesh, openEMS run, post-processing |
| `../scripts/test_extract.py` | extractor self-check: `python ../scripts/test_extract.py` |
| `../scripts/fp_tools.py` | for tuning on a board copy (KiCad's Python): refill zones, save a board footprint to a library |
| `../examples/ti_ifa/` | TI SWRA117D meander IFA on a 2-layer board, with coarse results |
| `SKILL.md` | lets [Claude Code](https://claude.com/claude-code) run it for you (`/kicad2ant`) |

Design notes borrowed from [kicad2ems](https://github.com/lowprocess/kicad2ems) (air size, excitation past the band,
gain table) and from Antmicro's [gerber2ems](https://github.com/antmicro/gerber2ems) (VNA overlay,
Smith chart, convergence check).
