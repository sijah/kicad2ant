"""Pull a PCB antenna and its ground out of a KiCad 6+ board into <out>.m for antenna_sim.m.

usage: python extract_antenna.py BOARD.kicad_pcb REF [out.m] [--feed PAD] [--gnd NET]

Reads, from the board as saved:
  - antenna = every copper item of footprint REF on any copper layer: fp_poly/line/arc/rect/circle (with
    stroke width), pads of any shape/angle/offset (custom pads with their primitives), footprint zones;
    plated through-hole pads become PEC barrels between their layers;
  - ground = the filled zones and the tracks of the GND net on every copper layer, and the GND-net vias (PEC lines);
  - stackup = copper layer heights and one dielectric per copper pair (sublayers thickness-weighted);
  - outline = the closed Edge.Cuts loops: the largest is the board, the others are cutouts;
  - port = feed pad (--feed, default "1") straight down/up to the nearest GND copper under it, else
    in-plane to the nearest GND copper on its own layer.
Other nets' copper and the parts are not modelled.  Sim frame (mm): origin = footprint origin,
x = board x, y up (KiCad y flipped), z = 0 at the bottom copper layer."""
import argparse, math, os, re, sys

ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
ap.add_argument('board'); ap.add_argument('ref', help="the antenna footprint's reference, or auto"); ap.add_argument('out', nargs='?', default='antenna_geom.m')
ap.add_argument('--feed', default='1', help='feed pad number (default 1)')
ap.add_argument('--gnd', help='ground net (default: net of pad 2 of REF, else GND, else the largest zone net with a ground name)')
a = ap.parse_args()
warn = lambda m: print('warning: ' + m, file=sys.stderr)


def parse(s):
    """s-expression -> nested lists of strings (quotes removed)"""
    out = [[]]
    for m in re.finditer(r'\(|\)|"((?:[^"\\]|\\.)*)"|[^\s()"]+', s):
        t = m.group()
        if t == '(': out.append([])
        elif t == ')': x = out.pop(); out[-1].append(x)
        else: out[-1].append(m.group(1).replace('\\"', '"') if m.group(1) is not None else t)
    return out[0][0]

kids = lambda n, k: [c for c in n[1:] if isinstance(c, list) and c and c[0] == k] if n else []
one = lambda n, k: next(iter(kids(n, k)), None)
def num(n, k, i=1, d=None):
    c = one(n, k)
    return float(c[i]) if c is not None and len(c) > i else d
xy = lambda n, k: (float(one(n, k)[1]), float(one(n, k)[2]))

pcb = parse(open(a.board, encoding='utf8').read())
assert pcb[0] == 'kicad_pcb', f'{a.board} is not a .kicad_pcb'
assert (num(pcb, 'version') or 0) >= 20211014, 'KiCad 6 or newer board file needed (open and save it in KiCad)'
nets = {c[1]: c[2] for c in kids(pcb, 'net') if len(c) > 2}
def netname(n):
    c = one(n, 'net_name') or one(n, 'net')
    if c is None: return None
    return c[1] if c[0] == 'net_name' else c[2] if len(c) > 2 else nets.get(c[1], c[1])

# ---- stackup: copper z and one dielectric box per copper pair ------------------------------------
order = lambda L: -1 if L == 'F.Cu' else 10**6 if L == 'B.Cu' else int(re.sub(r'\D', '', L) or 0)
cu_names = sorted((c[1] for c in (one(pcb, 'layers') or [])[1:] if isinstance(c, list) and c[1].endswith('.Cu')), key=order)
st = one(one(pcb, 'setup'), 'stackup')
layers = []                                   # top -> bottom: ['cu', name, t] / ['d', [sublayer dicts]]
for L in kids(st, 'layer'):
    if L[1].endswith('.Cu'): layers.append(['cu', L[1], num(L, 'thickness', d=0.035)])
    elif L[1].startswith('dielectric') and 'mask' not in (one(L, 'type') or [0, ''])[1].lower():
        subs = [{}]
        for c in L[2:]:
            if c == 'addsublayer': subs.append({})
            elif isinstance(c, list) and c[0] in ('thickness', 'epsilon_r', 'loss_tangent'): subs[-1].setdefault(c[0], float(c[1]))
        layers.append(['d', subs])
