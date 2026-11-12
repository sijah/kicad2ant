# kicad2ant meshing: survey and improvement plan

This plan is the companion to `docs/MESHING.md`, which describes today's mesh and why it fails on the
TI AN043 MIFA (S11 −4.5 dB against −32 dB for the reference). The goal is a mesh that is accurate without
hand-tuning, and checks itself.

**Status: proposal, nothing built yet (2026-11-12).** The survey was a read-only reading of the source; none
of the other tools was run.

## 1. What the other projects do

kicad2ant is GPL-3.0-or-later, so code from the GPL-3,
Apache and MIT projects can be reused with credit. a commercial EM tool and the kicad_ems solver are closed:
take ideas from their manuals and outputs only.

| Project (licence) | Lines at copper edges | Thin traces and gaps | Merge | Grading | z | Adaptive |
|---|---|---|---|---|---|---|
| **pyems** (GPL-3) | thirds rule, chosen per interval; a fixed line on zero-thickness metal | every interval, smallest first, gets ≥ `min_lines` (5) lines: `spacing = min(res, dist/(min_lines-1))`. Spacing at an already-meshed boundary is capped at 3× (metal) or 1.5× (dielectric) the nearest line | none; meshing order plus min spacing | exact geometric series filling each interval, graded from both ends, 1.2 per axis | substrate is just another interval, ≥5 lines | none; warns when ratio ≥ smooth, checks the PML is uniform |
| **easyMesh4openEMS** (GPL-3 / MIT) | thirds; the metal side found by a point-in-polygon probe, so any polygon works | smallest gap under λ/60 sets the global smallest cell = gap/(n−1); gaps filled with ≥4 lines when the edges overlap | an on-edge line wins, else midpoint; edge ties broken by priority, then length | `SmoothMeshLines` 1.3, max cell λ/√ε per material, plus a **ratio-repair pass** that inserts lines where the ratio is ≥2 | ≥4 lines in thin layers | none |
| **kicad2ems** (GPL-3) | narrow thirds pair (+fine/9, −4fine/9) | `fine = min(trace, gap, 2·h)/4`; an extra line every copper width along curves | fine/2, by priority (kept > inside > outside > fill), no chaining or averaging | own two-sided smoother, 1.4 | a line at every interface, ≥4 cells, **first cell next to the copper = fine, graded** (−19.3 → −31.5 dB on GCPW) | 3 mesh levels (f = 1, 1.5, 2), converged if within 0.1 dB / 2°; off for antennas |
| **EMShrimulator** (GPL-3) | exactly on edges, snapped back after smoothing | ≥3 cells in any gap narrower than the target cell | rounding only | `SmoothMeshLines` 1.4 | ≥3 | whole mesh refined 1.3× per pass until max ΔS ≤ 0.02; cell count previewed so no pass is wasted; time-domain ΔS early stop |
| **OpenEMSH** (GPL-3) | per-edge policies: THIRDS / HALFS / ONELINE | ≥2 lines per half-interval; thirds spacing chosen while smoothing | conflict rules: opposite thirds become HALFS at the midpoint; ONELINE always wins | 2 | – | none; diagonal zones capped at λ/60, a 20° vertex rule, buried edges skipped |
| **gerber2ems** (Apache) | thirds, 50 µm cell | none, just a tiny cell | on-edge lines protected, weighted by segment length | 2-series fill, 1.2 | 4 | none |
| **kicad_ems plugin** (MIT; closed solver) | lines nudged onto edges after meshing | ≥2 cells across the feed trace; features under 3 cells split into 3–5 | – | 1.5 | per slab | fine band within 0.25 λ of the feed along the copper; a **pre-solve cell-scan** for trace-width error, shorted gaps and fused or split copper |
| **pcbmodelgen** (GPL-3) | on the edges | none | averages (moves lines off the edges) | 1.5, lists violations | 4 | none |
| **z0-field-solver** (GPL-3) | exactly on the edges; last cell fitted to land on the next edge | f0 = min(w, gap)/24…64 | not needed | linear growth | – | lesson: put edge lines exactly on the copper first; Richardson extrapolation hurt on snapped grids |
| **a commercial EM tool** (closed) | on the edges, 0.15–0.25 mm fill | – | 0.05 mm | 1.3 | 4 | none |

**What they agree on:**
- The cell size follows the geometry.
- Every trace, gap and dielectric gets a minimum number of lines.
- Lines on the copper edges are never merged away.
- Cells grow smoothly, at a ratio of 1.2–1.4.
- z is graded next to the copper.

**What none of them has:** local refinement driven by an error estimate. EMShrimulator and kicad2ems are
the only ones that check convergence at all, and both do it by refining the whole mesh.

## 2. Plan

### Stage 1: correct fixed rules

All of this goes in `scripts/antenna_sim.m`'s mesh section, with hints from `extract_antenna.py`. Stage 1
on its own should fix AN043.

