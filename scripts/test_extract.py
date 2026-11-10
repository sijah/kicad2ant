"""Self-check for extract_antenna.py: python test_extract.py  (prints OK or fails an assert).
Builds small boards and checks the extracted stackup, outline, antenna copper, ground, PEC lines and port.
Also runs KiCad's own RF_Antenna footprints when a KiCad install is found."""
import glob, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STACKUP = '''
\t(setup
\t\t(stackup
\t\t\t(layer "F.Mask" (type "Top Solder Mask") (thickness 0.01))
\t\t\t(layer "F.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "dielectric 1" (type "prepreg") (thickness 0.2) (material "R-1551(W)") (epsilon_r 4.3) (loss_tangent 0.02))
\t\t\t(layer "In1.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "dielectric 2" (type "core") (thickness 0.8 locked) (material "FR4") (epsilon_r 4.6) (loss_tangent 0.02) addsublayer (thickness 0.1) (epsilon_r 4.0) (loss_tangent 0.01))
\t\t\t(layer "In2.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "dielectric 3" (type "prepreg") (thickness 0.2) (epsilon_r 4.3) (loss_tangent 0))
\t\t\t(layer "B.Cu" (type "copper") (thickness 0.035))
\t\t)
\t)'''

def zone(layer, y1, filled=True):
    fill = f'\n\t\t(filled_polygon (layer "{layer}") (pts (xy 80 20) (xy 130 20) (xy 130 {y1}) (xy 80 {y1})))' if filled else ''
    return f'\n\t(zone (net 1) (net_name "GND") (layer "{layer}") (polygon (pts (xy 80 20) (xy 130 20) (xy 130 {y1}) (xy 80 {y1}))){fill}\n\t)'

def board(in1_y=50.5, ref='(property "Reference" "AE1" (at 0 0 0) (layer "F.SilkS"))', filled=True, footprint=None):
    fp = footprint or f'''
\t(footprint "ant" (layer "F.Cu") (at 100 50)
\t\t{ref}
\t\t(fp_poly (pts (xy 9 9) (xy 9 8) (xy 8 8)) (stroke (width 0)) (layer "F.Fab"))
\t\t(fp_poly (pts (xy 0 0.5) (xy 10 0.5) (xy 10 1.5) (xy 0 1.5)) (stroke (width 0.2) (type solid)) (fill yes) (layer "F.Cu"))
\t\t(fp_line (start 0 2) (end 10 2) (stroke (width 0.5)) (layer "B.Cu"))
\t\t(pad "1" smd rect (at 1 0) (size 0.5 1) (layers "F.Cu" "F.Mask") (net 2 "RF"))
\t\t(pad "2" thru_hole circle (at 3 0) (size 0.6 0.6) (drill 0.3) (layers "*.Cu" "*.Mask") (net 1 "GND"))
\t\t(pad "" thru_hole circle (at 5 0) (size 0.6 0.6) (drill 0.3) (layers "*.Cu"))
\t)'''
    return f'''(kicad_pcb (version 20240108) (generator "pcbnew")
\t(general (thickness 1.6))
\t(layers (0 "F.Cu" signal) (4 "In1.Cu" signal) (6 "In2.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))
{STACKUP}
\t(net 0 "")
\t(net 1 "GND")
\t(net 2 "RF")
{fp}
\t(gr_line (start 80 20) (end 130 20) (stroke (width 0.1)) (layer "Edge.Cuts"))
\t(gr_line (start 80 53) (end 80 20) (stroke (width 0.1)) (layer "Edge.Cuts"))
\t(gr_arc (start 130 50) (mid 129.1213 52.1213) (end 127 53) (stroke (width 0.1)) (layer "Edge.Cuts"))
\t(gr_line (start 130 20) (end 130 50) (stroke (width 0.1)) (layer "Edge.Cuts"))
\t(gr_line (start 127 53) (end 80 53) (stroke (width 0.1)) (layer "Edge.Cuts"))
\t(gr_circle (center 110 30) (end 111 30) (stroke (width 0.1)) (layer "Edge.Cuts"))
\t(gr_line (start 0 0) (end 500 500) (stroke (width 0.1)) (layer "F.SilkS"))
\t(via (at 90 30) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))
\t(via (at 92 30) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 2)){zone("F.Cu", 49, filled)}{zone("In1.Cu", in1_y, filled)}{zone("B.Cu", 49, filled)}
)
'''

def extract(text, *args):
    d = tempfile.mkdtemp()
    pcb, out = os.path.join(d, 'b.kicad_pcb'), os.path.join(d, 'g.m')
    open(pcb, 'w', newline='\n', encoding='utf8').write(text)
    r = subprocess.run([sys.executable, os.path.join(HERE, 'extract_antenna.py'), pcb, 'AE1', out, *args], capture_output=True, text=True)
    return r, (open(out, encoding='utf8').read() if r.returncode == 0 else '')

