"""Self-check for fp_tools.py: python test_fp_tools.py  (prints OK or fails an assert).
The oracle is KiCad's own footprint save: fixtures/rot90_AE_tuned.kicad_mod was written by pcbnew's FootprintSave
from footprint AE1 of fixtures/rot90.kicad_pcb (rotated 90 degrees, pads on nets), with NOTE "kicad2ant test note"."""
import os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fp_tools  # noqa: E402

FIX = os.path.join(HERE, 'fixtures')
ROT90 = open(os.path.join(FIX, 'rot90.kicad_pcb'), encoding='utf-8').read()
ORACLE = open(os.path.join(FIX, 'rot90_AE_tuned.kicad_mod'), encoding='utf-8').read()
# AE1 at 30 degrees holding a keepout zone, a dimension, text boxes, a group, a pad at 45 degrees, pad net
# "Net-(AE1-Pad1)" and a descr with a newline; the .kicad_mod is pcbnew's FootprintSave of it
EXTRAS = open(os.path.join(FIX, 'rot30_extras.kicad_pcb'), encoding='utf-8').read()
EXTRAS_ORACLE = open(os.path.join(FIX, 'rot30_extras_AE_tuned.kicad_mod'), encoding='utf-8').read()
NOTE = 'kicad2ant test note'
DROP = {'uuid', 'version', 'generator', 'generator_version'}


def parse(s):
    out = [[]]
    for m in re.finditer(r'\(|\)|"((?:[^"\\]|\\.)*)"|[^\s()"]+', s):
        t = m.group()
        if t == '(': out.append([])
        elif t == ')': x = out.pop(); out[-1].append(x)
        else: out[-1].append(m.group(1) if m.group(1) is not None else t)
    return out[0][0]


def clean(n):
    if not isinstance(n, list):
        try: return round(float(n), 5)   # KiCad rounds rotated points to 1 nm in integers
        except ValueError: return n
    n = [clean(c) for c in n if not (isinstance(c, list) and c and c[0] in DROP)]
    if n and n[0] == 'at' and len(n) == 4 and min(n[3] % 360, -n[3] % 360) < 1e-3:   # KiCad writes 359.99997
        n = n[:3]
    if n and n[0] == 'members':   # KiCad's save gives the items new uuids
        n = n[:1]
    if n and n[0] == 'fp_text_box':   # 4 corners (ours) or start/end (KiCad): the same box
        pts = [c[1:] for c in n if c[0] in ('start', 'end')] + \
              [p[1:] for c in n if c[0] == 'pts' for p in c[1:]]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        n = [c for c in n if not (isinstance(c, list) and c[0] in ('start', 'end', 'pts'))]
        n.append(['box', min(xs), min(ys), max(xs), max(ys)])
    return n


def norm(t):
    fp = clean(parse(t))
    return [fp[0], fp[1]] + sorted(repr(c) for c in fp[2:])


def mod(board=ROT90, ref='AE1', note=NOTE):
    return fp_tools.footprint_to_mod(board, ref, 'AE_tuned', note)


def raises(f, text):
    try: f()
    except ValueError as e:
        assert text in str(e), e
        return
    raise AssertionError('no ValueError')


def ae1(board):
    """(start, end) of AE1's footprint in board text."""
    i = board.index('(footprint "Texas_SWRA117D')
    return i, fp_tools.span(board, i)


def test_matches_kicad():
    assert norm(mod()) == norm(ORACLE)


def test_extras_match_kicad():   # zone and dimension points are board coordinates on the board
    assert norm(mod(EXTRAS)) == norm(EXTRAS_ORACLE)


def test_net_with_parens():
    m = mod(ROT90.replace('(net "RF")', '(net "/RF)x")'))
    assert '(net ' not in m and 'x")' not in m


def test_descr_newline_kept():
    assert r'(descr "line1\nline2 \"q\" kicad2ant test note")' in mod(EXTRAS)


def test_kicad_cli_newest():
    paths = [os.path.join('KiCad', v, 'bin', 'kicad-cli.exe') for v in ('9.0', '10.0')]
    assert max(paths, key=fp_tools.version_key) == paths[1]