| # | Change | Source | Replaces |
|---|---|---|---|
| 1.1 | `fine = clamp(min(narrowest trace, narrowest gap, 2·h_sub)/4, …)` per run, with the mode as a cap | kicad2ems | fixed `cell_ant` 0.5 / 0.2 |
| 1.2 | The extractor exports intervals per axis (trace widths and gaps between antenna edges, with which side is metal), not just edge coordinates | pyems, easyMesh | `edge_x`, `edge_y` |
| 1.3 | Mesh intervals smallest first; each trace, gap and dielectric gets ≥ N lines (N = 4 coarse, 5 fine) | pyems, EMShrimulator, OpenEMSH | none today |
| 1.4 | Thirds pair sized from the interval's own spacing, not from `cell_ant` | OpenEMSH, pyems | `edge ± cell_ant/3, 2/3` |
| 1.5 | Merge at fine/2 by priority: port and outline > on-edge > inside > outside > fill. No averaging, no chaining | kicad2ems, easyMesh | `antenna_sim.m:113-116` |
| 1.6 | Fill each gap with an exact geometric series from both ends, ratio ≤ 1.3–1.4; one pass, no re-merge afterwards | pyems, kicad2ems, gerber2ems (Apache, reusable) | `SmoothMeshLines` + pass 2 |
| 1.7 | Ratio-repair pass, then assert ratio ≤ 2 | easyMesh, pyems | warning only at 2 |
| 1.8 | z: a line at every interface, ≥4 cells per dielectric, first cell next to the copper = fine, graded | kicad2ems | `linspace` |
| 1.9 | Port: a single line through the feed centre, port planes on lines; option for a line port instead of the pad box | reference, EMShrimulator, kicad2ems | box port over the whole pad |
| 1.10 | Print mesh quality: fewest cells across a trace, smallest cell, worst ratio, cells per λ | z2ems, pcbmodelgen | partial |

Fast mode keeps its own looser settings, but gets the same rules 1.3 (with N = 2), 1.5 and 1.9, so it
stops collapsing traces too.

### Stage 2: adaptive check before the solve

Costs seconds, needs no FDTD run (kicad_ems cell-scan idea).

1. Rasterise the antenna and ground copper onto the planned grid, the way openEMS will see it.
2. Compare against the drawing:
   - width error of each trace (%);
   - gaps that become shorted;
   - copper that fuses together or splits apart;
   - cells across the narrowest trace.
3. If any check fails, divide `fine` by 1.3 and try again, up to a cell budget. Report what was refined.
4. Option: full fineness only within 0.25 λ of the feed, measured along the copper, with coarser bands
   beyond (kicad_ems).

### Stage 3: adaptive convergence on S11

Opt-in `--converge`, or the plugin's "Verify" button.

1. Run the mesh at `fine`, then `fine/1.3`, `fine/1.69` …
2. Preview the cell count before each run and skip a level that changes nothing (EMShrimulator).
3. Stop when, between the last two levels:
   - |ΔS11| ≤ 0.2 dB over the −10 dB band;
   - Δf_res ≤ 0.5 %;
   - ΔZin ≤ 2 Ω at f0.
   Or after 4 levels, with a warning.
4. Each level ends early with a time-domain ΔS11 check: stop when S11 stops changing, after the pulse has
   crossed the model (EMShrimulator `convergence.py`, rewritten).
5. Report the converged values and the convergence history in the summary.

Later, outside this plan: local refinement near the feed, the short and the open end only, using the
level-to-level difference as the error estimate. None of the surveyed tools does this; it would be new work.

## 3. Validation

Each board has an independent reference.

| Board | Reference | Pass criterion |
|---|---|---|
| `examples/ti_an043_mifa` | a commercial EM tool report + exported XML: 2445 MHz, −32 dB, 2365–2540 MHz | f_res within 1 %, −10 dB band edges within 1 %, Zin at f0 within 5 Ω |
| `examples/printed_ifa` | reference report + XML: 2450 MHz, −25.5 dB | same |
| `examples/ti_ifa` | TI's published numbers, earlier kicad2ant runs | f_res within 1 % |
| `kicad_ems_plugin_examples/nrf_dev_board` | its own meander IFA results | f_res within 1 % |

**Run time and size:**
- Coarse: no more than about 2× today's run time.
- Fast: under 1 minute on AN043.
- Fine and `--converge`: may take longer.

The CI tests (`scripts/test_extract.py`) get fixtures for the new interval export: trace and gap widths, and
which side is metal.

## 4. Order of work

1. Interval export in the extractor, plus tests (1.2).
2. The new x/y mesher (1.1, 1.3–1.7, 1.10), checked on AN043 coarse against the XML.
3. z grading (1.8) and the single-line port (1.9); re-check AN043 and the printed IFA.
4. Fast mode on the new rules; time it.
5. Stage 2, the pre-solve check.
6. Stage 3, `--converge`.
7. Update `docs/MESHING.md`, `docs/USAGE.md`, README credits (pyems, easyMesh4openEMS, EMShrimulator,
   OpenEMSH, kicad2ems, gerber2ems) and CHANGELOG.

## 5. Known bugs in the surveyed code, so they aren't copied

- **pyems:** `set_lines_equidistant(0, …)` hardcodes the x axis (`port.py:587, 921, 1233`). Its smoothness
  test compares an absolute difference with a ratio (`mesh.py:1227-1230`).
- **easyMesh4openEMS:** the diagonal angle is always 45° (`meshingUtils.py:249, 259`). There is a hardcoded
  1.5-unit gap floor (`meshingUtils.py:107, 611`).
- **pcbmodelgen:** averaging line pairs moves lines off the copper edges.
- **EMShrimulator:** puts edge lines only on bounding boxes, so meander interiors get none. Its
  `AddEdges2Grid` lines are added after smoothing and never re-graded.