if not layers:
    assert len(cu_names) == 2, f'{len(cu_names)}-layer board without a stackup: set it in Board Setup > Physical Stackup, then save'
    h = num(one(pcb, 'general'), 'thickness', d=1.6)
    warn(f'no stackup in the board: 2 layers, {h} mm board, epsR 4.5, tan d 0.02 assumed')
    layers = [['cu', 'F.Cu', 0.035], ['d', [{'thickness': h - 0.07}]], ['cu', 'B.Cu', 0.035]]
cu_z, diel, z, pend, prev = {}, [], 0.0, [], None
for L in layers[::-1]:                        # bottom up; copper is a sheet at its mid-plane
    if L[0] == 'd': pend += L[1]; continue
    if prev:
        for s in pend: assert 'thickness' in s, 'a stackup dielectric has no thickness'
        tt = sum(s['thickness'] for s in pend)
        for k, d in (('epsilon_r', 4.5), ('loss_tangent', 0.02)):
            if any(k not in s for s in pend): warn(f'stackup dielectric under {L[1]} has no {k}: {d} used')
        mean = lambda k, d: sum(s['thickness'] * s.get(k, d) for s in pend) / tt
        dz = tt + prev[2] / 2 + L[2] / 2
        diel.append((z, z + dz, mean('epsilon_r', 4.5), mean('loss_tangent', 0.02))); z += dz
    cu_z[L[1]], prev, pend = round(z, 5), L, []

# ---- footprint and frames ------------------------------------------------------------------------
def refof(fp):
    for p in kids(fp, 'property'):
        if p[1] == 'Reference': return p[2]
    for t in kids(fp, 'fp_text'):
        if t[1] == 'reference': return t[2]
if a.ref == 'auto':   # the one footprint that looks like an antenna: reference AE* / ANT*, or an RF_Antenna library part (same rule as the plugin's core.is_antenna_ref)
    cand = sorted({refof(f) for f in kids(pcb, 'footprint') if re.match(r'(AE|ANT)', refof(f) or '', re.I)
                   or 'antenna' in str(f[1]).lower()} - {None})
    assert len(cand) == 1, f'cannot pick the antenna footprint ({cand or "no AE*/ANT* reference"}): give its reference'
    a.ref = cand[0]; print(f'antenna footprint: {a.ref}')
fps = [f for f in kids(pcb, 'footprint') if refof(f) == a.ref]
assert len(fps) == 1, f'{a.ref}: {len(fps)} footprints with that reference'
fp = fps[0]
at = one(fp, 'at'); X0, Y0 = float(at[1]), float(at[2])

def rot(x, y, ang):
    """KiCad rotation (degrees, y down)"""
    r = math.radians(ang); return x * math.cos(r) + y * math.sin(r), -x * math.sin(r) + y * math.cos(r)
bd = lambda x, y: (x - X0, -(y - Y0))        # board -> sim
def frame(f):
    """footprint-local -> sim"""
    t = one(f, 'at'); X, Y, ang = float(t[1]), float(t[2]), float(t[3]) if len(t) > 3 else 0.0
    return lambda x, y: (lambda r: bd(X + r[0], Y + r[1]))(rot(x, y, ang))

