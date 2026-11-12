# The kicad2ant mesher

How kicad2ant builds the openEMS grid since the mesh rewrite (2026-11-12): the architecture, the problems the
old mesh had, and what changed. The old mesh is described in `docs/MESHING.md`, and the survey of other tools
in `docs/MESHING_PLAN.md`.

## 1. Why the mesh matters

openEMS is FDTD on a rectilinear grid. kicad2ant models copper as zero-thickness PEC sheets, so copper
exists only on grid lines. Where the lines fall decides how wide each trace and gap looks to the solver.
A trace that lands on one line behaves like a thin wire. If the lines miss the copper edge, the trace
looks wider or narrower than drawn. Either way, the resonance moves and the match is lost.

## 2. Architecture

```
.kicad_pcb ──> extract_antenna.py ──> mesher.py ──> antenna_geom.m ──> antenna_sim.m ──> openEMS
               copper, edges, port,   grid_x/y/z    (geometry +        uses the grid
               vias, outline, stackup  lines (mm)    grid lines)        as is, adds PML
```

| Part | Job |
|---|---|
| `scripts/extract_antenna.py` | Reads the board and collects what the mesh must respect: straight antenna edges, ground edges near the feed, via centres, the port, the outline, copper heights and dielectrics. It calls `mesher.build()` and writes `geom.grid_x`, `grid_y`, `grid_z` and the worst neighbour ratio into `antenna_geom.m`. New options: `--mode`, `--f0`, `--case`. |
| `scripts/mesher.py` | The mesher. Plain Python, no dependencies, tested in CI (`scripts/test_mesher.py`). |
| `scripts/kicad2ant.py` | Passes `--mode` (dry runs use coarse), `--f0` and `--case` to the extractor. |
| `scripts/antenna_sim.m` | Uses `geom.grid_*` unchanged. It only adds the 8 PML cells on each side and places the NF2FF box. It stops with a clear message if `antenna_geom.m` comes from an older kicad2ant (no grid lines). |

**Why Python and not Octave:** the mesh decides the accuracy, so it must be tested. Python runs in CI on
Linux, Windows and macOS without Octave or openEMS. Octave keeps the model build, the solver run and the
post-processing. Converting to Octave was not the cause of the error. The reference XML ran in the same openEMS
and matched reference exactly.

### 2.1 Inside `mesher.py`

| Function | What it does |
|---|---|
| `build(mode, f0, ...)` | Sets the cell sizes per region and builds the line sets for x, y and z. Regions: the antenna area (antenna box + 3 mm), the board or plastic case, and the air. |
| `axis(keep, edges, other, sizes, merge)` | Builds one axis (steps below). |
| `fill(a, b, s0, s1, smax)` | Fills one gap with cells that start at `s0` and `s1` at its ends and grow by at most 1.3 toward the middle, never above `smax`. It tries three layouts (middle remainder, stretched, equal cells) and keeps the one with the best ratio. |
| `ratio(v)` | The worst ratio between neighbouring cells, for the run print and the tests. |

`axis()` works in five steps:

1. **Collect** the lines with a priority: `keep` (port planes) > `edges` (copper edges) > `other` (via
   centres, hints, region limits, air limits).
2. **Merge** lines closer than 0.05 mm into one. A kept line wins; otherwise the midpoint. Each cluster is
   measured from its first line, so merges never chain along a row of lines.
3. **Size each gap**: `min(region cell, copper span / nmin, gap)`. The copper span is measured between the
   copper edges around the gap, so a hint line inside a trace does not double its cells.
4. **Limit the size at each line**: no bigger than a nearby small cell can grow to by that distance
   (about 0.3 × distance). A short gap next to fine cells then never has to end on a big cell.
5. **Fill** every gap with `fill()`.

### 2.2 Settings per mode

| Mode | Largest cell over the antenna | Least cells across a trace or gap | Least cells through a dielectric | Air cell |
|---|---|---|---|---|
| fast | 0.5 mm | 2 | 2 | λ/15 |
| coarse | 0.25 mm | 3 | 4 | λ/15 |
| fine | 0.15 mm | 4 | 4 | λ/20 |

