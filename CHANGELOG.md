# Changelog — kicad2ant

## Unreleased

### Added
- **Fast mode, now the default** (plugin and `--mode fast`): S11, Zin, resonance and the −10 dB band
  in seconds to a minute, for each tuning step. Rougher model (no thirds-rule lines, MUR, λ/8 air,
  −30 dB) and no far field; the resonance comes out about 1–2 % below Coarse. Coarse and Fine are
  unchanged.
- The plugin explains the chosen mode in a line under the fields.
- **Results tab** in the plugin: the summary and a Plot choice (S11 / Zin, Smith, Pattern, Model),
  scaled to the window. Click a plot to open it full size. The window switches to it when a run ends.
- **Copy log** and **Clear log** buttons.
- Example `examples/openems_ifa/`: openEMS's own `inverted_f.m` antenna as a KiCad board.

### Changed
- S11 / Zin plot: zoomed to f0 ± 15 % (widened to the −10 dB band), target band shaded, resonance
  and −10 dB edges marked, bigger text.
- A saved plugin mode from 0.1.0 (a list index) keeps meaning the same mode.

### Fixed
- Octave failed at start with "OpenBLAS error: Memory allocation still failed" on some machines
  (one OpenBLAS thread per core). Octave now runs with `OPENBLAS_NUM_THREADS=1` unless you set it.
- A footprint with the reference `ANT` or `AE` (no number) was not picked automatically.
- The pattern plot was empty: the dB conversion floored the far field at 1e-9, above the actual
  field values (~1e-13), so every point came out at +63 dBi, off the plot. The floor is now 120 dB
  below the peak. The gain table and the `.vtk` were not affected.
- Two runs in the same run folder (the plugin and the command line, or two command lines) wrecked
  each other's field dumps. The second one is now refused.

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
