# kicad2ant architecture, end to end

kicad2ant simulates the printed antenna on a KiCad 10 board. The board's copper goes through a geometry
extractor (Python), a mesher (Python), the model build, the openEMS FDTD run and the post-processing
(Octave). The results are S11, Zin, the −10 dB band, gain, the pattern and a `.s1p`.

The user guide is in `README.md`, the model in `docs/USAGE.md`, the mesh in `docs/MESHER.md`, and the skill
in `SKILL.md`.

## 1. The big picture

```
 entry points                       pipeline                                         outputs
 ────────────                       ────────                                         ───────
 KiCad plugin ─┐                                                                     BOARD_kicad2ant/
 (wx window)   │  board copy   ┌──────────────┐  antenna_geom.m  ┌──────────────┐     ├─ antenna_geom.m
               ├─────────────> │ kicad2ant.py │ ───────────────> │ antenna_sim.m│     ├─ antenna_sim.m, run_sim.m
 command line ─┤               │  (front end) │                  │   (Octave)   │     ├─ sim_<mode>/  (openEMS XML,
               │               └──────┬───────┘                  └──────┬───────┘     │    fields, log)
 Claude skill ─┘                      │ runs                            │ runs        ├─ results/  summary, .s1p,
 (SKILL.md)                           v                                 v             │    plots
                              extract_antenna.py ── mesher.py        openEMS +        └─ history/ earlier .s1p
                              (board -> geometry)   (grid lines)     nf2ff
```

| Stage | File | Language | Needs |
|---|---|---|---|
| Front end | `scripts/kicad2ant.py` | Python 3 | Python only |
| Geometry | `scripts/extract_antenna.py` | Python 3 | Python only (reads the `.kicad_pcb` text, no pcbnew) |
| Mesh | `scripts/mesher.py` | Python 3 | Python only |
| Model, run, results | `scripts/antenna_sim.m` | Octave | Octave + openEMS 0.37 |
| KiCad window | `kicad_plugin/kicad2ant_plugin/` | Python (wx, pcbnew) | KiCad 10 |
| Tuning helpers | `scripts/fp_tools.py` | Python (pcbnew) | KiCad's Python |
| Footprint to board | `scripts/fp2board.py` | Python 3 | Python only |

The work is split this way so that everything decided from the board, including the geometry and the
mesh, is plain Python and tested in CI. Octave only builds the model from the finished numbers, runs
openEMS and does the post-processing.

## 2. Entry points

### 2.1 KiCad plugin

`kicad_plugin/kicad2ant_plugin/`

- `__init__.py`: a SWIG `pcbnew.ActionPlugin` with a wx dialog. It holds the mode, f0, band, feed pad
  ("use selected"), ground net, plastic case, the openEMS folder and the run folder.
- `core.py`: pure-Python helpers, tested by `kicad_plugin/test_core.py`. They build the command line,
  find the run folder and the result, parse the summary, read progress from the log, and handle the
  run-folder lock and stopping the process tree.

When you press Run:
1. It loads the board, refills the zones (`ZONE_FILLER`), and saves a **copy** into the run folder as
   `board.kicad_pcb`. The user's board is never changed.
2. It starts `kicad2ant.py` on that copy as a child process, and streams the log into the window with a
   progress bar.
3. When the run ends, it shows the summary and the result plots.

`kicad_plugin/build_pcm.py` packs the plugin and the scripts (`kicad2ant.py`, `extract_antenna.py`,
`mesher.py`, `antenna_sim.m`) into the PCM zip in `dist/`. It checks that the plugin `VERSION` matches
`metadata.json`.

### 2.2 Command line

```
python scripts/kicad2ant.py BOARD.kicad_pcb [REF] [--mode dry|fast|coarse|fine] [--f0 MHz] [--band LO HI]
       [--feed PAD] [--gnd NET] [--case ER TAND WALL SIDE TOP BOTTOM] [--out DIR] [--post] [--view]
```

