# kicad2ant meshing: the old mesh

> Replaced by `scripts/mesher.py`. See `docs/MESHER.md` for the new mesher. This file is kept as the
> record of the old method and its failures.

This describes the mesh kicad2ant built as of commit `c310207` (branch `fp2board`), and where it fails.
The code is in two places:

- `scripts/extract_antenna.py:324-370` reads the board and writes mesh hints into `antenna_geom.m`.
- `scripts/antenna_sim.m:41-140` turns the hints into an openEMS rectilinear grid.

openEMS is FDTD on a rectilinear grid. Copper is a zero-thickness PEC sheet, so metal exists only on mesh
lines. Where the lines fall decides how wide a trace looks to the solver.

## 1. Settings per mode

`antenna_sim.m:43-47`

| Setting | fast | coarse | fine |
|---|---|---|---|
| `cell_ant` (largest cell over the antenna, mm) | 0.5 | 0.5 | 0.2 |
| Thirds-rule lines on edges | no, lines on the edges themselves | yes | yes |
| `air_div`: largest cell = λ / `air_div` | 15 | 15 | 20 |
| `nz`: least cells through a dielectric | 2 | 2 | 4 |
| Air on each side | max(5 mm, λ0/8) | max(5 mm, λ0/4) | max(5 mm, λ0/4) |
| Boundary | MUR | PML_8 (+8 cells) | PML_8 (+8 cells) |
| End criterion | 1e-3 (−30 dB) | 1e-4 (−40 dB) | 1e-5 (−50 dB) |
| Smallest gap between lines from different grids | `cell_ant/2` | `cell_ant/4` | `cell_ant/4` |

λ here is `c0 / (f0 + fc)`, the shortest wavelength in the sweep. The largest cell inside the board is
`d_sub = λ / √εr_max / air_div` (`antenna_sim.m:96`).

## 2. Mesh hints from the extractor

`extract_antenna.py:324-370` writes these into `antenna_geom.m`:

| Field | What it holds | How it is found |
|---|---|---|
| `geom.ant_box` | bounding box of the antenna copper | min/max of all antenna polygon points |
| `geom.mesh_x`, `mesh_y` | "low priority" lines | `axis_lines()`: the midpoint coordinate of every antenna edge that runs along an axis (within 5°, at least 0.05 mm long); the same for ground fill edges within 3 mm of the antenna box; plus the antenna box corners, the port corners and the via centres |
| `geom.edge_x`, `edge_y` | straight antenna edges for the thirds rule | each axis-aligned antenna edge, with a side flag: +1 if the metal is above/right, −1 if below/left. Edges with metal on both sides (internal seams between shapes) are dropped |
| `geom.port_gnd_x`, `port_gnd_y` | ground edges near the feed | straight ground edges on the feed layer within 1 mm of the port. Used by fast mode only, so the pad-to-ground gap stays open |
| `geom.port` | the lumped port box | the feed pad, from F.Cu to the ground layer |

Diagonal and arc edges give no hint lines. The regular `cell_ant` grid over the antenna has to resolve them.

## 3. x and y lines

`antenna_sim.m:92-127`, once for x and once for y.

### 3.1 Line sets

**High priority (`pri`)**, the lines to keep:
- The two port planes: `geom.port` min and max on this axis. They are always kept, because dropping one
  collapses the port to zero width.
- Fast mode: a line on every straight antenna edge, plus the ground edges near the port.
- Coarse and fine: two thirds-rule lines per straight antenna edge, `cell_ant/3` inside the metal and
  `2·cell_ant/3` outside it:
  ```
  edge + side * cell_ant/3        (inside)
  edge - side * 2*cell_ant/3      (outside)
  ```
  For 0.5 mm cells that is 0.167 mm inside and 0.333 mm outside. There is no line on the edge itself.

**Low priority (`low`)**, filler that is dropped near a kept line:
- the extractor hints `mesh_x`/`mesh_y`;
- a regular `cell_ant` grid over the antenna box plus 3 mm;
- a regular `d_sub` grid over the board (or over the plastic case);
- the board edges, the case wall faces, and the air limits.

### 3.2 Merging the high-priority lines

Going through the high-priority lines in sorted order (`antenna_sim.m:112-118`):

1. A line within `cell_ant/3` of a port plane is dropped.
2. A line within `cell_ant/3` of the last kept line replaces it with one line midway, as long as the
   midpoint stays clear of the port planes. This is OpenEMSH's rule, meant to keep the copper centred.
3. Otherwise the line is kept.

### 3.3 Adding the filler and smoothing

1. Filler lines within `cell_ant/2` of any kept line are dropped (`antenna_sim.m:120`).
2. All lines are sorted. A line closer than `cell_ant/4` to the previous one is dropped (`cell_ant/2` in
   fast mode), unless it is a kept line (`antenna_sim.m:121-122`).
3. **Pass 1:** the result goes through `SmoothMeshLines(lines, λ/air_div, 1.4)`. The smoothed lines become
   the new filler set and the whole of 3.2 and 3.3 runs again (**pass 2**). Pass 2 does not smooth again, so
   steps 1-2 can reopen ratio jumps that pass 1 had smoothed out.

## 4. z lines

`antenna_sim.m:128-132`

- Fixed lines: every copper height, both faces of every dielectric, the case walls, and the air limits.
- Inside each dielectric: `linspace` with `max(nz, ceil(thickness / cell_ant))` cells. For a 1.6 mm board
  that is 4 cells in coarse (1.6/0.5 rounds up to 4) and 8 in fine (1.6/0.2).
