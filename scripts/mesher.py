"""kicad2ant mesher: the openEMS grid lines (mm) for antenna_geom.m. Plain Python, no dependencies.

Rules (docs/MESHING_PLAN.md stage 1, from a commercial EM tool's manual, pyems, kicad2ems, EMShrimulator, OpenEMSH):
- lines exactly on the straight copper edges, the vias, the port planes and the port centre; no thirds-rule
  pairs, which merge into one line on a trace as wide as the cell (docs/MESHING.md section 7);
- lines closer than `merge` become one: a kept line (port) wins, else the midpoint; no chaining;
- every gap between two such lines over the antenna gets at least `nmin` cells (pyems min_lines), so a trace
  never shrinks to one line;
- each gap is filled from both ends with cells growing by at most RATIO up to its region's largest cell
  (kicad2ems smooth_lines), so neighbouring cells never jump.
"""
import math

C0 = 299792458.0
RATIO = 1.3
MERGE = 0.05    # mm: copper edges closer than this get one line (a commercial EM tool's default); smaller cells shrink the timestep
# Every run setting, per mode: the plugin's Simulation tab shows these, --set KEY=VALUE overrides one.
# mesh (here): cell: largest cell over the antenna (mm); nmin: least cells across any gap there; nz: least cells
# through a dielectric; merge: copper edges closer than this get one line (mm); ratio: largest neighbour cell ratio;
# air: air around the board (mm, 0 = max(5 mm, lambda/4)); f_start / f_stop: the sweep (MHz, 0 = f0 -/+ 40 %).
# run (antenna_sim.m): npts: sweep points; nrts: step limit; end_db: openEMS end criterion (always PML_8: MUR was 2.5 % off);
# threads: openEMS threads (0 = all); pattern: far field (gain, efficiency, pattern); f_pat: pattern frequency (MHz,
# 0 = the resonance); pat_step: full-sphere step (deg)
_RUN = dict(merge=MERGE, ratio=RATIO, air=0.0, f_start=0.0, f_stop=0.0, npts=801, nrts=300000, threads=0,
            f_pat=0.0, pat_step=5.0)
MODES = {'fast':   dict(_RUN, cell=0.5,  nmin=2, air_div=15, nz=2, end_db=-30.0, pattern=0),
         'coarse': dict(_RUN, cell=0.25, nmin=3, air_div=15, nz=4, end_db=-40.0, pattern=1),
         'fine':   dict(_RUN, cell=0.15, nmin=4, air_div=20, nz=4, end_db=-50.0, pattern=1)}


def settings(mode, sets=()):
    """The mode's settings with the KEY=VALUE overrides in sets. ValueError on an unknown key or a bad value."""
    m = dict(MODES[mode])
    for kv in sets:
        k, _, v = kv.partition('=')
        if k not in m: raise ValueError(f'unknown setting {k} (known: {", ".join(sorted(m))})')
        m[k] = type(m[k])(float(v))
    ok = (m['cell'] > 0 and m['nmin'] >= 1 and m['nz'] >= 1 and m['merge'] >= 0 and m['ratio'] > 1 and m['air'] >= 0
          and m['npts'] >= 2 and m['nrts'] >= 1 and m['end_db'] < 0 and m['threads'] >= 0 and m['pat_step'] > 0
          and m['pattern'] in (0, 1) and m['f_start'] >= 0 and m['f_pat'] >= 0
          and (m['f_stop'] == 0 or m['f_stop'] > m['f_start']))
    if not ok: raise ValueError(f'bad setting in {" ".join(sets)}')
    return m


def sweep(m, f0):
    """(start, stop) of the sweep, Hz: f0 -/+ 40 % unless set."""
    return (m['f_start'] * 1e6 or f0 * 0.6), (m['f_stop'] * 1e6 or f0 * 1.4)


def fill(a, b, s0, s1, smax, r=RATIO):
    """The lines strictly inside (a, b): cells start at s0 next to a and s1 next to b and grow by at most r toward
    the middle, never above smax. The middle cell takes what is left; a sliver there is spread over the others."""
    rem, L, R = b - a, [], []
    while True:
        nl = min(smax, L[-1] * r if L else s0)
        nr = min(smax, R[-1] * r if R else s1)
        d = min(nl, nr)
        if d >= rem - 1e-9: break
        (L if nl <= nr else R).append(d); rem -= d
    cand = [L + [rem] + R[::-1]]              # the middle cell as it falls, the others stretched over it, or equal cells
    if L or R:
        st = L + R[::-1]; k = (b - a) / sum(st)
        if max(st) * k <= smax * r: cand.append([c * k for c in st])
    n = math.ceil((b - a) / smax - 1e-9); cand.append([(b - a) / n] * n)
    cells = min(cand, key=lambda c: ratio_cells([s0] + c + [s1]))
    out, x = [], a
    for c in cells[:-1]: x += c; out.append(x)
    return out


