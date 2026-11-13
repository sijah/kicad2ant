# Changelog — kicad2ant

## v0.3.7 (2026-11-13)

### Added
- Board thickness shown in three places:
  - Plugin Run tab: a **PCB** line with the thickness, copper layer count, material, εr and tanδ read from the
    saved board. A warning line under it when the board has no stackup (values assumed) or only KiCad's default
    one (1.51 mm FR4 εr 4.5, written on save even when never set).
  - Results summary: `board: 0.8 mm, 2 copper layers, FR4 epsR 4.4, tanD 0.02` (shown in the Results tab).
  - Plot heading, on every PNG: `project | REF mode | 0.8 mm FR4 epsR 4.4`.

### Changed
- The summary's old `board:` line (copper sheets, modelled dielectric height, ground, port) is now `model:`.

## v0.3.6 (2026-11-13)

### Fixed
- Plugin window can be minimized (it had no minimize button). The toolbar button brings a minimized window back.
- Setup tab sometimes showed "Octave (version unknown)": `octave --version` failed with OpenBLAS "Memory
  allocation still failed" on many-core machines. The version check now uses one OpenBLAS thread, as runs do.

## v0.3.5 (2026-11-13)

### Added
- Plugin Setup tab shows the Octave and openEMS a run will use and their versions, or which one is not found,
  with a Check again button. `kicad2ant.py --check` prints the same; every run's log starts with it.
- README: step-by-step linking of Octave to openEMS (Windows `setup`, Linux / macOS `.octaverc`), and that MATLAB
  is not supported.

### Changed
- A missing Octave is reported before any work starts (it used to come after the board was extracted), with a
  message that says why Octave is needed. A wrong Octave path in the Setup tab (or `OCTAVE`) is named as such. In
  the plugin it opens a warning and the Setup tab.

### Fixed
- Show the 3D model (`--view`, since 0.3.4): on a re-run it opened at once with the previous run's model (e.g.
  without a plastic case just added), because the last run's openEMS.log was still there. It now waits for this
  run's log. The simulation itself always used the new model.

## v0.3.4 (2026-11-13)

### Added
- Plugin About tab: what kicad2ant does, licence and credits, and how the antenna footprint should look (a drawing
  of an IFA and a table: reference, feed pad, ground pad, feed-to-ground gap, keepout, direction).

- Plugin Results tab: move the mouse over the S11 / Zin plot for the values at that frequency, for every trace
  (the run, the measured files and the earlier runs): S11 dB, VSWR and Zin, read from the .s1p files (a small
  `<REF>_<mode>_s11_zin.txt` beside the picture says where the plot is and which files it shows).
- Every plot carries the project (board) name, the antenna and the mode as a heading, and
  "kicad2ant <version> | openEMS FDTD | date" as a grey mark. `scripts/kicad2ant.py` has its own VERSION now,
  checked by `build_pcm.py`.

### Changed
- `--view` / *Show the 3D model*: the model opens as soon as it is built, while openEMS runs, instead of when the
  run ends. Stop the run if the mesh or the port looks wrong.
- S11 plot: the legend is below the plot in one row (inside it covered the dip and the resonance mark), with the
  file names without folder and `.s1p`; the simulation curve is drawn on top of the overlays.

### Fixed
- Plugin: the Results summary covered the Plot choice when it had more lines.
- Plugin: the run time and time left were cut off ("0:" for "0:27") in a window at its normal size.
- Plugin: the "Board in" choice stretched across the window when Air was chosen.
- Plugin: before the energy starts to fall the progress says "Simulating" instead of "Converging: -0 of -30 dB".
- Plots of an unannotated antenna (ANT**, named ANT__) printed "TeX parse error: syntax error" and drew the titles
  wrong; titles now print the name as it is. The results were not affected.

## v0.3.3 (2026-11-13)

### Changed
- Plugin window cleaned up. Run tab: mode, f0, band (the default band shows in grey), ground net ("auto"), the
  antenna Auto finds (e.g. "Auto: AE1 pad 1", with a warning when the reference is not annotated), the case
  fields only for a plastic case, and a line saying what the Simulation tab changes from the mode, with Edit.
  One "Open folder" button with a menu (results / run folder). The log is folded and opens when a run fails.
  Progress shows the energy against the end criterion (-18 of -40 dB) and an estimate of the time left.
