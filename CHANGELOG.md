# Changelog — kicad2ant

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