λ is the shortest wavelength in the sweep, at f0 + 0.4 f0. Inside the board the largest cell is
λ/√εr/`air_div`. Grading ratio: 1.3. Merge distance: 0.05 mm.

## 3. Problems with the old mesh

Found on the TI AN043 MIFA (0.5 mm meandered traces) against a commercial EM tool and its exported openEMS XML.

| Run | Resonance | Min S11 |
|---|---|---|
| reference / XML (reference) | 2446 MHz | −32.2 dB |
| Old mesh, coarse | 2469 MHz | −4.5 dB |
| Old mesh, fine | 2547 MHz | −4.7 dB |

A bisection pinned down the causes. The kicad2ant model on the reference's mesh gave −15.5 dB at 2452 MHz, so the
mesh was the main error. the reference's XML with kicad2ant's box port gave −21.2 dB, so the port was the second one.

| # | Problem | Effect |
|---|---|---|
| 1 | **Traces collapsed to one line.** The thirds-rule lines inside a 0.5 mm trace were 0.167 mm apart, exactly the merge distance, so they merged into one line. | The 0.5 mm arms became thin wires. |
| 2 | **No line on the copper edge.** The edge came only from the thirds pair, which merging broke. | Traces looked wider or narrower than drawn, and different in different places. |
| 3 | **No minimum cells across a trace or gap.** | 39 x lines over the antenna, against 111 for reference. |
| 4 | **Cell jumps up to 4.35×.** A second merge pass after smoothing undid the smoothing. | Numerical reflections. |
| 5 | **Fixed cell size**, whatever the geometry. Fine mode just made the same mistakes smaller. | Fine mode was no better than coarse. |
| 6 | **Box port** over the whole 0.5 × 0.5 mm pad. | On its own, moved the reference from −32 to −21 dB. |
| 7 | **The mesh lived in Octave.** | Could not be tested in CI. |

## 4. What changed

| Old | New | Fixes |
|---|---|---|
| Thirds-rule pairs next to each edge | A line exactly on every straight copper edge | 1, 2 |
| Merge at `cell/3`, chaining, midpoint | Merge at 0.05 mm, port wins, no chaining | 1 |
| Nothing | At least `nmin` cells (2 / 3 / 4) across every span between copper edges | 3, 5 |
| `SmoothMeshLines` + second merge pass | One pass: two-sided geometric fill at 1.3, size-at-line limit | 4 |
| Fixed `cell_ant` 0.5 / 0.2 mm | Region cell sizes; the copper sets the smallest cells | 5 |
| Lumped port box over the pad | Line port through the pad centre, from the feed layer to ground | 6 |
| Mesh in `antenna_sim.m` | `scripts/mesher.py`, tests in `scripts/test_mesher.py`, run in CI | 7 |

**Mesh on AN043 (cells include PML):**

| Mode | Old: worst ratio | New: worst ratio | New: cells | New: smallest cell |
|---|---|---|---|---|
| fast | – | 1.80 | 0.28 M | 0.150 mm |
| coarse | 4.35 | 1.41 | 0.77 M | 0.100 mm |
| fine | 4.33 | 1.30 | 1.74 M | 0.075 mm |

Each 0.5 mm trace now gets 3 cells across in coarse mode, with lines on both edges.

**Simulation result, AN043 coarse (board εr 4.5, 0.77 M cells, 522 s):**

| Run | Resonance | Min S11 | −10 dB band | Zin at 2440 MHz | D / η / G at 2440 MHz |
|---|---|---|---|---|---|
| reference / XML (reference, εr 4.4) | 2446 MHz | −32.2 dB | 2364–2540 MHz | about 47 Ω | 2.13 dBi / 89.9 % / 1.67 dBi |
| Old mesh, coarse | 2469 MHz | −4.5 dB | none | 14.6+j19.1 Ω | about the same |
| **New mesher, coarse** | **2399 MHz** | **−19.7 dB** | **2320–2484 MHz** | **36.0+j8.1 Ω** | **2.12 dBi / 90 % / 1.67 dBi** |

