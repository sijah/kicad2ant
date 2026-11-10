"""Helpers for the kicad2ant KiCad plugin, free of wx and pcbnew so they can be tested on their own."""
import glob, hashlib, os, re, shutil, signal, subprocess, sys, time

TARGET_DB = {'fast': 30.0, 'coarse': 40.0, 'fine': 50.0}   # openEMS end criterion 1e-3 / 1e-4 / 1e-5 in antenna_sim.m
MODES = [   # (mode, what it does), in the order the plugin lists them; the same words are in kicad2ant.py --help and the README
    ('dry', 'Builds the model and draws it, no simulation. Do it first, to see the port and the ground.'),
    ('fast', 'Rougher model: S11, Zin, resonance and the -10 dB band, no gain or pattern. For each tuning step.'),
    ('coarse', 'Also directivity, efficiency, gain and pattern. To confirm the variant you chose.'),
    ('fine', 'Finer mesh, runs to -50 dB. For the numbers you report.')]


def mode_key(saved):
    """The mode a saved setting means: 0.1.0 saved the list index (0 dry, 1 coarse, 2 fine), later versions the name."""
    if type(saved) is int and 0 <= saved <= 2:
        return ('dry', 'coarse', 'fine')[saved]
    return saved if saved in dict(MODES) else 'fast'
ENERGY = re.compile(r"Timestep:\s*(\d+).*?\(\s*-\s*([\d.]+)\s*dB\)")
PHASES = (('antenna footprint:', 'Reading the board'), ('Create FDTD operator', 'Meshing'),
          ('Running FDTD engine', 'Simulating'), ('openEMS running', 'Simulating'),
          ('Time for ', 'Post-processing'), ('nf2ff', 'Post-processing'))
SUMMARY = ('case:', 'fast (', 'resonance','min S11', 'S11 < -10', 'no -10 dB band', 'at ', 'run:')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def progress(line, target_db):
    """Fraction done (0..0.99) from an openEMS 'Timestep ... (- xx dB)' line, else None."""
    m = ENERGY.search(line)
    return min(max(float(m.group(2)) / target_db, 0.0), 0.99) if m and target_db else None


def phase(line):
    if re.search(r'^\w+ mesh: ', line):
        return 'Meshing'
    return next((name for key, name in PHASES if key in line), None)


def is_antenna_ref(ref, lib_name):
    """The footprint kicad2ant would treat as an antenna (same rule as its automatic pick)."""
    return bool(re.match(r'(AE|ANT)', ref, re.I)) or 'antenna' in lib_name.lower()


def run_dir(board_path, env=os.environ, base=''):
    """Run folder: BOARD_kicad2ant next to the board (or in `base`, the folder the user chose), or a space-free fallback (openEMS nf2ff cannot use a path with spaces)."""
    if not board_path:
        raise ValueError('save the board once first')
    stem = os.path.splitext(os.path.basename(board_path))[0]
    here = os.path.join(base or os.path.dirname(board_path), stem + '_kicad2ant')
    if ' ' not in here:
        return here
    # the home folder before the temp folder: results there survive a reboot
    for home in (env.get('LOCALAPPDATA'), env.get('USERPROFILE') or env.get('HOME'), 'C:\\' if os.name == 'nt' else '/tmp'):
        if home and ' ' not in home:
            break
    tag = hashlib.md5(board_path.encode('utf-8')).hexdigest()[:6]
    return os.path.join(home, 'kicad2ant', stem.replace(' ', '_') + '_' + tag)


CASE_FIELDS = (('εr', '3.0'), ('tanδ', '0.01'), ('wall', '2'), ('gap side', '1'), ('top', '1'), ('bottom', '1'))   # ABS


def case_args(values):
    """The --case numbers from the plastic case fields (epsR, tanD, wall, gap side, top, bottom, mm).
    ValueError unless epsR >= 1, wall > 0 and the others >= 0."""
    v = [float(x) for x in values]
    if len(v) != 6 or not v[0] >= 1 or not v[2] > 0 or not min(v[1:]) >= 0:
        raise ValueError(values)
    return ['%g' % x for x in v]


def build_cmd(python, script, board_copy, out, mode, ref='auto', feed='', f0='', band=(), gnd='', view=False, case=()):
    cmd = [python, script, board_copy, ref or 'auto', '--mode', mode, '--out', out]
    if feed:
        cmd += ['--feed', feed]
    if f0:
        cmd += ['--f0', f0]
    if len(band) == 2 and all(band):
        cmd += ['--band', band[0], band[1]]
    if gnd:
        cmd += ['--gnd', gnd]
    if case:   # plastic case: epsR, tanD, wall, gap side, top, bottom
        cmd += ['--case'] + list(case)
    if view:
        cmd.append('--view')
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


PICTURES = (('S11 / Zin', '_%s_s11_zin.png'), ('Smith', '_%s_smith.png'), ('Pattern', '_%s_pattern.png'),
            ('Model', '_geometry.png'))


def result_pictures(out, name, mode):
    """[(label, path)] of the plots this run left in <out>/results, in the order the Results tab lists them."""
    pics = PICTURES[-1:] if mode == 'dry' else PICTURES
    paths = [(label, os.path.join(out, 'results', name + (s % mode if '%' in s else s))) for label, s in pics]
    return [(label, p) for label, p in paths if os.path.isfile(p)]


def fit(w, h, box_w, box_h):
    """Picture size that fits the box with the aspect kept; never larger than the picture itself."""
    k = min(box_w / w, box_h / h, 1.0)
    return int(w * k), int(h * k)


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


def failure_line(lines):
    """The last line of a failed run that says what went wrong (not kicad2ant's 'failed (see above)')."""
    return next((l.strip() for l in reversed(lines) if l.strip() and l.strip() != 'failed (see above)'), '')


def band_covered(lines):
    """Whether the summary says the -10 dB band covers the target band."""
    return any(l.startswith('S11 < -10') and ' covers the ' in l for l in lines)


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


def pid_alive(pid, name=''):
    """Whether a process is running (on Windows: and its program name starts with `name`, since pids are
    reused). Not os.kill(pid, 0): on Windows that terminates it."""
    if pid <= 0:
        return False
    if os.name == 'nt':
        out = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid, '/NH', '/FO', 'CSV'], capture_output=True,
                             text=True, creationflags=NO_WINDOW).stdout
        return '"%d"' % pid in out and out.strip().lower().startswith('"' + name.lower())
    # shortcut: no name check on POSIX, pid reuse there is rare; read /proc/<pid>/comm if it bites
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_holder(folder):
    """The pid of the live kicad2ant run (a python process) named in <folder>/.running, else None."""
    try:
        with open(os.path.join(folder, '.running')) as f:
            pid = int(f.read().strip() or 0)
    except (OSError, ValueError):
        return None
    return pid if pid_alive(pid, 'python') else None


def take_lock(folder, pid):
    """Marks the run folder as used by `pid`. None if taken (also when `pid` holds it already, as when the plugin
    wrote its child's pid), else the pid of the other live run, and nothing is written."""
    holder = lock_holder(folder)
    if holder not in (None, pid):
        return holder
    with open(os.path.join(folder, '.running'), 'w') as f:
        f.write(str(pid))
    return None


def release_lock(folder, pid):
    """Removes <folder>/.running if `pid` holds it."""
    p = os.path.join(folder, '.running')
    try:
        with open(p) as f:
            mine = f.read().strip() == str(pid)
        if mine:
            os.remove(p)
    except OSError:
        pass


def open_folder(path):
    if os.name == 'nt':
        os.startfile(path)
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', path])