# ---- geometry helpers (all in the sim frame) -----------------------------------------------------
def arc(p, m, q):
    """3-point arc -> polyline, about 10 deg per segment"""
    (ax, ay), (mx, my), (bx, by) = p, m, q
    d = 2 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my))
    if abs(d) < 1e-12: return [p, q]
    ux = ((ax*ax + ay*ay) * (my - by) + (mx*mx + my*my) * (by - ay) + (bx*bx + by*by) * (ay - my)) / d
    uy = ((ax*ax + ay*ay) * (bx - mx) + (mx*mx + my*my) * (ax - bx) + (bx*bx + by*by) * (mx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    t0, tm, t1 = (math.atan2(y - uy, x - ux) for x, y in (p, m, q))
    sw = (t1 - t0) % (2 * math.pi)
    if (tm - t0) % (2 * math.pi) > sw: sw -= 2 * math.pi
    n = max(2, int(abs(sw) / math.radians(10)) + 1)
    return [p] + [(ux + r * math.cos(t0 + sw * i / n), uy + r * math.sin(t0 + sw * i / n)) for i in range(1, n)] + [q]

def stadium(cx, cy, sx, sy, T, n=12):
    """oval/circle of size sx x sy centred (cx, cy) in a local frame, mapped by T"""
    r = min(sx, sy) / 2; hx, hy = (sx / 2 - r, 0) if sx >= sy else (0, sy / 2 - r)
    b = -90 if sx >= sy else 0
    return [T(cx + s * hx + r * math.cos(math.radians(b + 180 * (k + i / n))), cy + s * hy + r * math.sin(math.radians(b + 180 * (k + i / n))))
            for k, s in ((0, 1), (1, -1)) for i in range(n + 1)]

def seg(p, q, w):
    """track of width w -> rectangle; shortcut: square caps of w/2 instead of round ones"""
    dx, dy = q[0] - p[0], q[1] - p[1]; L = math.hypot(dx, dy)
    if not w: return None
    if L == 0: return stadium(p[0], p[1], w, w, lambda x, y: (x, y), 6)
    ux, uy = dx / L * w / 2, dy / L * w / 2
    return [(p[0] - ux - uy, p[1] - uy + ux), (q[0] + ux - uy, q[1] + uy + ux), (q[0] + ux + uy, q[1] + uy - ux), (p[0] - ux + uy, p[1] - uy - ux)]
def inside(p, ring):
    c = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > p[1]) != (y2 > p[1]) and p[0] < x1 + (p[1] - y1) * (x2 - x1) / (y2 - y1): c = not c
    return c
area = lambda r: abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]))) / 2
thick = lambda pl, w: [s for p, q in zip(pl, pl[1:]) for s in [seg(p, q, w)] if s]

def path(pts, T):
    """(pts (xy ..) (arc (start ..) (mid ..) (end ..)) ..) -> polyline"""
    out = []
    for c in pts[1:]:
        if c[0] == 'xy': out.append(T(float(c[1]), float(c[2])))
        elif c[0] == 'arc': out += arc(T(*xy(c, 'start')), T(*xy(c, 'mid')), T(*xy(c, 'end')))
    return out

def shapes(g, T):
    """copper polygons of one fp_*/gr_* item (footprint graphic or pad primitive)"""
    kind = g[0].split('_', 1)[1]
    w = num(one(g, 'stroke'), 'width') or num(g, 'width') or 0
    f = one(g, 'fill'); filled = f is not None and f[1] in ('solid', 'yes')
    if kind == 'line': return thick([T(*xy(g, 'start')), T(*xy(g, 'end'))], w)
    if kind == 'arc': return thick(arc(T(*xy(g, 'start')), T(*xy(g, 'mid')), T(*xy(g, 'end'))), w)
    if kind == 'poly': ring = path(one(g, 'pts'), T); filled = filled or f is None   # KiCad 6/7 copper polys: filled
    elif kind == 'rect': (x0, y0), (x1, y1) = xy(g, 'start'), xy(g, 'end'); ring = [T(x0, y0), T(x1, y0), T(x1, y1), T(x0, y1)]
    elif kind == 'circle':
        (cx, cy), (ex, ey) = xy(g, 'center'), xy(g, 'end'); d = 2 * math.hypot(ex - cx, ey - cy)
        ring = stadium(cx, cy, d, d, T, 24)
    else: warn(f'{g[0]} on copper is not modelled'); return []
    return ([ring] if filled else []) + thick(ring + ring[:1], w)

def cu_of(item):
    """copper layers of a pad/item, expanded (*.Cu, F&B.Cu)"""
    Ls = (one(item, 'layers') or one(item, 'layer') or [None])[1:]
    out = []
    for L in Ls:
        out += list(cu_z) if L == '*.Cu' else ['F.Cu', 'B.Cu'] if L == 'F&B.Cu' else [L] if L in cu_z else []
    return out

# ---- antenna copper ------------------------------------------------------------------------------
T = frame(fp)
ant, lines, pads = [], [], []                  # ant: (layer, ring); lines: (x, y, z0, z1)
for g in fp[1:]:
    if isinstance(g, list) and g[0] in ('fp_poly', 'fp_line', 'fp_arc', 'fp_rect', 'fp_circle', 'fp_curve'):
        L = one(g, 'layer')[1]
        if L in cu_z: ant += [(L, r) for r in shapes(g, T)]
for zn in kids(fp, 'zone'):
    for f in kids(zn, 'filled_polygon'):
        if one(f, 'layer')[1] in cu_z: ant.append((one(f, 'layer')[1], path(one(f, 'pts'), bd)))
