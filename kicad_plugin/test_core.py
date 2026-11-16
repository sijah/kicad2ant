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
    assert core.run_dir("D:/x/ifa.kicad_pcb", {}, "E:/sim").replace('\\', '/') == "E:/sim/ifa_kicad2ant"   # the chosen place
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


def test_case():
    assert core.case_args(['3.0', '0.01', '2', '1', '0', '1.5']) == ['3', '0.01', '2', '1', '0', '1.5']
    for bad in (['0.5', '0', '2', '1', '1', '1'], ['3', '0', '0', '1', '1', '1'], ['3', '0', '2', '-1', '1', '1'],
                ['3', '0', '2', '1', '1'], ['3', 'x', '2', '1', '1', '1'], ['nan', '0', '2', '1', '1', '1']):
        try:
            core.case_args(bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    assert core.build_cmd('py', 'k.py', 'b', 'o', 'fast', case=['3', '0.01', '2', '1', '1', '1'])[-7:] ==         ['--case', '3', '0.01', '2', '1', '1', '1']
    assert '--case' not in core.build_cmd('py', 'k.py', 'b', 'o', 'fast')


def test_time_left():
    line = "[@       12s] Timestep:         8056 || Speed:  164.9 MC/s (1.304e-03 s/TS) || Energy: ~1.42e-17 (-24.73dB)"
    assert core.energy(line) == (12, 24.73) and core.energy('Create FDTD operator') is None
    assert core.energy(line.replace('[@       12s]', '[@     1m05s]'))[0] == 65   # openEMS's form after a minute
    assert core.energy(line.replace('[@       12s]', '[@  1h02m03s]'))[0] == 3723
    assert core.time_left([(4, 0.0), (8, 10.0), (12, 20.0), (16, 30.0)], 40) == 4.0   # 2.5 dB/s, 10 dB to go
    assert core.time_left([(4, 0.0), (8, 10.0)], 40) is None                         # too early to tell
    assert core.time_left([(8, 10.0), (12, 9.0), (16, 8.0)], 40) is None             # not falling


def test_default_band():
    assert core.default_band('2440') == (2400.0, 2483.5) and core.default_band('900') == (882.0, 918.0)
    assert core.default_band('') is None and core.default_band('x') is None


def test_hover():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, 'results'))
    with open(os.path.join(d, 'results', 'A_fast.s1p'), 'w') as fh:   # S = 0 at 2400, 1/3 at 2500 MHz
        fh.write('! sim\n# Hz S RI R 50\n2400000000 0 0\n2500000000 0.333333 0\n')
    with open(os.path.join(d, 'm.s1p'), 'w') as fh:                    # MHz / DB form
        fh.write('# MHZ S DB R 50\n2450 -20 180\n2460 -20 180\n')
    with open(os.path.join(d, 'results', 'A_fast_s11_zin.txt'), 'w') as fh:
        fh.write('box 0.1 0.9 0.1 0.9\nxlim 2400 2500\ntrace 0 0 0 simulation\tresults/A_fast.s1p\n'
                 'trace 0 0.6 0 m\tm.s1p\ntrace 1 0 0 gone\tmissing.s1p\n')
    info = core.hover_plot(os.path.join(d, 'results', 'A_fast_s11_zin.txt'), d)
    assert [t[0] for t in info['traces']] == ['simulation', 'm']               # the missing file is left out
    assert core.hover_freq(info, 0.5, 0.5) == 2450 and core.hover_freq(info, 0.05, 0.5) is None
    assert abs(core.s_at(*info['traces'][0][2:4], 2450e6) - 1 / 6) < 1e-6 and core.s_at([1, 2], [0, 0], 3) is None
    lines = core.hover_lines(info, 2500)
    assert lines[0] == ('2500.0 MHz', None) and lines[1][0] == 'simulation: -9.5 dB  VSWR 2.00  Zin 100.0 +0.0j'
    assert lines[2][0] == 'm: no data here'
    f, s, z0 = core.read_s1p(os.path.join(d, 'm.s1p'))
    assert f == [2450e6, 2460e6] and abs(s[0] - (-0.1)) < 1e-9 and z0 == 50
    assert core.readout(1.0).endswith('(no match)')
    assert core.hover_plot(os.path.join(d, 'nothing.txt'), d) is None