- Simulation tab: grouped into Sweep / Mesh / Run / Far field; changed values in bold; the pattern
  frequency and step are greyed when the pattern is off.
- New Setup tab for Octave, the openEMS folder, the run folder location and the theme. The big header is gone.

### Fixed
- When a run ended, the window showed the Simulation tab instead of Results (since 0.3.1).

## v0.3.2 (2026-11-13)

### Changed
- Simulation tab: the sweep start and stop show the default sweep as numbers (f0 -/+ 40 %, 1464 / 3416 MHz at
  2440 MHz) instead of 0, and follow f0 until you type your own.

## v0.3.1 (2026-11-13)

### Added
- Plugin Simulation tab: the chosen mode's run settings (sweep, points, cell size, cells across traces and the
  substrate, merge distance, grading, air, step limit, end criterion, threads, pattern on/off, frequency and step),
  each one editable. The command line takes the same as `--set KEY=VALUE`; the values live in `mesher.py` MODES.

## v0.3.0 (2026-11-13)

### Added
- `scripts/fp2board.py`: puts an antenna footprint (`.kicad_mod`) on a bare board that kicad2ant can
  simulate (ground polygons to GND zones, feed pad off the ground, outline, stackup). The 19 example
  footprints are converted into `examples/<name>/`.
- The extractor reads board copper shapes on the ground net (`gr_poly` / `gr_rect` ... with a net) as ground.

### Changed
- New mesher in Python (`scripts/mesher.py`): a line on every straight copper edge and port plane, at least
  2/3/4 cells across each trace and gap (fast/coarse/fine), grading at 1.3, and a check that stops the run
  when copper or the port is off the grid. The port is a line at the feed-pad centre.
- Fast mode uses PML and λ/4 air like coarse (MUR with λ/8 was 2.5 % off).
- The copper sheets lie on the faces of the stackup's dielectric, which keeps its own thickness. Before, each
  sheet sat at the middle of its copper layer, so a 0.73 mm dielectric was modelled 0.765 mm thick.
- Mesh: lines come only from copper edges along x or y (within 5°), plus the antenna's extent, the port and the
  vias. An arc or a diagonal no longer gives a line per facet; the cell grid over the antenna resolves it
  (the rule pcbmodelgen and kicad2ems use). 6–33 % fewer cells on the example boards.
- Mesh: the largest cell is sized at the top of the sweep (f0 + fc), not at the top of the excitation.

### Fixed
- The mesh could drop a port plane that fell within a third of a cell of a copper edge (a feed pad a
  little narrower than its trace): the port collapsed to zero width and S11 came out 0 dB.
- Two copper-edge mesh lines closer than a third of a cell now merge into one line midway between them
  (the rule from OpenEMSH) instead of keeping the first, so the copper stays centred.
- Fast mode: a long straight ground edge next to the port was missed (its middle was far from the port),
  so the mesh could merge the feed gap away.

## v0.2.0 (2026-11-10)

### Added
- **Fast mode, now the default** (plugin and `--mode fast`): S11, Zin, resonance and the −10 dB band
  in seconds to a minute, for each tuning step. Rougher model (no thirds-rule lines, MUR, λ/8 air,
  −30 dB) and no far field; the resonance comes out about 1–2 % below Coarse. Coarse and Fine are
  unchanged.
- The plugin explains the chosen mode in a line under the fields.
- **Results tab** in the plugin: the summary and a Plot choice (S11 / Zin, Smith, Pattern, Model),
  scaled to the window. Click a plot to open it full size. The window switches to it when a run ends.
- **Copy log** and **Clear log** buttons.
- **Several overlays:** `measured1.s1p`, `measured2.s1p`, … in the run folder are drawn along with
  `measured.s1p`, each in its own colour with a legend, and each gets a line in the summary.