def axis(keep, edges, other, sizes, merge, r=RATIO):
    """Grid lines on one axis. keep: lines that never move (port planes); edges: copper edges, wanted exactly;
    other: further lines wanted exactly (vias, hints, region and domain limits); sizes(a, b) -> (largest cell,
    least cells) for the gap a..b. The least cells count across the span between the copper edges around a gap,
    so a hint line inside a trace does not double its cells."""
    pts = sorted([(round(v, 6), 2) for v in keep] + [(round(v, 6), 1) for v in edges] + [(round(v, 6), 0) for v in other])
    H, E, cl = [], [], [pts[0]]
    for p in pts[1:] + [(math.inf, 0)]:
        if p[0] - cl[0][0] <= merge + 1e-9: cl.append(p); continue
        k = sorted({v for v, f in cl if f == 2})
        rep = k or [(cl[0][0] + cl[-1][0]) / 2]
        H += rep
        if any(f == 1 for _, f in cl): E += rep   # copper edges only: a port plane or via is no trace edge
        cl = [p]
    H, E = sorted(set(H)), sorted(set(E))
    gaps = list(zip(H, H[1:]))
    s = []
    for a, b in gaps:
        c, n = sizes(a, b)
        lo = max([e for e in E if e <= a + 1e-9], default=None)
        hi = min([e for e in E if e >= b - 1e-9], default=None)
        if lo is not None and hi is not None: c = min(c, (hi - lo) / n)   # a trace or gap: at least n cells across
        c = min(max(c, merge), b - a)   # never below the merge distance: a 0.07 mm pad-to-trace step got 0.024 mm cells (AN1088)
        s.append((b - a) / math.ceil((b - a) / c - 1e-9))   # the cell that fits whole: what the neighbours really meet
    # the cell at each line: no bigger than a small cell elsewhere can grow to by then (cells grow by RATIO, so
    # about (RATIO - 1) * distance), so a short gap next to fine cells never has to end on a big cell
    h = [min(sj + (r - 1) * 0.9 * max(0.0, a - x, x - b) for sj, (a, b) in zip(s, gaps)) for x in H]
    out = list(H)
    for i, (a, b) in enumerate(gaps):
        out += fill(a, b, min(s[i], h[i]), min(s[i], h[i + 1]), s[i], r)
    return repair(sorted(out))


def repair(v, rmax=1.5, reach=6):
    """Halve a cell more than rmax times a neighbour (easyMesh4openEMS's ratio repair). Each gap is filled
    knowing only its neighbours' limits, not the cells they end up with; this catches the jumps that leaves.
    It only adds lines, so the copper edges stay. A halved cell leaves the cell beyond it twice as big, so that one
    is halved too; on a graded ramp that never stops (TI DN007 fast: 3x the cells, 7x the time), so a jump is
    repaired only when the chain ends within `reach` cells (a bump), and a step in a ramp is left as it is."""
    for _ in range(1000):
        d = [b - a for a, b in zip(v, v[1:])]
        cut = _chain(d, rmax, reach)
        if cut is None: return v
        v = sorted(v + [(v[k] + v[k + 1]) / 2 for k in cut])
    return v


def _chain(d, rmax, reach):
    """The cells to halve for the first jump that a short chain fixes, or None."""
    big = lambda p, q: p > rmax * q + 1e-9
    for i in range(len(d)):
        for s in (-1, 1):                                    # s: the side of the small neighbour
            if not (0 <= i + s < len(d) and big(d[i], d[i + s])): continue
            cut = [i]
            while 0 <= cut[-1] - s < len(d) and big(d[cut[-1] - s], d[cut[-1]] / 2):
                cut.append(cut[-1] - s)
                if len(cut) > reach: break
            else:
                return cut
    return None


def ratio_cells(d):
    return max(max(p / q, q / p) for p, q in zip(d, d[1:])) if len(d) > 1 else 1.0


def ratio(v):
    """Worst ratio between neighbouring cells of the grid lines v."""
    return ratio_cells([b - a for a, b in zip(v, v[1:])])


