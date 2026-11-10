"""kicad2ant: simulate a PCB antenna from a KiCad board in openEMS.

  python kicad2ant.py BOARD.kicad_pcb [REF] [--mode dry|coarse|fine] [--f0 MHz] [--band LO HI]
                      [--feed PAD] [--gnd NET] [--out DIR] [--post]

REF is the antenna footprint (default: the one AE*/ANT* or RF_Antenna footprint). Results go to
BOARD_kicad2ant/ next to the board (or --out): results/<REF>_<mode>_summary.txt and plots.
Put a VNA measurement there as measured.s1p to overlay it. --post redoes only the post-processing.
Finds Octave and openEMS itself; set OCTAVE / OPENEMS to override.
"""
import argparse, glob, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.name == 'nt'
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('board'); ap.add_argument('ref', nargs='?', default='auto')
ap.add_argument('--mode', choices=('dry', 'coarse', 'fine'), default='coarse',
                help='dry = model + geometry plot only; coarse = minutes; fine = for numbers you quote')
ap.add_argument('--f0', type=float, default=2440, help='design frequency, MHz (default 2440)')
ap.add_argument('--band', type=float, nargs=2, metavar=('LO', 'HI'), help='target band, MHz (default 2400 2483.5 at 2.44 GHz, else f0 -/+ 2 %%)')
ap.add_argument('--feed', help='feed pad (default 1)'); ap.add_argument('--gnd', help='ground net (default: net of pad 2, else GND)')
ap.add_argument('--out', help='run folder (default BOARD_kicad2ant next to the board); no spaces')
ap.add_argument('--post', action='store_true', help='only redo the post-processing on the saved fields')
a = ap.parse_args()

def first(*cands):
    return next((c for c in cands if c and os.path.exists(c)), None)

def octave():
    exe = os.environ.get('OCTAVE') or shutil.which('octave-gui') or shutil.which('octave')
    if not exe and WIN:
        exe = (sorted(glob.glob(r'C:\Program Files\GNU Octave\Octave-*\mingw64\bin\octave-gui.exe'))
               + sorted(glob.glob(os.path.expandvars(r'%LOCALAPPDATA%\Programs\GNU Octave\Octave-*\mingw64\bin\octave-gui.exe'))) or [None])[-1]
    if not exe: sys.exit('Octave not found: install it (octave.org) or set OCTAVE to octave-gui.exe / octave')
    return exe

def openems():
    if 'OPENEMS' in os.environ: return os.environ['OPENEMS']
    exe = shutil.which('openEMS')
    if exe and os.path.isdir(os.path.join(os.path.dirname(exe), 'matlab')): return os.path.dirname(exe)
    if WIN:   # the Windows zip is unpacked anywhere: look two folders deep on every drive
        hits = [os.path.dirname(p) for d in 'CDEFGH' for p in glob.glob(f'{d}:/openEMS*/openEMS.exe') + glob.glob(f'{d}:/*/openEMS*/openEMS.exe')
                + glob.glob(f'{d}:/*/openEMS*/openEMS/openEMS.exe')]
        if hits: return sorted(hits)[-1]
    return ''   # Linux / macOS: openEMS already on the Octave path via .octaverc

board = os.path.abspath(a.board)
if not os.path.isfile(board): sys.exit(f'no such board: {board}')
out = os.path.abspath(a.out or os.path.splitext(board)[0] + '_kicad2ant')
if ' ' in out: sys.exit(f'the run folder has a space ({out}): openEMS nf2ff cannot use it, pass --out C:\\sim\\myboard')
os.makedirs(out, exist_ok=True)
f0 = a.f0 * 1e6
lo, hi = [b * 1e6 for b in a.band] if a.band else ((2400e6, 2483.5e6) if abs(f0 - 2.44e9) < 1e7 else (f0 * 0.98, f0 * 1.02))
if not a.band and a.f0 == 2440: print('target band 2400..2483.5 MHz (2.4 GHz ISM); give --f0 / --band for another', flush=True)

if not a.post:
    cmd = [sys.executable, os.path.join(HERE, 'extract_antenna.py'), board, a.ref, os.path.join(out, 'antenna_geom.m')]
    cmd += ['--feed', a.feed] * bool(a.feed) + ['--gnd', a.gnd] * bool(a.gnd)
    if subprocess.run(cmd).returncode: sys.exit(1)

ems = openems()
if ' ' in ems: sys.exit(f'openEMS is in a path with a space ({ems}): nf2ff cannot run there, move it and set OPENEMS')
q = lambda s: s.replace("'", "''")
script = (f"res='{'coarse' if a.mode == 'dry' else a.mode}'; dry_run={int(a.mode == 'dry')}; skip_fdtd={int(a.post)}; "
          f"f0={f0:.6g}; band_t=[{lo:.8g} {hi:.8g}]; run_dir='{q(out)}'; ems='{q(ems)}'; "
          f"run('{q(os.path.join(HERE, 'antenna_sim.m'))}')")
# --no-gui (qt toolkit) rather than octave-cli: only qt prints figures without a display
r = subprocess.run([octave(), '--no-gui', '--eval', script])
print(f'\nresults in {os.path.join(out, "results")}' if r.returncode == 0 else '\nfailed (see above)')
sys.exit(r.returncode)
