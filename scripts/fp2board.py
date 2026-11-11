#!/usr/bin/env python3
"""fp2board: put an antenna footprint (.kicad_mod) on a bare board (.kicad_pcb) that kicad2ant can simulate.

  python fp2board.py ANTENNA.kicad_mod [OUT.kicad_pcb] [--thickness MM] [--er ER] [--tand TAND] [--prepreg MM]
                     [--list] [--ground I,J] [--feed-at X Y]

Copper polygons that hold a ground via (pad "2") and are at least 20 % of the largest such polygon become
GND copper shapes on the board, not zones (a zone refill would cut them off the antenna's shorts); without a pad 2 the largest copper polygon is the ground. Everything else
stays in the footprint (reference ANT1) as the antenna. Pad 1 is the feed (net RF), pads 2 are GND.
A feed pad that overlaps the ground on its own layer is moved onto the end of the nearest antenna copper,
so the port spans the gap. --list numbers the copper polygons; --ground I,J adds polygons to the ground;
--feed-at X Y puts pad 1 there (footprint mm) instead. Outline: the bounds of the F.Fab drawing and all copper.
Default OUT: <footprint folder>/<name>/<name>.kicad_pcb, name in lower case without spaces (openEMS limit).
Stackup: 2 layers, or 4 when the footprint uses an inner layer (prepreg on both sides of a core).
"""
import argparse, math, os, re, sys

ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
ap.add_argument('mod'); ap.add_argument('out', nargs='?')
ap.add_argument('--thickness', type=float, default=1.6, help='board thickness, mm (default 1.6)')
ap.add_argument('--er', type=float, default=4.5, help='dielectric epsilon r (default 4.5)')
ap.add_argument('--tand', type=float, default=0.02, help='loss tangent (default 0.02)')
ap.add_argument('--prepreg', type=float, default=0.2, help='4 layers: outer prepreg thickness, mm (default 0.2)')
ap.add_argument('--list', action='store_true', help='list the copper polygons with their numbers and stop')
ap.add_argument('--ground', default='', help='comma list of polygon numbers (from --list) to make ground as well')
ap.add_argument('--feed-at', nargs=2, type=float, metavar=('X', 'Y'), help='place feed pad 1 here, footprint mm')
a = ap.parse_args()

class Q(str): pass                               # a quoted string, written back with its quotes

def parse(s):
    st = [[]]
    for t in re.findall(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()"]+', s):
        if t == '(': st.append([])
        elif t == ')': x = st.pop(); st[-1].append(x)
        else: st[-1].append(Q(t[1:-1]) if t[0] == '"' else t)
    return st[0][0]

dump = lambda n: '(' + ' '.join(map(dump, n)) + ')' if isinstance(n, list) else (f'"{n}"' if isinstance(n, Q) else n)
kids = lambda n, k: [c for c in n[1:] if isinstance(c, list) and c and c[0] == k]
one = lambda n, k: (kids(n, k) or [None])[0]
f2 = lambda v: f'{v:.4f}'.rstrip('0').rstrip('.')

def inside(p, r):
    x, y = p; c = False
    for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1): c = not c
    return c

area = lambda r: abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]))) / 2

def nearest(p, r):                               # closest point of ring r's boundary to p, and its distance
    best = None
    for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
        dx, dy = x2 - x1, y2 - y1; L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0, min(1, ((p[0] - x1) * dx + (p[1] - y1) * dy) / L2))
        q = (x1 + t * dx, y1 + t * dy); d = math.hypot(q[0] - p[0], q[1] - p[1])
        if best is None or d < best[1]: best = (q, d)
    return best

fp = parse(open(a.mod, encoding='utf8').read())
assert fp[0] in ('footprint', 'module'), f'{a.mod} is not a footprint'
pts = lambda g: [(float(p[1]), float(p[2])) for p in kids(one(g, 'pts'), 'xy')]
# shortcut: only fp_poly copper is read as ground (arcs in pts are skipped); fp_rect / fp_circle planes stay antenna
cu = [g for g in kids(fp, 'fp_poly') if str(one(g, 'layer')[1]).endswith('.Cu')]
pads = kids(fp, 'pad')
at = lambda g: (float(one(g, 'at')[1]), float(one(g, 'at')[2]))
p2 = [at(p) for p in pads if p[1] == '2']
feeds = [p for p in pads if p[1] == '1']
assert len(feeds) == 1, f'need exactly one pad "1" as the feed (found {len(feeds)})'
feed = feeds[0]

if a.list:
    for i, g in enumerate(cu):
        r = pts(g); xs, ys = [p[0] for p in r], [p[1] for p in r]
        print(f'{i:3} {one(g, "layer")[1]:7} {area(r):9.1f} mm2  x {min(xs):.2f}..{max(xs):.2f}  y {min(ys):.2f}..{max(ys):.2f}'
              f'  pad2 {sum(inside(p, r) for p in p2)}')
    sys.exit()
held = [g for g in cu if any(inside(p, pts(g)) for p in p2)]
if held:
    big = max(area(pts(g)) for g in held)
    gnd = [g for g in held if area(pts(g)) >= 0.2 * big]
else:
    gnd = [max(cu, key=lambda g: area(pts(g)))]
    print(f'no pad "2": the largest copper polygon ({one(gnd[0], "layer")[1]}, {area(pts(gnd[0])):.0f} mm2) is the ground')
gnd += [cu[int(i)] for i in a.ground.split(',') if i and not any(cu[int(i)] is g for g in gnd)]
fp[:] = [c for c in fp if not any(c is g for g in gnd)]