def get(t, k):
    v = re.search(rf'geom\.{k} = (\[[^\]]*\]|\'[^\']*\')', t).group(1)
    return v.strip("'") if v[0] == "'" else [float(x) for x in v.strip('[]').replace(';', ' ').split()]

def area(v):
    p = list(zip(v[0::2], v[1::2]))
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(p, p[1:] + p[:1]))) / 2

near = lambda a, b, tol=1e-3: len(a) == len(b) and all(abs(x - y) < tol for x, y in zip(a, b))

# 1. vertical port to In1, 4-layer stackup with sublayers / locked thickness / parenthesised material
r, t = extract(board())
assert r.returncode == 0, r.stderr
assert get(t, 'gnd_net') == 'GND'
assert near(get(t, 'cu_z'), [1.405, 1.17, 0.235, 0]), get(t, 'cu_z')          # F, In1, In2, B
assert near(get(t, 'diel'), [0, 0.235, 4.3, 0, 0.235, 1.17, (0.8 * 4.6 + 0.1 * 4) / 0.9, (0.8 * 0.02 + 0.1 * 0.01) / 0.9,
                             1.17, 1.405, 4.3, 0.02], 1e-4), get(t, 'diel')    # tan d 0 kept as 0
o = get(t, 'outline')
assert near([min(o[0::2]), min(o[1::2]), max(o[0::2]), max(o[1::2])], [-20, -3, 30, 30]), o   # silk line not in it
assert abs(area(o) - (50 * 33 - (9 - 3.14159 * 9 / 4))) < 0.1, area(o)                # rounded corner
assert len(re.findall(r'geom\.holes = \{\[', t)) == 1
assert t.count('geom.ant{end+1}') == 1 + 4 + 1 + 1 + 4 + 4, t.count('geom.ant{end+1}')  # poly+stroke, B line, 3 pads
assert "'F.Fab'" not in t and re.search(r"'B.Cu', 'z', 0(.0)?, 'pts'", t)
assert near(get(t, 'lines'), [3, 0, 0, 1.405, 5, 0, 0, 1.405, -10, 20, 0, 1.405]), get(t, 'lines')  # barrels + GND via only
assert near(get(t, 'port'), [0.75, -0.5, 1.17, 1.25, 0.5, 1.405]) and get(t, 'port_dir') == [0, 0, 1], get(t, 'port')
assert t.count('geom.gnd{end+1}') == 3
assert get(t, 'edge_x') == [-0.25, 1, -0.1, 1, 0.75, 1, 1.25, -1, 10.1, -1, 10.25, -1], get(t, 'edge_x')   # thirds-rule edges
assert get(t, 'edge_y') == [-2.25, 1, -1.75, -1, -1.6, 1, -0.4, -1, 0.5, -1], get(t, 'edge_y')

# 2. no GND under the feed on any layer -> in-plane port to the F.Cu fill edge (KiCad y 49 = sim y 1)
r, t = extract(board(in1_y=49))
assert r.returncode == 0, r.stderr
assert near(get(t, 'port'), [0.75, 0.5, 1.405, 1.25, 1, 1.405]) and get(t, 'port_dir') == [0, 1, 0], get(t, 'port')

# 3. KiCad 6/7 reference syntax, --gnd / --feed options, error paths
r, t = extract(board(ref='(fp_text reference "AE1" (at 0 0) (layer "F.SilkS"))'))
assert r.returncode == 0, r.stderr
r, _ = extract(board(filled=False)); assert r.returncode and 'press B' in r.stderr, r.stderr
r, _ = extract(board(), '--feed', '7'); assert r.returncode and 'pad "7"' in r.stderr, r.stderr
r, _ = extract(board(), '--gnd', 'NOPE'); assert r.returncode and 'no filled NOPE zones' in r.stderr, r.stderr

# 4. KiCad's own antenna footprints, dropped into the test board
lib = sorted(glob.glob(r'C:\Program Files\KiCad\*\share\kicad\footprints\RF_Antenna.pretty'))
for name in ('Texas_SWRA117D_2.4GHz_Left', 'Texas_SWRA416_868MHz_915MHz') if lib else ():
    src = open(os.path.join(lib[-1], name + '.kicad_mod'), encoding='utf8').read().replace('"REF**"', '"AE1"')
    src = '\n'.join('\t' + l for l in src.replace(f'(footprint "{name}"', f'(footprint "{name}" (at 100 50)', 1).splitlines())
    r, t = extract(board(footprint=src))
    assert r.returncode == 0, (name, r.stderr)
    print(f'{name}: {r.stdout.strip()}')