def check(grid, port, cu_z, diel, tol=1e-4):
    """Problems that would make openEMS drop part of the model, on the final lines (as written, 4 decimals):
    a copper sheet or dielectric face off the z lines (the sheet is ignored), a port plane off the lines, or no line
    inside the port (a line port off the grid excites nothing). [] when the grid is usable."""
    on = lambda v, k: any(abs(v - g) <= tol for g in grid[k])
    bad = [f'copper sheet z = {z:g} mm is not a z line' for z in cu_z if not on(z, 'z')]
    bad += [f'dielectric face z = {z:g} mm is not a z line' for d in diel for z in d[:2] if not on(z, 'z')]
    for a, k in enumerate('xyz'):
        lo, hi = sorted((port[a], port[a + 3]))
        bad += [f'port plane {k} = {v:g} mm is not a {k} line' for v in (lo, hi) if not on(v, k)]
        if hi - lo > tol and not any(lo + tol < g < hi - tol for g in grid[k]):
            bad.append(f'no {k} line inside the port ({lo:g}..{hi:g} mm)')
    for k in 'xyz':
        v = grid[k]
        if any(b - a <= 0 for a, b in zip(v, v[1:])): bad.append(f'{k} lines not strictly increasing')
    return bad


def build(mode, f0, ant_box, edges, hints, port, port_gnd, vias, outline, cu_z, diel, case=None, sets=()):
    """x, y, z grid lines (mm), before the PML cells antenna_sim.m adds. edges/hints/port_gnd: per axis (x, y)
    lists of coordinates; vias: (x, y); outline: ring of (x, y); diel: (z0, z1, epsR, tand); case: the six
    case_box values or None; sets: KEY=VALUE overrides (settings()). The sweep must agree with antenna_sim.m's."""
    m = settings(mode, sets)
    lam = C0 / sweep(m, f0)[1] * 1e3                 # shortest wavelength of the sweep
    air = m['air'] or max(5.0, C0 / f0 * 1e3 / 4)   # fast had lambda/8 and MUR: 2.5 % off on the printed IFA, -9 dB on AN043
    dmax = lam / m['air_div']
    d_sub = lam / math.sqrt(max(d[2] for d in diel)) / m['air_div']
    zmax = max(cu_z)
    bb = [min(p[0] for p in outline), min(p[1] for p in outline), max(p[0] for p in outline), max(p[1] for p in outline)]
    co = [bb[0], bb[1], 0.0, bb[2], bb[3], zmax]     # what the air is measured from: the board, or the case's outside
    gb, dg, cl = [bb[0], bb[1], 0.0, bb[2], bb[3], zmax], d_sub, [[], [], []]
    if case:
        w = case[2]
        ci = [bb[0] - case[3], bb[1] - case[3], -case[5], bb[2] + case[3], bb[3] + case[3], zmax + case[4]]
        co = [ci[0] - w, ci[1] - w, ci[2] - w, ci[3] + w, ci[4] + w, ci[5] + w]
        cl = [[co[a], ci[a], ci[a + 3], co[a + 3]] for a in range(3)]
        gb, dg = co, min(d_sub, lam / math.sqrt(case[0]) / m['air_div'])
    ar = [ant_box[0] - 3, ant_box[1] - 3, ant_box[2] + 3, ant_box[3] + 3]   # the antenna region

    def sizes_xy(a, lo, hi):
        mid = (lo + hi) / 2
        if ar[a] <= mid <= ar[a + 2]: return m['cell'], m['nmin']
        if gb[a] <= mid <= gb[a + 3]: return dg, 1
        return dmax, 1
    out = {}
    for a, k in enumerate('xy'):
        keep = [port[a], port[a + 3]]       # the line port at the pad centre snaps to the nearest line
        other = (list(hints[a]) + [(port[a] + port[a + 3]) / 2] + [v[a] for v in vias if ar[0] <= v[0] <= ar[2] and ar[1] <= v[1] <= ar[3]]
                 + [ar[a], ar[a + 2], bb[a], bb[a + 2], gb[a], gb[a + 3]] + cl[a] + [co[a] - air, co[a + 3] + air])
        out[k] = axis(keep, list(edges[a]) + list(port_gnd[a]), other, lambda lo, hi, a=a: sizes_xy(a, lo, hi), m['merge'], m['ratio'])

    def sizes_z(lo, hi):
        mid = (lo + hi) / 2
        for z0, z1, er, _ in diel:
            if z0 <= mid <= z1: return (z1 - z0) / max(m['nz'], math.ceil((z1 - z0) / m['cell'])), 1
        if gb[2] <= mid <= gb[5]: return dg, 1
        return dmax, 1
    hz = list(cu_z) + [d[0] for d in diel] + [d[1] for d in diel] + cl[2] + [co[2] - air, co[5] + air]
    out['z'] = axis([], [], hz, sizes_z, min(d[1] - d[0] for d in diel) / 20, m['ratio'])
    return out