- Rounded to 1e-5 mm, then `SmoothMeshLines(z, λ/air_div, 1.4)`.
- No extra grading next to the copper sheets.

## 5. PML and the result print

- When not in fast mode, 8 cells of `λ/air_div` are added outside the air on every side, for PML_8
  (`antenna_sim.m:133-134`).
- The run prints the cell count, the smallest cell and the worst neighbour ratio (`antenna_sim.m:136-139`).
  The summary flags a ratio above 2 (`antenna_sim.m:297`).
- The NF2FF box sits at mesh index 10 from each end (`antenna_sim.m:140`).

## 6. Other features

| Feature | How it is modelled | Effect on the mesh |
|---|---|---|
| Ground vias | zero-width PEC line from z0 to z1 (`antenna_sim.m:75-77`) | via centre is a filler hint only; openEMS snaps the line to the nearest grid line |
| Feed | lumped port box over the whole feed pad, `AddLumpedPort` (`antenna_sim.m:91`) | port planes kept exactly; no line at the port centre |
| Plastic case | six dielectric boxes | wall faces added as filler; dielectric grid spread over the case |
| Board cutouts | air polygons over the dielectric | no hint lines of their own |

## 7. Known weaknesses: the TI AN043 MIFA test (2026-11-12)

**Test setup.**
- Board: `examples/ti_an043_mifa`, a meandered IFA made of 0.5 mm traces.
- Reference: a commercial EM tool's run and its exported openEMS XML, run directly in openEMS 0.37.
- Bisection runs: in scratchpad only, not in the repo.

### 7.1 Results

| Run | Resonance | Min S11 | −10 dB band | Zin at 2450 MHz |
|---|---|---|---|---|
| a commercial EM tool / XML (reference) | 2446 MHz | −32.2 dB | 2364–2540 MHz | 47.2−j0.1 Ω |
| kicad2ant coarse | 2469 MHz | −4.5 dB | none | 14.6+j19.1 Ω |
| kicad2ant fine | 2547 MHz | −4.7 dB | none | 13.6+j11.6 Ω |
| kicad2ant model on the reference mesh | 2452 MHz | −15.5 dB | 2368–2550 MHz | 37.1−j7.0 Ω |
| Reference XML with kicad2ant's box port | 2472 MHz | −21.2 dB | 2382–2578 MHz | 47.1−j10.9 Ω |
| kicad2ant with the via as a box instead of a line | 2466 MHz | −4.5 dB | none | 14.7+j19.1 Ω |

The copper, feed and via positions in the two models are identical apart from a shift. **The mesh is the
main error, and the box port is a second, smaller one.** The via model does not matter.

### 7.2 What goes wrong

1. **Traces collapse to one line.** With `cell_ant = 0.5` on a 0.5 mm trace, the two inside thirds lines are
   0.167 mm from each edge, so 0.167 mm apart. That is exactly the `cell_ant/3` merge distance, so they
   merge into one line in the middle of the trace (3.2 step 2), and the trace becomes a thin wire.
   - In the AN043 coarse mesh, the 0.5 mm top arms (y 5.15-5.65) get the single line y = 5.4.
   - Some x pairs survive by rounding (x 2.117 and 2.283 on the 1.95-2.45 leg), so different parts of the
     antenna are resolved differently.
2. **No minimum number of cells across a trace or gap.** Nothing checks it. Coarse mode had 39 x lines
   and 18 y lines over the antenna; the reference had 111 and 49.
3. **No line on the copper edge itself.** The edge position comes only from the thirds-rule pair, which
   merging can break.
4. **Fine mode does not fix it.** Fine mode (0.2 mm cells, 0.056 mm smallest cell, 1.02 M cells) gave the
   same bad match. The thirds pairs and the fill still don't line up with the copper, and the neighbour
   ratio stayed at 4.33.
5. **Abrupt cell jumps.** The worst neighbour ratio was 4.35 coarse and 4.33 fine, against 1.3 in the
   reference. Pass 2 re-merges after smoothing and never smooths again.
6. **The cell size does not follow the geometry.** `cell_ant` is a fixed 0.5 or 0.2 mm, whatever the
   narrowest trace or gap is.
7. **Box port.** A lumped port over the whole 0.5 × 0.5 mm pad, against a single-line port in the
   reference. That alone moved the reference from −32.2 to −21.2 dB and shifted it +26 MHz.
8. **Uniform z mesh.** The cells through the dielectric are evenly spaced, with no grading next to the
   copper. A 1.6 mm board gets 4 cells in coarse, but a thin core (under 1 mm) can get only 2. kicad2ems
   measured −19.3 dB uniform vs −31.5 dB graded on a GCPW.
9. **No convergence check.** Nothing shows whether a finer mesh would change the answer.

### 7.3 What still works

Directivity, radiation efficiency and gain agreed with the reference in every run: 2.1 dBi, about 90 %,
1.7 dBi. The far field is not sensitive to this mesh error; S11 and Zin are.

## 8. Reference mesh for comparison

a commercial EM tool, Accurate preset, on the same antenna:

- Lines exactly on every copper edge.
- 0.15 mm fill over the copper, so a 0.5 mm trace gets 4 cells across, with a centre line on the feed
  strip and on the via.
- Lines closer than 0.04 mm merged.
- Grading 1.3.
- 4 cells through the 1.6 mm substrate.
- Largest cell λ/20 at the stop frequency; air λ/2.
- 157 × 99 × 41 = 0.61 M cells.
- The port is a single line.

How other open-source meshers handle these problems, and the plan to fix kicad2ant's mesh, are in
`docs/MESHING_PLAN.md`.