def test_kicad_cli_path_not_first():   # KiCad 9 on PATH must not win over an installed KiCad 10
    tmp = tempfile.mkdtemp()
    exes = {}
    for v in ('9.0', '10.0'):
        d = os.path.join(tmp, 'KiCad', v, 'bin')
        os.makedirs(d)
        exes[v] = os.path.join(d, 'kicad-cli.exe' if os.name == 'nt' else 'kicad-cli')
        open(exes[v], 'w').close()
        os.chmod(exes[v], 0o755)
    old = os.environ.get('PATH'), os.environ.pop('KICAD_CLI', None), fp_tools.INSTALLS
    os.environ['PATH'] = os.path.dirname(exes['9.0'])
    fp_tools.INSTALLS = [os.path.join(tmp, 'KiCad', '*', 'bin', os.path.basename(exes['9.0']))]
    try:
        assert fp_tools.find_kicad_cli() == exes['10.0'], fp_tools.find_kicad_cli()
    finally:
        os.environ['PATH'], fp_tools.INSTALLS = old[0], old[2]
        if old[1] is not None: os.environ['KICAD_CLI'] = old[1]


def test_no_nets_no_place():
    m = mod()
    assert '(net ' not in m and '(at 100 50' not in m
    assert '"REF**"' in m and m.startswith('(footprint "AE_tuned"')
    assert '(version 20260206)' in m


def test_unrotated_unchanged():
    i, j = ae1(ROT90)
    b0 = ROT90[:i] + re.sub(r'(\(at [-\d.]+ [-\d.]+) 90\)', r'\1 0)', ROT90[i:j]) + ROT90[j:]
    assert '(at 100 50 0)' in b0
    assert norm(mod(b0)) == norm(ORACLE)


def test_old_fp_text_reference():
    b = ROT90.replace('(property "Reference" "AE1"', '(fp_text reference "AE1"')
    m = mod(b)
    assert '(fp_text reference "REF**"' in m
    k = m.index('(fp_text reference')
    assert re.match(r'\(fp_text reference "REF\*\*"\s+\(at -4\.55 -6\.41 0\)', m[k:]), m[k:k + 60]


def test_back_side_refused():
    i, j = ae1(ROT90)
    b = ROT90[:i] + ROT90[i:j].replace('(layer "F.Cu")', '(layer "B.Cu")', 1) + ROT90[j:]
    raises(lambda: mod(b), 'back side')


def test_kept_children():
    i, j = ae1(ROT90)
    extra = '\n\t\t(model "${KIPRJMOD}/x.step"\n\t\t\t(offset (xyz 0 0 0))\n\t\t)\n\t'
    b = ROT90[:j - 1] + extra + ROT90[j - 1:]
    m = mod(b)
    assert '(model "${KIPRJMOD}/x.step"' in m and '(offset (xyz 0 0 0))' in m
    assert '(embedded_fonts no)' in m


def test_quoted_paren():
    s = '(descr "a (b) \\"c)\\"") tail'
    assert s[fp_tools.span(s, 0):] == ' tail'
    b = ROT90.replace('(descr "http://www.ti.com/lit/an/swra117d/swra117d.pdf")', '(descr "a (b) \\"c\\"")')
    assert '(descr "a (b) \\"c\\" kicad2ant test note")' in mod(b)


def test_missing_ref():
    raises(lambda: mod(ref='XX'), 'no footprint XX')


def test_kicad_cli_env():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        exe = f.name
    old = os.environ.get('KICAD_CLI')
    os.environ['KICAD_CLI'] = exe
    try:
        assert fp_tools.find_kicad_cli() == exe
    finally:
        os.remove(exe)
        if old is None: del os.environ['KICAD_CLI']
        else: os.environ['KICAD_CLI'] = old


def test_cli_save(tmp=None):
    tmp = tempfile.mkdtemp()
    brd, lib = os.path.join(tmp, 'b.kicad_pcb'), os.path.join(tmp, 'my lib.pretty')
    open(brd, 'w', encoding='utf-8').write(ROT90)
    sys.argv = ['fp_tools.py', 'save-footprint', brd, 'AE1', lib, 'AE_tuned', NOTE]
    fp_tools.main()
    assert norm(open(os.path.join(lib, 'AE_tuned.kicad_mod'), encoding='utf-8').read()) == norm(ORACLE)


for name, f in list(globals().items()):
    if name.startswith('test_'):
        f()
print('OK')