The match is back: from no −10 dB band to −19.7 dB with the whole 2.4 GHz band covered. The resonance is
now 1.9 % low, outside the 1 % target.

The board's εr is 4.5 and the reference's model uses 4.4. A copy of the board at εr 4.4 gave 2408 MHz, −20.9 dB,
band 2333–2496 MHz, Zin 38.3+j5.2 Ω. So εr explains only 9 MHz. The remaining 1.5 % comes from the mesh
or the port. Next tests: the new mesh with the old box port, and lines on the edges against the thirds
rule.

**Simulation result, printed IFA coarse.** The board is a scratch copy with a 0.8 mm core, εr 4.4, to match
the reference's model. The run took 510 s on 0.86 M cells. Both runs were stopped at about −28 dB, since this antenna
rings slowly; the XML S11 matched the reference's report there anyway.

| Run | Resonance | Min S11 | Zin at resonance | −10 dB band | D / η / G |
|---|---|---|---|---|---|
| reference report | 2451 MHz | −25.4 dB | 52.8+j4.7 Ω | 2315–2616 MHz | 2.81 dBi / 94 % / 2.53 dBi |
| reference XML in openEMS | 2450 MHz | −25.7 dB | 52.8+j4.5 Ω | 2315–2615 MHz | – |
| **New mesher** | **2462 MHz (+0.45 %)** | **−24.5 dB** | **53.9+j4.8 Ω** | **2330–2613 MHz** | **2.83 dBi / 93 % / 2.52 dBi** |

Within the 1 % target on resonance and both band edges, with Zin within about 1 Ω.

**Fast against coarse.** Both boards use the same copies as above: the printed IFA with a 0.8 mm core, and
AN043 at εr 4.4.

| Board | Run | Cells | Time | Resonance | Min S11 | −10 dB band |
|---|---|---|---|---|---|---|
| printed IFA | reference | 0.79 M | – | 2451 MHz | −25.4 dB | 2315–2616 |
| | coarse | 0.86 M | 510 s | 2462 (+0.45 %) | −24.5 dB | 2330–2613 |
| | fast, old boundary (MUR, λ/8 air) | 0.14 M | 33 s | 2389 (−2.5 %) | −38.1 dB | 2281–2542 |
| | **fast, now (PML, λ/4 air)** | 0.46 M | **130 s** | **2467 (+0.65 %)** | **−27.0 dB** | **2330–2616** |
| AN043, εr 4.4 | reference | 0.61 M | – | 2446 MHz | −32.2 dB | 2364–2540 |
| | coarse | 0.76 M | 306 s | 2416 (−1.2 %) | −20.8 dB | 2335–2503 |
| | fast, old boundary | 0.10 M | 13 s | 2428 (−0.7 %) | −8.8 dB | none |
| | **fast, now** | 0.34 M | **72 s** | **2428 (−0.7 %)** | **−22.1 dB** | **2342–2525** |

Fast mode with the coarse mesh but the old boundary gave the same wrong numbers. So the error came from
the boundary, not the mesh. Fast now uses the same PML and λ/4 air as coarse; it keeps the coarser mesh,
stops at −30 dB and skips the far field. That makes it about 4× faster than coarse, within about 0.5 % of
it. The PML cells now copy the size of the last air cell on each side, which removed a 1.9× jump into the
PML.

### 4.1 Bugs found while building it

- The feed pad got 6 cells of 0.083 mm, because the port-centre line and a via line split it. Fix: no
  port-centre keep line, and `nmin` counts between copper edges, not hint lines.
- Edges 0.03 mm apart made 0.0075 mm cells in fine mode, which shrinks the timestep. Fix: merge at 0.05 mm.
- A thin leftover cell in the middle of a gap gave ratio 1.6. Fix: `fill()` picks among three layouts.
- The board edge jumped 1.84 → 2.97 mm, because a 7 mm gap could not grow from 0.25 mm to the board cell.
  Fix: limit the size at each line (step 4).
