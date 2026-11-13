"""kicad2ant: simulate a PCB antenna from a KiCad board in openEMS.

  python kicad2ant.py BOARD.kicad_pcb [REF] [--mode dry|fast|coarse|fine] [--f0 MHz] [--band LO HI]
                      [--feed PAD] [--gnd NET] [--case ER TAND WALL SIDE TOP BOTTOM] [--out DIR]
                      [--set KEY=VALUE ...] [--post] [--view]

REF is the antenna footprint (default: the one AE*/ANT* or RF_Antenna footprint). Results go to
BOARD_kicad2ant/ next to the board (or --out): results/<REF>_<mode>_summary.txt and plots.
Put a VNA measurement there as measured.s1p (more as measured1.s1p, measured2.s1p ..) to overlay it. --post redoes only the post-processing.
Finds Octave and openEMS itself; set OCTAVE / OPENEMS to override.
"""
import argparse, glob, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.name == 'nt'
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('board'); ap.add_argument('ref', nargs='?', default='auto')
ap.add_argument('--mode', choices=('dry', 'fast', 'coarse', 'fine'), default='fast',
                help='dry: builds the model and draws it, no simulation; fast (default): rougher model, S11 / Zin / '
                     'resonance / -10 dB band only, for each tuning step; coarse: also gain, efficiency and pattern, '
                     'to confirm the variant you chose; fine: finer mesh, for the numbers you report')
ap.add_argument('--f0', type=float, default=2440, help='design frequency, MHz (default 2440)')
ap.add_argument('--band', type=float, nargs=2, metavar=('LO', 'HI'), help='target band, MHz (default 2400 2483.5 at 2.44 GHz, else f0 -/+ 2 %%)')
ap.add_argument('--feed', help='feed pad (default 1)'); ap.add_argument('--gnd', help='ground net (default: net of pad 2, else GND or the largest ground-named zone net)')
ap.add_argument('--case', type=float, nargs=6, metavar=('ER', 'TAND', 'WALL', 'SIDE', 'TOP', 'BOTTOM'),
                help='plastic case, a box shell around the board: epsR, loss tangent, wall thickness and the gaps to the '
                     'board at the sides, top (F.Cu side) and bottom, mm; e.g. 3 0.01 2 1 1 1 for ABS. Default: the board in air')
ap.add_argument('--out', help='run folder (default BOARD_kicad2ant next to the board); no spaces')
ap.add_argument('--set', action='append', default=[], metavar='KEY=VALUE',
                help='override one run setting of the mode, e.g. --set cell=0.2 --set end_db=-50; the keys and each '
                     "mode's values are in mesher.py MODES (cell, nmin, nz, merge, ratio, air, f_start, f_stop, npts, "
                     'nrts, end_db, threads, pattern, f_pat, pat_step)')
ap.add_argument('--post', action='store_true', help='only redo the post-processing on the saved fields')
ap.add_argument('--view', action='store_true', help="open the 3D model in openEMS's viewer (AppCSXCAD) when the run ends")
a = ap.parse_args()

def octave():
    exe = os.environ.get('OCTAVE') or shutil.which('octave-gui') or shutil.which('octave')
    if not exe and WIN:
        found = (glob.glob(r'C:\Program Files\GNU Octave\Octave-*\mingw64\bin\octave-gui.exe')
                 + glob.glob(os.path.expandvars(r'%LOCALAPPDATA%\Programs\GNU Octave\Octave-*\mingw64\bin\octave-gui.exe')))
        ver = lambda p: [int(n) for n in re.findall(r'\d+', re.search(r'Octave-([\d.]*)', p).group(1))]   # 11.1 after 9.2
        exe = max(found, key=ver, default=None)
    if not exe: sys.exit('Octave not found: install it (octave.org) or set OCTAVE to octave-gui.exe / octave')
    return exe

def openems():
    if 'OPENEMS' in os.environ: return os.environ['OPENEMS']
    exe = shutil.which('openEMS')
    if exe and os.path.isdir(os.path.join(os.path.dirname(exe), 'matlab')): return os.path.dirname(exe)
    pre = os.path.dirname(os.path.dirname(os.path.realpath(exe))) if exe else ''   # a source build: <prefix>/bin/openEMS
    if pre and os.path.isdir(os.path.join(pre, 'share', 'openEMS', 'matlab')): return pre
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
# the run-folder lock lives in the plugin's core.py: next to this script's folder when installed, in the repo otherwise
for d in (os.path.dirname(HERE), os.path.join(os.path.dirname(HERE), 'kicad_plugin', 'kicad2ant_plugin')):
    if os.path.isfile(os.path.join(d, 'core.py')): sys.path.insert(0, d); break
