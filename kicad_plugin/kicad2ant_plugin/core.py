"""Helpers for the kicad2ant KiCad plugin, free of wx and pcbnew so they can be tested on their own."""
import glob, hashlib, os, re, shutil, signal, subprocess, sys, time

TARGET_DB = {'coarse': 40.0, 'fine': 50.0}   # openEMS end criterion 1e-4 / 1e-5 in antenna_sim.m
ENERGY = re.compile(r"Timestep:\s*(\d+).*?\(\s*-\s*([\d.]+)\s*dB\)")
PHASES = (('antenna footprint:', 'Reading the board'), ('Create FDTD operator', 'Meshing'),
          ('Running FDTD engine', 'Simulating'), ('openEMS running', 'Simulating'),
          ('Time for ', 'Post-processing'), ('nf2ff', 'Post-processing'))
SUMMARY = ('resonance', 'min S11', 'S11 < -10', 'no -10 dB band', 'at ', 'run:')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def progress(line, target_db):
    """Fraction done (0..0.99) from an openEMS 'Timestep ... (- xx dB)' line, else None."""
    m = ENERGY.search(line)
    return min(max(float(m.group(2)) / target_db, 0.0), 0.99) if m and target_db else None


def phase(line):
    if re.search(r'^\w+ mesh: ', line):
        return 'Meshing'
    return next((name for key, name in PHASES if key in line), None)


def antenna_ref(line):
    return line[len('antenna footprint:'):].strip() if line.startswith('antenna footprint:') else None


def safe_name(ref):
    return re.sub(r'[^\w-]', '_', ref)   # as antenna_sim.m names its result files


def is_antenna_ref(ref, lib_name):
    """The footprint kicad2ant would treat as an antenna (same rule as its automatic pick)."""
    return bool(re.match(r'(AE|ANT)', ref, re.I)) or 'antenna' in lib_name.lower()


def run_dir(board_path, env=os.environ):
    """Run folder: next to the board, or a space-free fallback (openEMS nf2ff cannot use a path with spaces)."""
    if not board_path:
        raise ValueError('save the board once first')
    stem = os.path.splitext(os.path.basename(board_path))[0]
    here = os.path.join(os.path.dirname(board_path), stem + '_kicad2ant')
    if ' ' not in here:
        return here
    base = env.get('LOCALAPPDATA', '')
    if not base or ' ' in base:
        base = 'C:\\' if os.name == 'nt' else '/tmp'
    tag = hashlib.md5(board_path.encode('utf-8')).hexdigest()[:6]
    return os.path.join(base, 'kicad2ant', stem.replace(' ', '_') + '_' + tag)


def build_cmd(python, script, board_copy, out, mode, ref='auto', feed='', f0='', band=()):
    cmd = [python, script, board_copy, ref or 'auto', '--mode', mode, '--out', out]
    if feed:
        cmd += ['--feed', feed]
    if f0:
        cmd += ['--f0', f0]
    if len(band) == 2 and all(band):
        cmd += ['--band', band[0], band[1]]
    return cmd


def find_result(out, mode, since):
    """(summary path, REF as in the file names) of the newest result written at or after `since`; for dry runs
    the geometry picture counts and the summary path is ''. None if there is none."""
    dry = mode == 'dry'
    suffix = '_geometry.png' if dry else '_%s_summary.txt' % mode
    hits = [p for p in glob.glob(os.path.join(out, 'results', '*' + suffix))
            if os.path.getmtime(p) >= since and os.path.getsize(p) > 0]
    if not hits:
        return None
    p = max(hits, key=os.path.getmtime)
    return ('' if dry else p), os.path.basename(p)[:-len(suffix)]


def summary_lines(path):
    """The lines of a kicad2ant summary a user needs: resonance, -10 dB band, impedance at f0, convergence."""
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            text = f.read().splitlines()
    except OSError:
        return []
    keep = []
    for line in text:
        if line.startswith('   f MHz'):
            break
        if line.startswith(SUMMARY):
            keep.append(line)
    return keep


def find_python(exe=sys.executable, prefix=sys.prefix):
    """A Python 3 for running kicad2ant.py: KiCad's own if possible (inside KiCad sys.executable is kicad)."""
    d = os.path.dirname(exe)
    cands = [exe if os.path.basename(exe).lower().startswith('python') else '',
             os.path.join(d, 'python.exe'), os.path.join(prefix, 'python.exe'), os.path.join(prefix, 'bin', 'python3'),
             os.path.join(d, '..', 'Frameworks', 'Python.framework', 'Versions', 'Current', 'bin', 'python3'),
             shutil.which('python3') or '']
    py = shutil.which('python') or ''
    if 'WindowsApps' not in py:   # the Microsoft Store stub only opens the Store
        cands.append(py)
    return next((os.path.normpath(c) for c in cands if c and os.path.isfile(c)), '')


def kill_tree(proc):
    """Ends the process and everything it started (python -> octave -> openEMS)."""
    if proc is None or proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True, creationflags=NO_WINDOW)
        return
    try:   # the child was started with start_new_session, so its group id is its pid
        os.killpg(proc.pid, signal.SIGTERM)
        for _ in range(30):
            if proc.poll() is not None:
                return
            time.sleep(0.1)
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def open_folder(path):
    if os.name == 'nt':
        os.startfile(path)
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', path])