- **Plastic case** (`--case`, plugin: **Around the board**): a box shell of one plastic around the
  board, with εr, loss tangent, wall and the gaps at the sides, top and bottom. On the openEMS IFA
  example ABS 2 mm at 1 / 5 / 10 mm gaps moves the resonance from 2408 MHz in air to 2181 / 2330 / 2394 MHz.
- **Run history:** each run keeps the result it replaces in `history/<REF>_<mode>_<date-time>.s1p`
  and overlays the last two earlier runs of the same mode, so antenna versions compare by themselves.
- Tuning (skill): the next antenna length is predicted from two runs (resonance goes as 1/length)
  instead of guessed; usually the third run lands within ~1 %.
- `fp_tools.py save-footprint ... NOTE`: the note (version, mode, resonance, run folder) goes into the
  saved footprint's description.
- Example `examples/openems_ifa/`: openEMS's own `inverted_f.m` antenna as a KiCad board.

### Changed
- S11 / Zin plot: zoomed to f0 ± 15 % (widened to the −10 dB band), target band shaded, resonance
  and −10 dB edges marked, bigger text.
- A saved plugin mode from 0.1.0 (a list index) keeps meaning the same mode.

### Fixed
- Fast mode shorted the port when ground copper sat within ~0.25 mm of the feed pad (a pour around the
  pad with 0.2 mm clearance): its mesh merged the clearance away. Typical with an in-plane port (no
  ground under the feed), S11 0 dB and Zin 0. Fast now puts mesh lines on the ground edges around the
  feed. Coarse and Fine were not affected and are unchanged.
- The resonance was the deepest point of the whole sweep, which can be a higher mode or the feed far
  from f0. It is now the -10 dB dip nearest f0 (else the nearest dip at least 1 dB deep, else the
  deepest point, as before). The -10 dB band and the pattern frequency follow it.
- Octave failed at start with "OpenBLAS error: Memory allocation still failed" on some machines
  (one OpenBLAS thread per core). Octave now runs with `OPENBLAS_NUM_THREADS=1` unless you set it.
- A footprint with the reference `ANT` or `AE` (no number) was not picked automatically.
- The pattern plot was empty: the dB conversion floored the far field at 1e-9, above the actual
  field values (~1e-13), so every point came out at +63 dBi, off the plot. The floor is now 120 dB
  below the peak. The gain table and the `.vtk` were not affected.
- Two runs in the same run folder (the plugin and the command line, or two command lines) wrecked
  each other's field dumps. The second one is now refused.
- Part of the antenna was missing from the model when its copper polygon was not simple (KiCad's
  keyhole slit around a drill, a zero-width spike), e.g. the TI SWRA117D footprint. The polygon is
  now split into simple pieces; slits and spikes are dropped, holes are filled.

## v0.1.0 (2026-11-10)

First public version. KiCad 10 (SWIG action plugin), status: testing.

### Added
- **KiCad plugin**: a toolbar button in the PCB editor. Mode, f0, band, ground net, feed pad
  (*Use selected pad*), Octave path, openEMS folder; progress from the openEMS log; **Stop**;
  **Open results folder** and **Open run folder**. It fills the zones and runs on a copy of the
  board, so the board file is not changed.
- Plugin window: **Output in** (where the run folder is made), **Show the 3D model** in openEMS's
  viewer (`--view` on the command line), **Theme** (System / Light / Dark); the window can be
  resized and maximized and remembers its size; the log wraps long lines.
- The run folder holds the whole model as Octave files: `antenna_geom.m`, a copy of
  `antenna_sim.m`, and `run_sim.m` with the run's settings, to run it again by hand.
- **Command line** `scripts/kicad2ant.py` and the Claude Code skill.
- Ground net found by name when the antenna has no pad 2 and no net is called `GND`
  (`AGND`, `GNDA`, `VSS`, `0V`, ... also inside a sheet path).
- GND tracks are part of the ground model, not only zone fills and vias.
- Finds openEMS source builds on Linux / macOS (`share/openEMS/matlab`) and picks the newest
  Octave on Windows.
- PCM package `com.github.sijah.kicad2ant-<version>.zip` built by `kicad_plugin/build_pcm.py`.

### Known limits
- Not tested in this version: Linux, macOS, paths with non-English letters.
- f0 below 100 MHz is refused.