`scripts/kicad2ant.bat` is a Windows wrapper for it.

### 2.3 Claude Code skill

`SKILL.md` runs the same `kicad2ant.py`. On top of a plain run it adds:
- the questions to ask the user first;
- the dry-run check of the geometry picture;
- the **tuning loop**: change the antenna copper in a board copy, refill with `fp_tools.py refill`, run
  fast, and repeat. The tuned antenna is saved to a library with `fp_tools.py save-footprint`.

## 3. The pipeline, step by step

### 3.1 `kicad2ant.py`: front end

1. Parses the options, checks the board exists, and picks the run folder: `BOARD_kicad2ant/` next to the
   board, or `--out`. The path must have no spaces (an openEMS limit).
2. Takes the run-folder lock (`core.take_lock`), so two runs cannot share a folder.
3. Refuses an f0 below 100 MHz. Sets the target band (default 2400–2483.5 MHz at 2.44 GHz, else f0 ± 2 %).
4. Runs `extract_antenna.py` with the reference, `--feed`, `--gnd`, `--mode`, `--f0` and `--case`. It
   skips this with `--post`.
5. Finds openEMS: `OPENEMS`, the PATH, or a search of the drives on Windows.
6. Copies `antenna_sim.m` into the run folder and writes `run_sim.m`, which holds the run's settings (mode,
   f0, band, case, openEMS path). Running `run_sim.m` in Octave repeats the run.
7. Finds Octave, then runs it headless with one OpenBLAS thread. Many-core machines otherwise fail to
   allocate memory.
8. Optionally opens the 3D model in AppCSXCAD (`--view`).

### 3.2 `extract_antenna.py`: board to geometry

It parses the `.kicad_pcb` S-expression text itself. KiCad 10 items carry `(net "GND")` by name, and the
older `fp_text reference` syntax still works.

| Collected | From |
|---|---|
| Antenna copper | the antenna footprint (REF, or auto: AE*/ANT*/RF_Antenna), pads and shapes on every copper layer |
| Ground copper | the ground net's zone fills, tracks and vias on every copper layer |
| Stackup | Board Setup > Physical Stackup: copper heights, dielectric thicknesses, εr, tan δ. Default: 2-layer FR4 |
| Outline | Edge.Cuts, with the cutouts |
| Feed port | the feed pad: vertical (from the pad down to the ground layer) or in-plane (to the nearest ground copper) |
| Ground vias | as PEC lines |
| Mesh input | straight antenna edges, ground edges near the feed, via centres, antenna box |

It then calls `mesher.build()` (section 3.3) and writes everything into `antenna_geom.m` as a `geom`
struct: polygons per layer, `cu_z`, dielectrics, outline, cutouts, port, vias, and `grid_x/y/z`.

### 3.3 `mesher.py`: grid lines

It puts lines exactly on the copper edges and the port planes, merges lines closer than 0.05 mm, and gives
every trace and gap at least 2, 3 or 4 cells (fast, coarse, fine). Each gap is filled from both ends with
cells growing by at most 1.3. The z grid has a line on every copper and dielectric face. Details:
`docs/MESHER.md`.

### 3.4 `antenna_sim.m`: model, run, results

The script runs in this order:

1. **Parameters:** mode, end criterion (−30 dB fast, −40 dB coarse, −50 dB fine), f0, `fc = 0.4·f0`, the sweep
   f0 ± fc, the band, the case. It loads the openEMS Octave scripts and runs `antenna_geom.m`.
2. **Model (CSXCAD):**
   - one dielectric box per layer pair, minus the cutouts;
   - copper as zero-thickness PEC polygons;
   - ground vias as PEC lines;
   - the optional plastic case as six dielectric boxes;
   - a 50 Ω lumped line port at the feed-pad centre.
3. **Mesh:** `geom.grid_*` as given, plus 8 cells of PML on each side (PML_8, every mode). The NF2FF
   box goes 10 cells in from the boundary.
