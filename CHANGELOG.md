# Changelog — kicad2ant

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