def test_auto_pick():
    assert core.auto_pick([('ANT**', 'MyLib:IFA'), ('R1', 'Resistor_SMD:R_0402')]) == ('ANT**', None)
    assert core.auto_pick([('E1', 'RF_Antenna:Johanson_2450AT18')]) == ('E1', None)
    assert core.auto_pick([('R1', 'R')])[0] is None and 'no AE*' in core.auto_pick([('R1', 'R')])[1]
    assert core.auto_pick([('AE1', ''), ('AE2', '')]) == (None, 'several: AE1, AE2')


def test_describe_sets():
    assert core.describe_sets(['pattern=0', 'cell=0.2']) == 'pattern off, cell 0.2'
    assert core.describe_sets([]) == ''


def test_auto_sweep():
    assert core.auto_sweep('2440') == (1464.0, 3416.0)
    assert core.auto_sweep('868') == (520.8, 1215.2)
    assert core.auto_sweep('') is None and core.auto_sweep('x') is None and core.auto_sweep('-5') is None
    d = {'f_start': 1464.0, 'f_stop': 3416.0}   # the shown default sweep sends no --set
    assert core.sim_sets({'f_start': '1464', 'f_stop': '3416'}, d) == []
    assert core.sim_sets({'f_start': '2000', 'f_stop': '3416'}, d) == ['f_start=2000']


def test_sim_sets():
    d = {'cell': 0.5, 'end_db': -30.0, 'pattern': 0}
    assert core.sim_sets({'cell': '0.5', 'end_db': '-40', 'pattern': '1'}, d) == ['end_db=-40', 'pattern=1']
    assert core.sim_sets({'cell': '0.50', 'end_db': '-30', 'pattern': '0'}, d) == []
    assert core.build_cmd('py', 'k.py', 'b', 'o', 'fast', sets=['cell=0.2'], view=True)[-3:] == ['--set', 'cell=0.2', '--view']


def test_summary_lines_real():
    assert core.summary_lines(REAL) == [
        "board: 1.6 mm, 2 copper layers, FR4 epsR 4.5, tanD 0.02 (KiCad's default stackup: check it in Board Setup > Physical Stackup)",
        'case: none, the board in air',
        'resonance (min S11) -5.3 dB at 2416 MHz', 'no -10 dB band',
        'at 2440 MHz: S11 -4.1 dB, Zin 20.0 +40.5j ohm',
        'run: converged in 60516 steps; mesh worst neighbour ratio 1.50']


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


def test_mode_key_legacy_index():
    assert [core.mode_key(i) for i in (0, 1, 2)] == ['dry', 'coarse', 'fine']   # 0.1.0 saved the list index
    assert core.mode_key('fast') == 'fast' and core.mode_key(7) == 'fast' and core.mode_key(None) == 'fast'
    assert core.mode_key('bogus') == 'fast' and core.mode_key(True) == 'fast'


def test_fast_target_and_cmd():
    assert core.TARGET_DB['fast'] == 30.0
    assert core.build_cmd('py', 'k.py', 'b', 'o', 'fast')[4:6] == ['--mode', 'fast']
    assert [m for m, _ in core.MODES] == ['dry', 'fast', 'coarse', 'fine'] and all(h for _, h in core.MODES)


def test_summary_fast():
    p = os.path.join(tempfile.mkdtemp(), 'AE1_fast_summary.txt')
    write(p, 'AE1 fast run (17 s)\nboard: 2 copper layers, 1.510 mm, epsR [4.5]; ground GND; port in-plane\n'
             'fast (S11 only, no far field): confirm with coarse\n'
             'resonance (min S11) -21.1 dB at 2408 MHz\nrun: converged in 7344 steps; mesh worst neighbour ratio 4.07\n')
    lines = core.summary_lines(p)
    assert lines[0].startswith('fast (S11 only') and lines[1].startswith('resonance') and len(lines) == 3
    write(p, 'AE1 fast run (17 s)\nboard: 0.8 mm, 2 copper layers, FR4 epsR 4.4, tanD 0.02\nmodel: ground GND\n'
             'resonance (min S11) -21.1 dB at 2408 MHz\n')
    assert core.summary_lines(p) == ['board: 0.8 mm, 2 copper layers, FR4 epsR 4.4, tanD 0.02',
                                     'resonance (min S11) -21.1 dB at 2408 MHz']


def test_lock_refuses_live_pid():
    t = tempfile.mkdtemp()
    assert core.take_lock(t, os.getpid()) is None and core.take_lock(t, os.getpid()) is None   # ours: taken again
    assert core.take_lock(t, 999999) == os.getpid() == core.lock_holder(t)   # held by a live python (this test)


