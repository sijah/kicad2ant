"""Self-check for the plugin helpers: python kicad_plugin/test_core.py  (prints OK or fails an assert)."""
import os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'kicad2ant_plugin'))
import core  # noqa: E402

REAL = os.path.join(HERE, '..', 'examples', 'ti_ifa', 'ifa_kicad2ant', 'results', 'AE1_coarse_summary.txt')


def write(path, text, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_progress():
    assert abs(core.progress("[@ 12s] Timestep: 20480 || Energy: ~3.1e-04 (-35.08dB)", 40) - 35.08 / 40) < 1e-6
    assert core.progress("[@        4s] Timestep:           97 || Speed:    8.1 MC/s (4.808e-02 s/TS) || Energy: ~1.85e-22 (- 0.00dB)", 40) == 0.0
    assert core.progress("Timestep: 10 || Energy: ~1 (- 60.00dB)", 40) == 0.99
    assert core.progress("Create FDTD operator", 40) is None
    assert core.TARGET_DB.get('dry') is None and core.TARGET_DB['fine'] == 50.0


def test_phase():
    assert core.phase("antenna footprint: AE1") == 'Reading the board'
    assert core.phase("coarse mesh: 108 x 84 x 43 = 0.39 Mcells, smallest cell 0.150 mm") == 'Meshing'
    assert core.phase("Running FDTD engine... this may take a while... grab a cup of coffee?!?") == 'Simulating'
    assert core.phase("Time for 40546 iterations with 390096.00 cells : 120.4 sec") == 'Post-processing'
    assert core.phase("whatever") is None


def test_antenna_ref_rule():
    assert core.is_antenna_ref('AE1', 'x') and core.is_antenna_ref('ant2', 'x')
    assert core.is_antenna_ref('J3', 'RF_Antenna:Texas_SWRA117D_2.4GHz_Left')
    assert not core.is_antenna_ref('L4', 'Inductor_SMD:L_0402')


def test_run_dir():
    assert core.run_dir("D:/x/ifa.kicad_pcb", {}).replace('\\', '/') == "D:/x/ifa_kicad2ant"
    try:
        core.run_dir('', {}); assert False
    except ValueError:
        pass
    home = core.run_dir("/a b/x.kicad_pcb", {'HOME': '/home/u'})   # not the temp folder: results survive a reboot
    assert home.startswith(os.path.join('/home/u', 'kicad2ant', 'x_')), home
    if os.name == 'nt':
        d = core.run_dir(r"C:\Users\A B\p\my board.kicad_pcb", {'LOCALAPPDATA': r"C:\Users\A B\AppData\Local"})
        assert ' ' not in d and d.startswith('C:\\kicad2ant') and '\\my_board_' in d, d
        assert core.run_dir(r"C:\Users\A B\q\my board.kicad_pcb", {}) != d
        d2 = core.run_dir(r"C:\Users\A B\p\my board.kicad_pcb", {'LOCALAPPDATA': r"C:\Local"})
        assert d2.startswith('C:\\Local\\kicad2ant\\my_board_'), d2


def test_build_cmd():
    assert core.build_cmd('py', 'k.py', 'b', 'o', 'coarse', ref='AE2', feed='1', f0='868', band=('863', '870')) == \
        ['py', 'k.py', 'b', 'AE2', '--mode', 'coarse', '--out', 'o', '--feed', '1', '--f0', '868', '--band', '863', '870']
    assert core.build_cmd('py', 'k.py', 'b', 'o', 'dry', ref='', band=('863', ''), gnd='GNDA') == \
        ['py', 'k.py', 'b', 'auto', '--mode', 'dry', '--out', 'o', '--gnd', 'GNDA']


def test_summary_lines_real():
    assert core.summary_lines(REAL) == [
        'resonance (min S11) -9.2 dB at 2413 MHz', 'no -10 dB band',
        'at 2440 MHz: S11 -6.0 dB, Zin 20.8 +23.1j ohm',
        'run: converged in 40546 steps; mesh worst neighbour ratio 3.40 (above 2: abrupt cell jump, check the fine run agrees)']


def test_summary_lines_band_found():
    p = os.path.join(tempfile.mkdtemp(), 'AE1_fine_summary.txt')
    write(p, 'AE1 fine run (9 s)\nmin S11 -12.0 dB at 2300 MHz = SWEEP EDGE: no resonance in 2300..2600 MHz\n'
             'S11 < -10 dB: 2398 .. 2470 MHz, covers the 2400.0..2483.5 MHz target\n'
             '   f MHz  S11 dB   D dBi\n at 2440 junk\n')
    assert core.summary_lines(p) == ['min S11 -12.0 dB at 2300 MHz = SWEEP EDGE: no resonance in 2300..2600 MHz',
                                     'S11 < -10 dB: 2398 .. 2470 MHz, covers the 2400.0..2483.5 MHz target']
    assert core.summary_lines('nope.txt') == []
    assert core.band_covered(core.summary_lines(p))
    assert not core.band_covered(core.summary_lines(REAL))
    assert not core.band_covered(['S11 < -10 dB: 2398 .. 2450 MHz, MISSES the 2400.0..2483.5 MHz target'])


def test_find_result_ignores_stale():
    t = tempfile.mkdtemp(); t0 = time.time()
    write(os.path.join(t, 'results', 'AE1_coarse_summary.txt'), 'old\n', t0 - 10)
    write(os.path.join(t, 'results', 'AE2_coarse_summary.txt'), '', t0 + 1)
    assert core.find_result(t, 'coarse', t0) is None
    write(os.path.join(t, 'results', 'AE2_coarse_summary.txt'), 'AE2 coarse run\n', t0 + 2)
    assert core.find_result(t, 'coarse', t0) == (os.path.join(t, 'results', 'AE2_coarse_summary.txt'), 'AE2')
    assert core.find_result(t, 'coarse', 0)[1] == 'AE2'
    assert core.find_result(t, 'dry', t0) is None
    write(os.path.join(t, 'results', 'AE2_geometry.png'), 'png', t0 + 3)
    assert core.find_result(t, 'dry', t0) == ('', 'AE2')


def test_find_python():
    t = tempfile.mkdtemp(); exe = os.path.join(t, 'kicad.exe'); py = os.path.join(t, 'python.exe')
    for f in (exe, py):
        open(f, 'w').close()
    assert core.find_python(exe, '/nonexistent') == py
    assert core.find_python(py, '/nonexistent') == py


def test_pid_alive():
    assert core.pid_alive(os.getpid())
    assert not core.pid_alive(4999999) and not core.pid_alive(0)
    if os.name == 'nt':   # a reused pid of another program is not our simulation
        assert core.pid_alive(os.getpid(), 'python') and not core.pid_alive(os.getpid(), 'notepad')


def test_failure_line():
    assert core.failure_line(['error: openEMS not found, set OPENEMS', '', 'failed (see above)']) == \
        'error: openEMS not found, set OPENEMS'
    assert core.failure_line(['', 'failed (see above)']) == ''


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
    print('OK')