# 5. the ground net: a sheet-path name from pad 2, a ground-named zone net when pad 2 has none, --gnd typed loosely
agnd = board().replace('"GND"', '"/rf/AGND"')
r, t = extract(agnd); assert r.returncode == 0 and get(t, 'gnd_net') == '/rf/AGND', r.stderr
nopad2 = agnd.replace('"*.Mask") (net 1 "/rf/AGND")', '"*.Mask")'); assert nopad2 != agnd
r, t = extract(nopad2); assert r.returncode == 0 and get(t, 'gnd_net') == '/rf/AGND' and 'ground net: /rf/AGND' in r.stdout, r.stderr
r, t = extract(nopad2, '--gnd', 'agnd'); assert r.returncode == 0 and get(t, 'gnd_net') == '/rf/AGND', r.stderr
r, _ = extract(nopad2.replace('AGND', 'PLANE')); assert r.returncode and '/rf/PLANE' in r.stderr and 'Ground net' in r.stderr, r.stderr
# pad 2 on a net with no zone (not connected) or pad 2 as the feed: it does not name the ground
r, t = extract(board().replace('"*.Mask") (net 1 "GND")', '"*.Mask") (net 3 "unconnected-(AE1-Pad2)")')); assert r.returncode == 0 and get(t, 'gnd_net') == 'GND', r.stderr
r, t = extract(board().replace('(net 2 "RF")', '(net 1 "GND")').replace('"*.Mask") (net 1 "GND")', '"*.Mask") (net 2 "RF")'), '--feed', '2'); assert r.returncode == 0 and get(t, 'gnd_net') == 'GND', r.stderr

# 6. a GND track is ground copper (an IFA's short can reach the ground through one); another net's track is not
trk = '\t(segment (start 100 49.5) (end 103 49.5) (width 0.2) (layer "F.Cu") (net %d))\n\t(via (at 90 30)'
r, t = extract(board().replace('\t(via (at 90 30)', trk % 1)); assert r.returncode == 0 and t.count('geom.gnd{end+1}') == 4, r.stderr
r, t = extract(board().replace('\t(via (at 90 30)', trk % 2)); assert r.returncode == 0 and t.count('geom.gnd{end+1}') == 3, r.stderr

# 7. ground copper only diagonal from the feed pad: no straight port reaches it, so stop and say so
diag = board(in1_y=49).replace('(xy 80 20) (xy 130 20) (xy 130 49) (xy 80 49)', '(xy 105 20) (xy 130 20) (xy 130 49) (xy 105 49)')
r, _ = extract(diag); assert r.returncode and 'diagonal' in r.stderr, r.stderr
# ... but straight-across copper wins over a nearer diagonal corner (here a GND track's end)
r, t = extract(board(in1_y=49).replace('\t(via (at 90 30)', '\t(segment (start 99 49.2) (end 100.4 49.2) (width 0.2) (layer "F.Cu") (net 1))\n\t(via (at 90 30)'))
assert r.returncode == 0 and get(t, 'port_dir') == [0, 1, 0], r.stderr

# 8. an outline gap KiCad still joins (0.005 mm) is closed; a real gap (0.05 mm) is an error
gap = lambda g: board().replace('(start 80 53) (end 80 20)', f'(start 80 53) (end 80 {20 + g})')
r, _ = extract(gap(0.005)); assert r.returncode == 0, r.stderr
r, _ = extract(gap(0.05)); assert r.returncode and 'not closed' in r.stderr, r.stderr
# an outline piece shorter than that is dropped, not kept as a one-point cutout
tiny = gap(0.004).replace('\t(via (at 90 30)', '\t(gr_line (start 80 20.004) (end 80 20) (layer "Edge.Cuts"))\n\t(via (at 90 30)')
r, _ = extract(tiny); assert r.returncode == 0 and ' 1 cutouts' in r.stdout, (r.stdout, r.stderr)

# 9. a through-hole feed pad: the port starts on the footprint's side, not on the bottom layer
r, t = extract(board(), '--feed', '2'); assert r.returncode == 0 and get(t, 'port_kind').startswith('vertical F.Cu'), (r.stderr, t[:300])

# 10. a board as KiCad 10 saves it (nets by name only, version 20260206)
k10 = open(os.path.join(HERE, 'fixtures', 'ifa_kicad10.kicad_pcb'), encoding='utf8').read()
r, t = extract(k10); assert r.returncode == 0 and get(t, 'gnd_net') == 'GND' and 'vertical F.Cu -> B.Cu' in get(t, 'port_kind'), r.stderr

# 11. automatic pick: the same rule as the plugin (reference AE* / ANT*, a digit not needed), REF** is not picked
def auto(ref):
    d = tempfile.mkdtemp(); pcb = os.path.join(d, 'b.kicad_pcb')
    open(pcb, 'w', newline='\n', encoding='utf8').write(board(ref=f'(property "Reference" "{ref}" (at 0 0 0) (layer "F.SilkS"))'))
    return subprocess.run([sys.executable, os.path.join(HERE, 'extract_antenna.py'), pcb, 'auto', os.path.join(d, 'g.m')], capture_output=True, text=True)
for ref in ('ANT', 'AE1', 'ANT2', 'ae'):
    r = auto(ref); assert r.returncode == 0 and f'antenna footprint: {ref}' in r.stdout, (ref, r.stderr)
r = auto('REF**'); assert r.returncode != 0 and 'cannot pick the antenna footprint' in r.stderr, r.stderr
print('OK')
