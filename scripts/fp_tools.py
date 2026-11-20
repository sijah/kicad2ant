"""Helpers for tuning an antenna on a copy of the board. Plain Python 3; refill needs KiCad's kicad-cli (KiCad 10+).

  fp_tools.py refill BOARD.kicad_pcb
      refills the zones and saves: do this after changing the antenna copper in a board copy, because
      kicad2ant reads the saved fills and those were made around the old antenna.
  fp_tools.py save-footprint BOARD.kicad_pcb REF LIB.pretty NAME [NOTE]
      saves footprint REF of the board as LIB.pretty/NAME.kicad_mod: unplaced, unrotated, pads without nets,
      the way KiCad's own footprint save writes it (test_fp_tools.py checks this against KiCad's output).
      This is how a tuned antenna gets from the simulated board copy into a footprint library.
      NOTE (e.g. "kicad2ant 0.2.0 fast: resonance 2438 MHz for f0 2440, run BOARD_try3_kicad2ant") is added
      to the footprint's description, so the library part says which simulation it came from.

Never run these on a board that is open in KiCad.
"""
import glob, math, os, re, shutil, subprocess, sys, tempfile

DROP = {'at', 'uuid', 'path', 'sheetname', 'sheetfile', 'locked', 'placed'}   # placement, not footprint
ANGLED = {'pad', 'property', 'fp_text'}   # on a board their (at x y a) angle includes the footprint's
NUM = r'(-?[\d.]+(?:e-?\d+)?)'


def span(text, start):
    """Index just past the s-expression that opens at text[start] == '('."""
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == '\\' else 1
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError('unbalanced s-expression')


def items(text, start, end):
    """(start, end, head) of each direct child of the s-expression text[start:end]; head is None for a bare token."""
    i = start + 1
    while i < end - 1:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == '(':
            j = span(text, i)
            yield i, j, re.match(r'\(\s*([^\s()"]+)', text[i:j]).group(1)
            i = j
        else:
            j = i
            if c == '"':
                j = i + 1
                while text[j] != '"':
                    j += 2 if text[j] == '\\' else 1
                j += 1
            else:
                while j < end - 1 and not text[j].isspace() and text[j] not in '()':
                    j += 1
            yield i, j, None
            i = j


def quote(s):
    return '"%s"' % s.replace('\\', '\\\\').replace('"', '\\"')


def ref_re(ref):
    return re.compile(r'\((property\s+"Reference"|fp_text\s+reference)\s+%s' % re.escape(quote(ref)))


def find_footprint(board, ref):
    r = ref_re(ref)
    for m in re.finditer(r'\(footprint\s', board):
        j = span(board, m.start())
        if r.search(board, m.start(), j):
            return m.start(), j
    raise ValueError('no footprint %s' % ref)


def fmt(v):
    """A number the way KiCad writes it: up to 6 decimals (1 nm), no trailing zeros."""
    t = ('%.6f' % v).rstrip('0').rstrip('.')
    return '0' if t == '-0' else t


def local_angle(a, fp_angle):
    a = (a - fp_angle) % 360
    return a - 360 if a > 180 else a


def turn(child, head, fp_angle):
    """Take the footprint angle off the child's own (at x y a)."""
    m = re.search(r'\(at\s+%s\s+%s(?:\s+%s)?\s*\)' % (NUM, NUM, NUM), child)
    if not m or not fp_angle:
        return child
    a = local_angle(float(m.group(3) or 0), fp_angle)
    at = '(at %s %s' % (m.group(1), m.group(2)) + (' %s)' % fmt(a) if a or head != 'pad' else ')')
    return child[:m.start()] + at + child[m.end():]


def to_local(child, x0, y0, fp_angle):
    """Zones and dimensions keep board coordinates on a board: move every (xy x y) and (at x y a) into the
    footprint's frame (KiCad: board = pos + rotate(local, angle), y down)."""
    c, s = math.cos(math.radians(fp_angle)), math.sin(math.radians(fp_angle))

    def pt(x, y):
        dx, dy = float(x) - x0, float(y) - y0
        return fmt(dx * c - dy * s), fmt(dx * s + dy * c)

    child = re.sub(r'\(xy\s+%s\s+%s\s*\)' % (NUM, NUM), lambda m: '(xy %s %s)' % pt(m.group(1), m.group(2)), child)

    def at(m):
        x, y = pt(m.group(1), m.group(2))
        a = ' %s' % fmt(local_angle(float(m.group(3)), fp_angle)) if m.group(3) else ''
        return '(at %s %s%s)' % (x, y, a)
    return re.sub(r'\(at\s+%s\s+%s(?:\s+%s)?\s*\)' % (NUM, NUM, NUM), at, child)