4. **Geometry plot:** every copper layer, the whole board and a zoom on the antenna. `--mode dry` stops here.
5. **Run:** writes `sim_<mode>/antenna.xml`, then runs `RunOpenEMS` with a log, which shows whether the run
   converged. With `skip_fdtd` (`--post`) it reuses the saved fields.
6. **Match:** S11, Zin, the Smith chart, the resonance, the −10 dB band and band coverage. It overlays
   `measured*.s1p` (VNA) and the last two earlier runs from `history/`.
7. **Far field** (coarse and fine only): `CalcNF2FF` over the band for directivity, radiation efficiency,
   gain and realized gain, plus the pattern cuts at resonance.
8. **Report:** `results/<REF>_<mode>_summary.txt`, `<REF>_<mode>.s1p` and the plots. The `.s1p` from the
   run before goes to `history/` first.

## 4. Run folder layout

```
BOARD_kicad2ant/
├─ board.kicad_pcb          the plugin's refilled copy (plugin runs only)
├─ antenna_geom.m           geometry + grid lines (extract_antenna.py + mesher.py)
├─ antenna_sim.m            the copied simulation script
├─ run_sim.m                this run's settings; run it in Octave to repeat
├─ measured*.s1p            optional VNA data, overlaid on the plots
├─ sim_<mode>/              openEMS XML, probe and field dumps, openEMS.log, nf2ff files
├─ results/                 <REF>_<mode>_summary.txt, <REF>_<mode>.s1p, geometry and result plots
└─ history/                 earlier runs' .s1p, named by date, for the overlay
```

## 5. Model conventions

- Units: mm, y up, z = 0 at the bottom copper.
- Copper: zero-thickness PEC sheets. Ground vias: PEC lines.
- Only the antenna footprint and the ground net are modelled. Other nets and the parts are not.
- Air: max(5 mm, λ/4) on every side, then the PML.
- Excitation: a Gaussian pulse over f0 ± 0.4 f0, so it reaches 30 % of the band past the top.
- Port: 50 Ω lumped line port through the feed-pad centre.

## 6. Side tools

| Tool | What it does |
|---|---|
| `scripts/fp2board.py` | Turns a bare antenna footprint (`.kicad_mod`) into a simulatable board: GND copper from the polygons holding pad 2, the rest as antenna footprint `ANT1`, feed pad 1 on net RF, 2- or 4-layer stackup, outline from F.Fab and the copper. It made the example boards in `examples/`. |
| `scripts/fp_tools.py refill BOARD` | Refills the zones of a board copy after the antenna copper changed (KiCad's Python). |
| `scripts/fp_tools.py save-footprint ...` | Saves the tuned antenna from a board copy into a `.pretty` library, with the run noted in its description. |

## 7. Tests and CI

| Test | Covers |
|---|---|
| `scripts/test_extract.py` | the extractor on hand-written fixtures in `scripts/fixtures/` and on example boards |
| `scripts/test_mesher.py` | the mesher: lines on edges, port planes kept, merge, least cells across traces, neighbour ratio |
| `kicad_plugin/test_core.py` | the plugin helpers |
| `kicad_plugin/build_pcm.py` | the PCM zip builds, and the versions agree |

`.github/workflows/test.yml` runs all four on Linux, Windows and macOS. A real simulation needs Octave and
openEMS, so it is not in CI. To check end to end, run `--mode dry` on `examples/ti_ifa` (seconds), then a
coarse run (about 10 minutes).

## 8. Limits

- KiCad 10 only. KiCad 11 removes the SWIG `ActionPlugin`.
- No spaces in the openEMS or run folder paths.
- Diagonal and arc edges get no grid lines of their own.
- Known open issue: on the IFA example the far field looks wrong right at resonance (see `CLAUDE.md`).
- Not tested end to end: `--mode fine`, Linux, macOS, back-side antennas in the tuning flow.