- The PCM zip did not include `mesher.py`, so the plugin would have failed. Fix: added to `build_pcm.py`.
- The line port at the pad centre had no grid line under it, so openEMS dropped it. The first run spent
  11 minutes with zero energy. Fix: a line through the pad centre, the port snapped to the nearest line in
  `antenna_sim.m`, and the check below.
- The pad-centre line split the pad into 0.125 mm cells, but the neighbours were graded from the 0.167 mm
  target, giving ratio 1.49. Fix: each gap uses the cell that fits it whole.
- printed IFA: 2.74 M cells with 0.033 mm cells. A via 0.1 mm from a trace edge got the "3 cells across"
  rule. Fix: the rule applies only between two copper edges, and port planes and vias don't count.
- printed IFA: ground vias in the footprint, 40 mm down the board, stretched the antenna box over the
  whole ground plane. Fix: ground-net pads are left out of the antenna box. Now 0.83 M cells, against
  the reference's 0.79 M.
- A port pad with 0.25 mm cells next to 0.15 mm trace cells gave ratio 1.67. Fix: a final repair pass
  halves any cell more than 1.5× a neighbour (easyMesh4openEMS's idea). Worst ratio is now 1.3 on AN043
  and the printed IFA in every mode, and 1.3–1.48 on ti_ifa.
- That repair pass cascaded. Halving a cell leaves the cell beyond it twice as big, so it is halved too,
  and on a ramp graded at 1.3 this runs out to the domain edge. TI DN007 fast had 180 y lines with
  0.05 mm cells, more than coarse, and took 960 s. Fix: a jump is repaired only when the halving chain
  ends within 6 cells (a bump). A step into a ramp is left as it is, at 1.5–1.9. Fast grids shrank on
  most of the example boards (DN007 0.49 → 0.22 M cells, printed IFA 0.21 → 0.15 M). Coarse is unchanged
  on most boards; on dk10 it went 4.0 → 2.1 M and on a test board 1.07 → 0.70 M.

### 4.2 Checks before the solver

From an outside architecture review (`docs/kicad2ant_evidence_based_recommendations.md`):

- `mesher.check()` runs on the final lines, as written to `antenna_geom.m`. The extractor stops with
  `mesh error` if any of these fails:
  - every copper sheet height and dielectric face is a z line, since openEMS ignores a sheet that is off a
    line;
  - both port planes are grid lines, with a line inside the port;
  - the lines are strictly increasing.
- NF2FF box: the review suggested moving it further from the PML. 4 cells in instead of 1 was tested on
  AN043 and made things worse: D 2.47 dBi and efficiency 76 %, against the reference's 2.13 dBi and 89.9 %, which the
  one-cell box matches. It stays one cell in. `antenna_sim.m` now stops if the box would cut the board or
  the case.

Worst neighbour ratio on AN043 after all the fixes (4.1):

| Mode | Board in air | With a plastic case (3 0.01 2 1 1 1) |
|---|---|---|
| fast | 1.3 | 1.32 |
| coarse | 1.3 | 1.32 |
| fine | 1.3 | 1.45 |

## 5. Limits and next steps

- Diagonal and arc edges get no lines of their own. The region cell has to resolve them.
- No grading in z next to the copper sheets yet (kicad2ems measured a big gain from it on a GCPW).
- `--post` on run folders made by an older kicad2ant stops with a message. Run the board again.
- Next, from `docs/MESHING_PLAN.md`: a pre-solve check that rasterises the copper onto the grid and refines
  where traces or gaps come out wrong (stage 2), then an opt-in `--converge` that refines until S11
  stops changing (stage 3).

## 6. Credits

Ideas, not code, from:
- pyems: least lines per interval.
- kicad2ems: two-sided grading, merge by priority.
- EMShrimulator: lines exactly on the edges, a minimum number of cells in a gap.
- OpenEMSH: the thirds-collapse analysis.
- a commercial EM tool's manual: 0.05 mm merge, 1.3 grading, line port.