def test_lock_takes_stale():
    t = tempfile.mkdtemp()
    write(os.path.join(t, '.running'), '999999')
    assert core.lock_holder(t) is None and core.take_lock(t, os.getpid()) is None
    core.release_lock(t, 12345)
    assert os.path.exists(os.path.join(t, '.running'))   # not ours: kept
    core.release_lock(t, os.getpid())
    assert not os.path.exists(os.path.join(t, '.running'))


def test_result_pictures():
    t = tempfile.mkdtemp(); r = os.path.join(t, 'results'); os.makedirs(r)
    for f in ('AE1_fast_s11_zin.png', 'AE1_fast_smith.png', 'AE1_geometry.png', 'AE1_coarse_pattern.png'):
        write(os.path.join(r, f), 'x')
    got = core.result_pictures(t, 'AE1', 'fast')
    assert [l for l, _ in got] == ['S11 / Zin', 'Smith', 'Model'], got
    assert got[0][1] == os.path.join(r, 'AE1_fast_s11_zin.png')
    assert [l for l, _ in core.result_pictures(t, 'AE1', 'dry')] == ['Model']


def test_fit():
    assert core.fit(1200, 900, 600, 600) == (600, 450)
    assert core.fit(400, 300, 600, 600) == (400, 300)   # never enlarged


def test_board_line():
    two = ('(kicad_pcb (general (thickness 0.8)) (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (5 "F.SilkS" user))\n'
           ' (setup (stackup (layer "F.Mask" (type "Top Solder Mask") (thickness 0.01)) (layer "F.Cu" (type "copper") (thickness 0.035))\n'
           '  (layer "dielectric 1" (type "core") (thickness 0.4) (material "FR4") (epsilon_r 4.4) (loss_tangent 0.02)\n'
           '   addsublayer (thickness 0.3) (material "FR4") (epsilon_r 4.2) (loss_tangent 0.02))\n'
           '  (layer "B.Cu" (type "copper") (thickness 0.035)) (copper_finish "None"))))')
    i = core.board_stack(two)
    assert i['thick'] == 0.8 and i['ncu'] == 2 and i['stackup'] and not i['default'] and abs(i['diel'][0][0] - 0.7) < 1e-9
    assert core.board_line(i) == '0.8 mm, 2 copper layers, FR4 εr 4.2-4.4, tanδ 0.02'
    assert core.board_line(i, short=True, uni=False) == '0.8 mm FR4 epsR 4.2-4.4'
    bare = core.board_stack('(kicad_pcb (general (thickness 1.6)) (layers (0 "F.Cu" signal) (2 "B.Cu" signal)))')
    assert core.board_line(bare).endswith('(no stackup set, assumed: set it in Board Setup > Physical Stackup)')
    assert core.board_line(bare).startswith('1.6 mm, 2 copper layers, εr 4.5, tanδ 0.02')
    dflt = core.board_stack(two.replace('(thickness 0.4)', '(thickness 1.51)').replace('(epsilon_r 4.4)', '(epsilon_r 4.5)')
                            .replace('   addsublayer (thickness 0.3) (material "FR4") (epsilon_r 4.2) (loss_tangent 0.02)', ''))
    assert dflt['default'] and "KiCad's default stackup" in core.board_line(dflt)
    assert core.board_file_line('nope.kicad_pcb') == ''


def test_bands():
    assert core.BANDS[core.band_preset('2440', '', '')][0].startswith('2.4 GHz')
    assert core.BANDS[core.band_preset('868', '863', '870')][4] == -6
    assert core.default_band('868') == (863.0, 870.0) and core.default_band('1000') == (980.0, 1020.0)
    assert core.default_band('2445') == (2400.0, 2483.5) and core.default_band('x') is None
    assert core.band_preset('1000', '', '') is None and core.band_preset('x', '', '') is None
    assert all(lo < f0 < hi and m in core.MATCHES for _, f0, lo, hi, m in core.BANDS)
    assert '75 mm' not in core.low_freq_note('868') and '86 mm' in core.low_freq_note('868')
    assert core.low_freq_note('2440') == '' and core.low_freq_note('') == ''
    assert core.build_cmd('py', 'k.py', 'b', 'o', 'fast', match=-6)[8:10] == ['--match', '-6']
    assert '--match' not in core.build_cmd('py', 'k.py', 'b', 'o', 'fast')
    assert core.band_covered(['S11 < -6 dB: 860 .. 875 MHz, covers the 863.0..870.0 MHz target'])

if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
    print('OK')