for p in kids(fp, 'pad'):
    kind, shape = p[2], p[3]
    t = one(p, 'at'); lx, ly = float(t[1]), float(t[2]); pa = float(t[3]) if len(t) > 3 else 0.0
    sx, sy = num(p, 'size'), num(p, 'size', 2)
    dr = one(p, 'drill'); off = one(dr, 'offset')
    ox, oy = (float(off[1]), float(off[2])) if off else (0.0, 0.0)
    cxy = rot(lx, ly, float(at[3]) if len(at) > 3 else 0.0)
    PT = lambda x, y, c=cxy, pa=pa: (lambda r: bd(X0 + c[0] + r[0], Y0 + c[1] + r[1]))(rot(x, y, pa))   # pad local -> sim
    anchor = (one(one(p, 'options'), 'anchor') or [0, 'rect'])[1] if shape == 'custom' else shape
    if anchor in ('circle', 'oval'): rings = [stadium(ox, oy, sx, sy, PT)]
    else: rings = [[PT(ox - sx/2, oy - sy/2), PT(ox + sx/2, oy - sy/2), PT(ox + sx/2, oy + sy/2), PT(ox - sx/2, oy + sy/2)]]  # rect/roundrect/trapezoid
    for g in (one(p, 'primitives') or [])[1:]:
        if isinstance(g, list) and g[0].startswith('gr_'): rings += shapes(g, PT)
    Ls = cu_of(p) if kind != 'np_thru_hole' else []
    ant += [(L, r) for L in Ls for r in rings]
    if kind == 'thru_hole' and len(Ls) > 1:
        x, y = PT(0, 0); zs = [cu_z[L] for L in Ls]; lines.append((x, y, min(zs), max(zs)))
    pads.append(dict(n=p[1], net=netname(p), layers=Ls, ring=rings[0], c=PT(0, 0)))
def simple(ring):
    """split a ring at repeated vertices (KiCad keyholes around drills, zero-width spikes) into simple loops;
    keep the copper loops, drop zero-area spikes and opposite-winding holes, which AddPolygon cannot fill"""
    sarea = lambda r: sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1])) / 2
    key = lambda p: (round(p[0], 6), round(p[1], 6))
    loops, st, seen = [], [], {}
    for p in ring + ring[:1]:
        k = key(p)
        if k in seen:
            i = seen[k]; loops.append(st[i:])
            for q in st[i + 1:]: seen.pop(key(q))
            del st[i + 1:]
        else: seen[k] = len(st); st.append(p)
    loops = [(sarea(r), r) for r in loops if len(r) > 2 and abs(sarea(r)) > 1e-9]
    if len(loops) < 2: return [r for _, r in loops] or [ring]
    big = max(loops, key=lambda s: abs(s[0]))[0]
    return [r for s, r in loops if s * big > 0]   # shortcut: holes are filled (drill-sized in footprints), model them if a slotted antenna needs it
ant = [(L, s) for L, r in ant for s in simple(r)]
assert ant, f'{a.ref} has no copper on any copper layer'

feeds = [q for q in pads if q['n'] == a.feed]
assert len(feeds) == 1, f'{a.ref} needs exactly one pad "{a.feed}" as the feed (found {len(feeds)}); pick another with --feed'
feed = feeds[0]; assert feed['layers'], f'feed pad {a.feed} has no copper'

# ---- ground: filled zones, tracks and vias of the GND net ------------------------------------------
zfill, zempty = {}, {}                         # zone net -> [(layer, ring)], zones without a fill
for zn in kids(pcb, 'zone'):
    n = netname(zn)
    if not n: continue
    fp_ = kids(zn, 'filled_polygon'); zempty[n] = zempty.get(n, 0) + (not fp_)
    zfill.setdefault(n, []).extend((one(f, 'layer')[1], path(one(f, 'pts'), bd)) for f in fp_ if one(f, 'layer')[1] in cu_z)
for g in pcb[1:]:                              # board copper shapes on a net: a ground drawn as a shape (no refill changes it)
    if isinstance(g, list) and g[0].startswith('gr_') and (one(g, 'layer') or [0, ''])[1] in cu_z and netname(g):
        zfill.setdefault(netname(g), []).extend((one(g, 'layer')[1], r) for r in shapes(g, bd))