def footprint_to_mod(board_text, ref, name, note=''):
    """The .kicad_mod text of footprint REF of a board, as KiCad's footprint save writes it."""
    s, e = find_footprint(board_text, ref)
    fp = board_text[s:e]
    kids = list(items(fp, 0, len(fp)))
    layer = next((fp[a:b] for a, b, h in kids if h == 'layer'), '')
    if '"B.' in layer:   # shortcut: front-side footprints only, flip it back in KiCad first when one is needed
        raise ValueError('%s is on the back side: not supported' % ref)
    at = next((fp[a:b] for a, b, h in kids if h == 'at'), '(at 0 0)')
    nums = [float(v) for v in re.findall(NUM, at)] + [0.0]
    x0, y0, fp_angle = nums[0], nums[1], nums[2]
    version = re.search(r'\(version\s+(\d+)\)', board_text)
    out = ['(footprint %s' % quote(name)]
    if version:
        out.append('\t(version %s)' % version.group(1))
    out.append('\t(generator "kicad2ant")')
    has_descr = False
    for a, b, h in kids[2:]:   # past the word footprint and the old lib id
        child = fp[a:b]
        if (child if h is None else h) in DROP:   # older boards write a bare 'locked' / 'placed'
            continue
        elif h == 'descr' and note:
            d = list(items(child, 0, len(child)))
            text = child[d[1][0] + 1:d[1][1] - 1] if len(d) > 1 else ''   # still escaped, as in the file
            child = '(descr "%s")' % ' '.join(filter(None, [text, quote(note)[1:-1]]))
            has_descr = True
        elif h == 'descr':
            has_descr = True
        if h == 'pad':
            child = re.sub(r'\s*\(net\s+(?:\d+\s*)?(?:"(?:[^"\\]|\\.)*")?\s*\)', '', child)
        if h in ANGLED:
            child = turn(child, h, fp_angle)
        if h in ('zone', 'dimension'):
            child = to_local(child, x0, y0, fp_angle)
        child = ref_re(ref).sub(lambda m: '(%s %s' % (m.group(1), quote('REF**')), child)
        out.append('\t' + child.replace('\n\t', '\n'))
    if note and not has_descr:
        out.insert(3 if version else 2, '\t(descr %s)' % quote(note))
    return '\n'.join(out) + '\n)\n'


def version_key(path):
    """(10, 0) for .../KiCad/10.0/bin/kicad-cli.exe: newest install first, 10.0 above 9.0."""
    v = re.findall(r'[\\/](\d+(?:\.\d+)*)[\\/]', path)
    return tuple(int(n) for n in v[-1].split('.')) if v else ()


INSTALLS = [os.path.join(r, 'KiCad', '*', 'bin', 'kicad-cli.exe')   # Windows all-users and per-user installs
            for r in {os.environ.get('ProgramFiles', r'C:\Program Files'), r'C:\Program Files',
                      os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs')}]
INSTALLS.append('/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')


def find_kicad_cli():
    """KICAD_CLI if set, else the newest of PATH's kicad-cli and the installed ones (an old KiCad on PATH
    can't read newer boards)."""
    if os.path.isfile(os.environ.get('KICAD_CLI') or ''):
        return os.environ['KICAD_CLI']
    found = {f for p in INSTALLS for f in glob.glob(p)} | {shutil.which('kicad-cli')}
    found = [f for f in found if f and os.path.isfile(f)]
    return max(found, key=lambda f: version_key(os.path.realpath(f)), default=None)


def refill(board):
    cli = find_kicad_cli()
    if not cli:
        sys.exit('kicad-cli not found: install KiCad 10 or set KICAD_CLI')
    prl = os.path.splitext(board)[0] + '.kicad_prl'
    had_prl = os.path.exists(prl)
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([cli, 'pcb', 'drc', '--refill-zones', '--save-board', '-o', os.path.join(tmp, 'drc.rpt'),
                            board], capture_output=True, text=True)
    if not had_prl and os.path.exists(prl):
        os.remove(prl)
    if r.returncode != 0:
        sys.exit('kicad-cli could not refill %s:\n%s' % (board, (r.stderr or r.stdout).strip()))


def main():
    a = sys.argv
    if len(a) == 3 and a[1] == 'refill':
        refill(a[2])
        print('refilled', a[2])
    elif len(a) in (6, 7) and a[1] == 'save-footprint':
        path, ref, lib, name = a[2:6]
        with open(path, encoding='utf-8') as f:
            board = f.read()
        try:
            text = footprint_to_mod(board, ref, name, a[6] if len(a) == 7 else '')
        except ValueError as e:
            sys.exit('%s: %s' % (path, e))
        os.makedirs(lib, exist_ok=True)
        out = os.path.join(lib, name + '.kicad_mod')
        with open(out, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        print('saved', out)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