# feed pad straddling the ground edge: move it onto the end of the nearest antenna copper on its layer
fl = next(str(L) for L in one(feed, 'layers')[1:] if str(L).endswith('.Cu'))
(fx, fy), size = at(feed), one(feed, 'size'); sx, sy = float(size[1]), float(size[2])
box = [(fx - sx / 2, fy - sy / 2), (fx + sx / 2, fy - sy / 2), (fx + sx / 2, fy + sy / 2), (fx - sx / 2, fy + sy / 2)]
hit = lambda r: any(inside(p, r) for p in box + [(fx, fy)]) or any(inside(p, box) for p in r)
if a.feed_at:
    one(feed, 'at')[1:3] = [f2(v) for v in a.feed_at]
elif fl != '*.Cu' and any(hit(pts(g)) for g in gnd if one(g, 'layer')[1] == fl):
    ant = [nearest((fx, fy), pts(g)) for g in cu if one(g, 'layer')[1] == fl and not any(g is h for h in gnd)]
    assert ant, f'feed pad 1 overlaps the ground on {fl} and there is no antenna copper on {fl} to move it to'
    (qx, qy), d = min(ant, key=lambda t: t[1])
    if d > 1e-6:
        ux, uy = (qx - fx) / d, (qy - fy) / d
        h = abs(ux) * sx / 2 + abs(uy) * sy / 2
        one(feed, 'at')[1:3] = [f2(qx + ux * h), f2(qy + uy * h)]
        print(f'feed pad 1 overlapped the ground on {fl}: moved from ({f2(fx)}, {f2(fy)}) to ({one(feed, "at")[1]}, {one(feed, "at")[2]})'
              + ('' if min(abs(ux), abs(uy)) < 1e-6 else ' (not straight across: check the port in the dry run)'))

for p in pads:
    if p[1] in ('1', '2'): p.append(['net', '2', Q('RF')] if p[1] == '1' else ['net', '1', Q('GND')])
for t in kids(fp, 'fp_text') + kids(fp, 'property'):
    if t[1] == 'reference' or t[1] == 'Reference': t[2] = Q('ANT1')
fp.insert(2, ['at', '100', '100'])

# outline: F.Fab drawing and all copper
xy = [p for g in cu for p in pts(g)] + [p for g in kids(fp, 'fp_poly') + kids(fp, 'fp_line') if one(g, 'layer')[1] == 'F.Fab'
                                      for p in (pts(g) if g[0] == 'fp_poly' else [(float(one(g, k)[1]), float(one(g, k)[2])) for k in ('start', 'end')])]
x0, y0 = min(p[0] for p in xy) + 100, min(p[1] for p in xy) + 100
x1, y1 = max(p[0] for p in xy) + 100, max(p[1] for p in xy) + 100

inner = sorted({int(m) for g in cu for m in re.findall(r'In(\d+)\.Cu', str(one(g, 'layer')[1]))})
assert not inner or max(inner) <= 2, 'footprints with more than 2 inner layers are not handled'
CU = 0.035
diel = lambda n, kind, t: f' (layer "dielectric {n}" (type "{kind}") (thickness {f2(t)}) (material "FR4") (epsilon_r {a.er}) (loss_tangent {a.tand}))\n'
cul = lambda L: f' (layer "{L}" (type "copper") (thickness {CU}))\n'
if inner:
    core = a.thickness - 2 * a.prepreg - 4 * CU
    assert core > 0, f'--prepreg {a.prepreg} leaves no core in a {a.thickness} mm board'
    layers = '(0 "F.Cu" signal) (4 "In1.Cu" signal) (6 "In2.Cu" signal) (2 "B.Cu" signal)'
    stack = cul('F.Cu') + diel(1, 'prepreg', a.prepreg) + cul('In1.Cu') + diel(2, 'core', core) + cul('In2.Cu') + diel(3, 'prepreg', a.prepreg) + cul('B.Cu')
else:
    layers = '(0 "F.Cu" signal) (2 "B.Cu" signal)'
    stack = cul('F.Cu') + diel(1, 'core', a.thickness - 2 * CU) + cul('B.Cu')

def zone(g):
    L = one(g, 'layer')[1]
    p = '(pts ' + ' '.join(f'(xy {f2(x + 100)} {f2(y + 100)})' for x, y in pts(g)) + ')'
    return f'(gr_poly {p} (stroke (width 0) (type solid)) (fill yes) (layer "{L}") (net 1))\n'

name = re.sub(r'[^a-z0-9]+', '_', os.path.splitext(os.path.basename(a.mod))[0].lower()).strip('_')
out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.mod)), name, name + '.kicad_pcb')
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
with open(out, 'w', encoding='utf8', newline='\n') as f:
    f.write(f'(kicad_pcb (version 20240108) (generator "pcbnew")\n(general (thickness {a.thickness}))\n'
            f'(layers {layers} (25 "Edge.Cuts" user) (37 "F.SilkS" user) (49 "F.Fab" user))\n'
            f'(setup (stackup\n{stack}))\n(net 0 "") (net 1 "GND") (net 2 "RF")\n'
            + '(' + '\n  '.join(dump(c) for c in fp) + ')\n'
            + f'(gr_rect (start {f2(x0)} {f2(y0)}) (end {f2(x1)} {f2(y1)}) (stroke (width 0.1)) (layer "Edge.Cuts"))\n'
            + ''.join(zone(g) for g in gnd) + ')\n')
print(f'{out}: {len(gnd)} GND shape(s) on {", ".join(sorted({str(one(g, "layer")[1]) for g in gnd}))}, '
      f'{len(inner) and 4 or 2} layers, {a.thickness} mm, outline {f2(x1 - x0)} x {f2(y1 - y0)} mm')