zarea = {n: sum(area(r) for _, r in v) for n, v in zfill.items()}
leaf = lambda n: n.rsplit('/', 1)[-1]          # a net's name without its sheet path
if a.gnd:   # as typed: the exact net, else its name after the sheet path (/rf/GND for GND), else ignoring case
    hits = next((h for h in ([n for n in zarea if same(n)] for same in (
        lambda n: n == a.gnd, lambda n: leaf(n) == a.gnd, lambda n: leaf(n).lower() == a.gnd.lower())) if h), [a.gnd])
    gnd = max(hits, key=lambda n: zarea.get(n, 0))
else:
    gnd = next((q['net'] for q in pads if q['n'] == '2' and q['n'] != a.feed and q['net'] in zarea), None) or ('GND' if 'GND' in zarea else None)
    if not gnd:   # no pad 2 and no net called GND: the largest zone net with a usual ground name
        named = [n for n in zarea if re.match(r'((A|D|P|RF)?GND\w*|VSS\w*|0V)$', leaf(n), re.I)]
        gnd = max(named, key=zarea.get, default=None)
        if gnd: print(f'ground net: {gnd} (the largest zone net with a ground name; give --gnd for another)')
assert zarea or a.gnd, 'the board has no copper zones: the antenna needs a ground. Draw a zone on the ground net, press B, save'
assert gnd, f'cannot tell the ground net (nets with zones: {", ".join(sorted(zarea))}): give it with --gnd NET, in the plugin as Ground net'
fills, unfilled = list(zfill.get(gnd, [])), zempty.get(gnd, 0)
assert fills, f'no filled {gnd} zones on the board' + (' (they exist but are not filled: press B in KiCad, then save)' if unfilled else '')
if unfilled: warn(f'{unfilled} {gnd} zones have no fill (press B in KiCad and save if that is not intended)')
for s in kids(pcb, 'segment') + kids(pcb, 'arc'):   # GND tracks: an IFA's short can reach the ground through one
    L = one(s, 'layer')[1]
    if netname(s) != gnd or L not in cu_z: continue
    pl = [bd(*xy(s, k)) for k in ('start', 'end')] if s[0] == 'segment' else arc(*(bd(*xy(s, k)) for k in ('start', 'mid', 'end')))
    fills += [(L, r) for r in thick(pl, num(s, 'width'))]
for v in kids(pcb, 'via'):
    if netname(v) == gnd:
        zs = [cu_z[L] for L in cu_of(v)]
        if len(zs) > 1: lines.append(bd(*xy(v, 'at')) + (min(zs), max(zs)))

# ---- port ------------------------------------------------------------------------------------------
fl = one(fp, 'layer')[1]                        # a through-hole feed pad: the port on the footprint's own side
if fl not in feed['layers']: fl = feed['layers'][0]
zf = cu_z[fl]; (fx, fy) = feed['c']
bx0, by0 = min(p[0] for p in feed['ring']), min(p[1] for p in feed['ring'])
bx1, by1 = max(p[0] for p in feed['ring']), max(p[1] for p in feed['ring'])
under = [L for L in sorted(cu_z, key=lambda L: abs(cu_z[L] - zf)) if L != fl and any(inside((fx, fy), r) for l, r in fills if l == L)]
if under:
    zg = cu_z[under[0]]
    port, pdir, pkind = (bx0, by0, min(zf, zg), bx1, by1, max(zf, zg)), (0, 0, 1), f'vertical {fl} -> {under[0]}'
else:
    best = None                                # nearest GND copper on the feed layer
    for l, r in fills:
        if l != fl: continue
        for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
            dx, dy = x2 - x1, y2 - y1; L2 = dx * dx + dy * dy
            t = 0 if L2 == 0 else max(0, min(1, ((fx - x1) * dx + (fy - y1) * dy) / L2))
            q = (x1 + t * dx, y1 + t * dy); d = math.hypot(q[0] - fx, q[1] - fy)
            across = abs(q[0] - fx) >= abs(q[1] - fy)          # straight across from the pad beats nearer but diagonal
            key = (not (by0 - 1e-3 <= q[1] <= by1 + 1e-3 if across else bx0 - 1e-3 <= q[0] <= bx1 + 1e-3), d)
            if best is None or key < best[0]: best = (key, q)
    assert best, f'no {gnd} copper under the feed pad on any layer, nor on its own layer {fl}: nothing to feed against'
    qx, qy = best[1]
    if abs(qx - fx) >= abs(qy - fy):
        e = bx1 if qx > fx else bx0; port, pdir = (min(e, qx), by0, zf, max(e, qx), by1, zf), (1, 0, 0)
    else:
        e = by1 if qy > fy else by0; port, pdir = (bx0, min(e, qy), zf, bx1, max(e, qy), zf), (0, 1, 0)
    assert not best[0][0], (f'the nearest {gnd} copper to feed pad {a.feed} is diagonal from it, at ({qx:.2f}, {qy:.2f}): a straight port '
                    f'would end beside it. Bring {gnd} copper straight across from the pad (or under it), or pick another feed pad')
    assert max(port[3] - port[0], port[4] - port[1]) > 1e-3 or pdir == (0, 0, 1), 'feed pad touches GND copper on its own layer'
    pkind = f'in-plane on {fl} to the {gnd} copper at ({qx:.2f}, {qy:.2f})'