import core  # noqa: E402
held = core.take_lock(out, os.getpid())
if held: sys.exit(f'another kicad2ant run is using {out} (pid {held}): wait for it to end, or give another --out')
import atexit; atexit.register(core.release_lock, out, os.getpid())
if a.f0 < 100 and a.mode != 'dry':
    sys.exit(f'f0 {a.f0:g} MHz is below 100 MHz (NFC and other low-frequency loops): this time-domain run would need '
             'millions of steps and stop unconverged after hours. Not supported.')
f0 = a.f0 * 1e6
lo, hi = [b * 1e6 for b in a.band] if a.band else ((2400e6, 2483.5e6) if abs(f0 - 2.44e9) < 1e7 else (f0 * 0.98, f0 * 1.02))
sys.path.insert(0, HERE)
import mesher  # noqa: E402
try:
    S = mesher.settings('coarse' if a.mode == 'dry' else a.mode, a.set)
    f_lo, f_hi = mesher.sweep(S, f0)
    if f_lo >= f_hi: raise ValueError(f'sweep start {f_lo/1e6:g} MHz is not below its stop {f_hi/1e6:g} MHz')
except ValueError as e: sys.exit(f'--set: {e}')
if not a.band and a.f0 == 2440: print('target band 2400..2483.5 MHz (2.4 GHz ISM); give --f0 / --band for another', flush=True)

if not a.post:
    cmd = [sys.executable, os.path.join(HERE, 'extract_antenna.py'), board, a.ref, os.path.join(out, 'antenna_geom.m')]
    cmd += ['--feed', a.feed] * bool(a.feed) + ['--gnd', a.gnd] * bool(a.gnd)
    cmd += ['--mode', 'coarse' if a.mode == 'dry' else a.mode, '--f0', str(a.f0)] + (['--case', *map(str, a.case)] if a.case else [])
    cmd += [x for kv in a.set for x in ('--set', kv)]
    if subprocess.run(cmd).returncode: sys.exit(1)

ems = openems()
if ' ' in ems: sys.exit(f'openEMS is in a path with a space ({ems}): nf2ff cannot run there, move it and set OPENEMS')
q = lambda s: s.replace("'", "''")
# the run folder gets the whole model as .m files: antenna_geom.m, antenna_sim.m and run_sim.m, which reruns it in Octave
shutil.copy(os.path.join(HERE, 'antenna_sim.m'), out)
with open(os.path.join(out, 'run_sim.m'), 'w', encoding='utf-8') as f:
    f.write(f"% kicad2ant: this run's settings. In Octave, run this file to run it again.\n"
            f"% dry_run=1 builds the model only; skip_fdtd=1 redoes only the post-processing.\n"
            f"res='{'coarse' if a.mode == 'dry' else a.mode}'; dry_run={int(a.mode == 'dry')}; skip_fdtd={int(a.post)};\n"
            f"f0={f0:.6g}; band_t=[{lo:.8g} {hi:.8g}]; case_box=[{' '.join('%g' % v for v in a.case or [])}];\n"
            f"f_lo={f_lo:.8g}; f_hi={f_hi:.8g}; npts={S['npts']}; nrts={S['nrts']}; end_crit={10 ** (S['end_db'] / 10):.6g}; "
            f"threads={S['threads']}; pattern={S['pattern']}; f_pat={S['f_pat'] * 1e6:.8g}; pat_step={S['pat_step']:g};\n"
            f"run_dir=fileparts(mfilename('fullpath')); ems='{q(ems)}';\n"
            f"run(fullfile(run_dir, 'antenna_sim.m'))\n")
script = f"run('{q(os.path.join(out, 'run_sim.m'))}')"
# --no-gui (qt toolkit) rather than octave-cli: only qt prints figures without a display
# one OpenBLAS thread: one per core fails to allocate its buffers on many-core machines ("Memory allocation still
# failed"), and Octave's share of the work is light (openEMS has its own threads)
r = subprocess.run([octave(), '--no-gui', '--eval', script], env=dict(os.environ, OPENBLAS_NUM_THREADS=os.environ.get('OPENBLAS_NUM_THREADS', '1')))
if a.view and r.returncode == 0:
    xml = os.path.join(out, 'sim_' + ('coarse' if a.mode == 'dry' else a.mode), 'antenna.xml')
    exe = next((p for p in (os.path.join(ems, 'AppCSXCAD.exe'), os.path.join(ems, 'bin', 'AppCSXCAD')) if ems and os.path.isfile(p)),
               shutil.which('AppCSXCAD'))
    if exe:   # detached and off our pipes: it stays open after this script ends, and the caller is not kept waiting
        null = subprocess.DEVNULL
        subprocess.Popen([exe, '--disableEdit', xml], cwd=os.path.dirname(exe), stdin=null, stdout=null, stderr=null,
                         **({'creationflags': 0x00000008 | 0x00000200} if WIN else {'start_new_session': True}))
    else: print('warning: --view: AppCSXCAD (the openEMS 3D viewer) was not found')
print(f'\nresults in {os.path.join(out, "results")}' if r.returncode == 0 else '\nfailed (see above)')
sys.exit(r.returncode)