# ---- outline -------------------------------------------------------------------------------------
segs, loops = [], []
edges = [(g, bd) for g in pcb[1:] if isinstance(g, list) and g[0].startswith('gr_')]
for f in kids(pcb, 'footprint'):
    Tf = frame(f); edges += [(g, Tf) for g in f[1:] if isinstance(g, list) and g[0].startswith('fp_')]
for g, Tg in edges:
    if (one(g, 'layer') or [0, 0])[1] != 'Edge.Cuts': continue
    k = g[0].split('_', 1)[1]
    if k == 'line': segs.append([Tg(*xy(g, 'start')), Tg(*xy(g, 'end'))])
    elif k == 'arc': segs.append(arc(Tg(*xy(g, 'start')), Tg(*xy(g, 'mid')), Tg(*xy(g, 'end'))))
    elif k == 'curve': segs.append(path(one(g, 'pts'), Tg))     # shortcut: bezier as its control polygon
    elif k == 'rect': (x0, y0), (x1, y1) = xy(g, 'start'), xy(g, 'end'); loops.append([Tg(x0, y0), Tg(x1, y0), Tg(x1, y1), Tg(x0, y1)])
    elif k == 'circle':
        (cx, cy), (ex, ey) = xy(g, 'center'), xy(g, 'end'); d = 2 * math.hypot(ex - cx, ey - cy)
        loops.append(stadium(cx, cy, d, d, Tg, 24))
    elif k == 'poly': loops.append(path(one(g, 'pts'), Tg))
near = lambda p, q: abs(p[0] - q[0]) < 1e-2 and abs(p[1] - q[1]) < 1e-2   # 0.01 mm: what KiCad itself still joins
while segs:
    ch = segs.pop()
    while not near(ch[0], ch[-1]):
        i = next((i for i, s in enumerate(segs) if near(s[0], ch[-1]) or near(s[-1], ch[-1])), None)
        assert i is not None, f'Edge.Cuts outline is not closed near sim ({ch[-1][0]:.2f}, {ch[-1][1]:.2f})'
        s = segs.pop(i); ch += s[1:] if near(s[0], ch[-1]) else s[-2::-1]
    if len(ch) > 3: loops.append(ch[:-1])        # a stray piece shorter than the tolerance is not a cutout
assert loops, 'no Edge.Cuts outline on the board'
loops.sort(key=area, reverse=True); outline, holes = loops[0], loops[1:]

# ---- mesh hints near the antenna -------------------------------------------------------------------
allp = [p for _, r in ant for p in r]
box = (min(p[0] for p in allp), min(p[1] for p in allp), max(p[0] for p in allp), max(p[1] for p in allp))
inbox = lambda p, m=3: box[0] - m <= p[0] <= box[2] + m and box[1] - m <= p[1] <= box[3] + m
hint = allp + [p for _, r in fills for p in r if inbox(p)] + [(port[0], port[1]), (port[3], port[4])] + [l[:2] for l in lines if inbox(l)]
# straight antenna edges for the thirds rule: coordinate -> side of the metal (+1 above, -1 below)
edge = ({}, {})
for L, r in ant:
    for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
        for ax, (a1, a2, b1, b2) in enumerate(((x1, x2, y1, y2), (y1, y2, x1, x2))):
            if abs(a1 - a2) > 1e-4 or abs(b1 - b2) < 1e-3: continue
            m = (b1 + b2) / 2
            pt = lambda d: (a1 + d, m) if ax == 0 else (m, a1 + d)
            hi, lo = (any(inside(pt(d), q) for l, q in ant if l == L) for d in (1e-3, -1e-3))
            if hi != lo: edge[ax][round(a1, 4)] = 1 if hi else -1
# straight ground edges within 1 mm of the port on the feed pad's layer: fast mode puts mesh lines on them, else
# its edge-exact mesh merges the pad-to-ground clearance away and shorts the port (shortcut: a clearance under
# cell_ant/3, ~0.17 mm, can still merge)
win = ((port[0] - 1, port[3] + 1), (port[1] - 1, port[4] + 1))   # x and y range around the port
pgnd = (set(), set())
for L, r in fills:
    if L != fl: continue
    for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
        for ax, (a1, a2, b1, b2) in enumerate(((x1, x2, y1, y2), (y1, y2, x1, x2))):
            wa, wb = win[ax], win[1 - ax]           # an edge that crosses the window counts, however long it is
            if (abs(a1 - a2) < 1e-4 and abs(b1 - b2) >= 0.05 and wa[0] <= a1 <= wa[1]
                    and min(b1, b2) <= wb[1] and max(b1, b2) >= wb[0]): pgnd[ax].add(round(a1, 4))
mx =sorted({round(p[0], 3) for p in hint}); my = sorted({round(p[1], 3) for p in hint})

# ---- write ---------------------------------------------------------------------------------------
M = lambda P: '[' + '; '.join(f'{x:.4f} {y:.4f}' for x, y in P) + ']'
V = lambda v: '[' + ' '.join(f'{x:.4f}' for x in v) + ']'
q = lambda s: "'" + str(s).replace("'", "''") + "'"
with open(a.out, 'w', encoding='utf8', newline='\n') as o:
    o.write(f'% generated by extract_antenna.py from {os.path.basename(a.board)} -- do not edit\n')
    o.write(f'% {a.ref} at board ({X0}, {Y0}); sim origin = footprint origin, y up, z 0 = bottom copper\n')
    o.write(f'geom.ref = {q(a.ref)}; geom.gnd_net = {q(gnd)}; geom.port_kind = {q(pkind)};\n')
    o.write(f'geom.cu_name = {{{", ".join(q(L) for L in sorted(cu_z, key=order))}}}; geom.cu_z = {V(cu_z[L] for L in sorted(cu_z, key=order))};\n')
    o.write('geom.diel = [' + '; '.join(f'{z0:.5f} {z1:.5f} {e:.4f} {t:.5f}' for z0, z1, e, t in diel) + '];  % z0 z1 epsR tand\n')
    o.write(f'geom.outline = {M(outline)};\ngeom.holes = {{{", ".join(M(h) for h in holes)}}};\n')
    o.write('geom.ant = {};\n' + ''.join(f"geom.ant{{end+1}} = struct('layer', {q(L)}, 'z', {cu_z[L]}, 'pts', {M(r)});\n" for L, r in ant))
    o.write('geom.gnd = {};\n' + ''.join(f"geom.gnd{{end+1}} = struct('layer', {q(L)}, 'z', {cu_z[L]}, 'pts', {M(r)});\n" for L, r in fills))
    o.write('geom.lines = [' + '; '.join(f'{x:.4f} {y:.4f} {z0:.5f} {z1:.5f}' for x, y, z0, z1 in lines) + '];  % PEC x y z0 z1\n')
    o.write(f'geom.port = {V(port)}; geom.port_dir = {V(pdir)};\n')
    o.write(f'geom.ant_box = {V(box)};\ngeom.mesh_x = {V(mx)};\ngeom.mesh_y = {V(my)};\n')
    for ax, k in enumerate('xy'):
        rows = '; '.join(f'{c:.4f} {sd}' for c, sd in sorted(edge[ax].items()))
        o.write(f'geom.edge_{k} = ' + (f'[{rows}]' if rows else 'zeros(0, 2)') + ';  % straight antenna edges: coordinate, metal side\n')
        o.write(f'geom.port_gnd_{k} = {V(sorted(pgnd[ax]))};  % straight ground edges near the port (fast mode mesh lines)\n')
print(f'{a.ref}: {len(ant)} antenna polygons, {len(fills)} {gnd} fills on {sorted({l for l, _ in fills}, key=order)}, '
      f'{len(lines)} PEC lines, {len(cu_z)} copper layers h {max(cu_z.values()):.3f} mm, {len(holes)} cutouts, port {pkind} -> {a.out}')
