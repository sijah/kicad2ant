"""kicad2ant KiCad plugin: simulate the antenna of the open board in openEMS from a toolbar button.

It fills the zones, saves a copy of the board as it is on screen into the run folder and runs scripts/kicad2ant.py
on that copy (the user's .kicad_pcb / .kicad_pro are never written). Progress comes from openEMS's own log file."""
import json, os, subprocess, sys, threading, time

import pcbnew
import wx

try:
    from . import core
except ImportError:   # loaded as a plain module (development)
    import core

PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
SETTINGS = os.path.join(os.path.expanduser('~'), '.kicad2ant_plugin.json')
DEFAULTS = {'mode': 1, 'f0': '2440', 'lo': '', 'hi': '', 'octave': '', 'openems': '', 'theme': 0, 'size': None, 'outdir': '', 'view': False}
MODES = [('Check model (seconds)', 'dry'), ('Coarse (minutes)', 'coarse'), ('Fine (much longer)', 'fine')]
AUTO = 'Auto: the AE* / ANT* / antenna footprint, pad 1'
GOOD = 'Good: the -10 dB band covers your target band.'
THEMES = ['System', 'Light', 'Dark']
COLOURS = {1: ((245, 245, 245), (20, 20, 20), (255, 255, 255)), 2: ((32, 32, 32), (225, 225, 225), (48, 48, 48))}   # window, text, field
NOT_NAMED = '  (not named AE* / ANT*: check it is the antenna, not a matching part)'
TITLE = 'kicad2ant'
_dialog = None


def script_path():
    installed = os.path.join(PLUGIN_DIR, 'scripts', 'kicad2ant.py')
    return installed if os.path.isfile(installed) else \
        os.path.normpath(os.path.join(PLUGIN_DIR, '..', '..', 'scripts', 'kicad2ant.py'))


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS, encoding='utf-8') as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    try:
        with open(SETTINGS, 'w', encoding='utf-8') as f:
            json.dump(s, f)
    except OSError:
        pass


def selected_feed():
    """(ref, pad number, whether the footprint is named like an antenna) of the selected pad, or of pad 1 of a
    selected footprint; None when nothing is selected. Any footprint is taken: people name antennas E1, A1, X1."""
    board = pcbnew.GetBoard()
    hit = None
    for fp in board.GetFootprints():
        if fp.IsSelected():   # KiCad marks a selected footprint's pads as selected too, so ask the footprint first
            hit = (fp, '1')
            break
        pad = next((p for p in fp.Pads() if p.IsSelected()), None)
        if pad is not None:
            hit = (fp, pad.GetNumber())
            break
    if hit is None:
        return None
    fp, num = hit
    ref = fp.GetReference()
    return ref, num, core.is_antenna_ref(ref, fp.GetFPIDAsString())


def child_env(python, octave, openems=''):
    env = dict(os.environ, PYTHONUNBUFFERED='1')
    kicad_dirs = {os.path.normcase(os.path.dirname(sys.executable)), os.path.normcase(sys.prefix)}
    if not any(os.path.normcase(python).startswith(d) for d in kicad_dirs):
        env.pop('PYTHONHOME', None)   # KiCad's settings would break another Python
        env.pop('PYTHONPATH', None)
    if octave:
        env['OCTAVE'] = octave
    if openems:
        env['OPENEMS'] = openems
    return env


class Kicad2antDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=TITLE + ': antenna simulation', style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
        s = load_settings()
        self.proc = None
        self.out = ''
        self.mode = 'coarse'
        self.feed = None
        self.started = 0.0
        self.log_pos = 0
        self.log_rest = ''
        self.best = 0.0
        self.stopped = False
        self.failed = False
        self.summary_text = ''

        self.mode_ctl = wx.Choice(self, choices=[m[0] for m in MODES])
        self.mode_ctl.SetSelection(s['mode'] if s['mode'] in (0, 1, 2) else 1)
        self.mode_ctl.SetToolTip('Check model: builds the model and draws it, no simulation. Run it first.\n'
                                 'Coarse: for tuning. Fine: for the numbers you quote.')
        self.f0 = wx.TextCtrl(self, value=s['f0'], size=(70, -1))
        self.lo = wx.TextCtrl(self, value=s['lo'], size=(70, -1))
        self.hi = wx.TextCtrl(self, value=s['hi'], size=(70, -1))
        for c in (self.lo, self.hi):
            c.SetToolTip('Target band in MHz. Leave empty: 2400 to 2483.5 at 2440 MHz, else f0 +/- 2 %.')
        self.gnd = wx.TextCtrl(self, size=(90, -1))
        self.gnd.SetToolTip('The ground net of this board. Leave empty: the net of the antenna\'s pad 2, else GND, '
                            'else the largest zone net with a ground name (AGND, GNDA, VSS ...).')
        self.theme_ctl = wx.Choice(self, choices=THEMES)
        self.theme_ctl.SetSelection(s['theme'] if s['theme'] in (0, 1, 2) else 0)
        self.theme_ctl.Bind(wx.EVT_CHOICE, lambda e: self.apply_theme())
        grid = wx.FlexGridSizer(0, 6, 6, 8)
        for label, ctl in (('Mode', self.mode_ctl), ('f0 (MHz)', self.f0), ('Ground net', self.gnd),
                           ('Band from (MHz)', self.lo), ('to (MHz)', self.hi), ('Theme', self.theme_ctl)):
            grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(ctl, 0, wx.ALIGN_CENTER_VERTICAL)

        self.feed_txt = wx.StaticText(self, label=AUTO)
        use_sel = wx.Button(self, label='Use selected pad')
        use_sel.SetToolTip('Click the feed pad of the antenna in the PCB editor (this window stays open), then press this.')
        use_sel.Bind(wx.EVT_BUTTON, self.on_use_selected)
        auto = wx.Button(self, label='Auto')
        auto.Bind(wx.EVT_BUTTON, lambda e: self.set_feed(None))
        feed_row = wx.BoxSizer(wx.HORIZONTAL)
        feed_row.Add(wx.StaticText(self, label='Feed:'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        feed_row.Add(self.feed_txt, 1, wx.ALIGN_CENTER_VERTICAL)
        feed_row.Add(use_sel, 0, wx.LEFT, 6)
        feed_row.Add(auto, 0, wx.LEFT, 4)

        self.octave = wx.TextCtrl(self, value=s['octave'])
        self.octave.SetToolTip('Leave empty to find Octave by itself. Set it if the run says Octave was not found.')
        browse = wx.Button(self, label='...', size=(30, -1))
        browse.Bind(wx.EVT_BUTTON, self.on_browse)
        oct_row = wx.BoxSizer(wx.HORIZONTAL)
        oct_row.Add(wx.StaticText(self, label='Octave (optional):'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        oct_row.Add(self.octave, 1)
        oct_row.Add(browse, 0, wx.LEFT, 4)

        self.openems = wx.TextCtrl(self, value=s['openems'])
        self.openems.SetToolTip('The openEMS folder, no spaces in the path: the one holding openEMS.exe and matlab on '
                                'Windows, the install prefix (e.g. ~/opt/openEMS) on Linux and macOS. '
                                'Leave empty to find openEMS by itself.')
        browse_ems = wx.Button(self, label='...', size=(30, -1))
        browse_ems.Bind(wx.EVT_BUTTON, self.on_browse_openems)
        ems_row = wx.BoxSizer(wx.HORIZONTAL)
        ems_row.Add(wx.StaticText(self, label='openEMS folder (optional):'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        ems_row.Add(self.openems, 1)
        ems_row.Add(browse_ems, 0, wx.LEFT, 4)

        self.outdir = wx.TextCtrl(self, value=s['outdir'])
        self.outdir.SetToolTip('Where the run folder <board>_kicad2ant is made. Leave empty: next to the board file. '
                               'A place with a space in its path cannot be used (openEMS): a folder in your '
                               'local app data is used then.')
        browse_out = wx.Button(self, label='...', size=(30, -1))
        browse_out.Bind(wx.EVT_BUTTON, self.on_browse_outdir)
        out_row = wx.BoxSizer(wx.HORIZONTAL)
        out_row.Add(wx.StaticText(self, label='Output in (optional):'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        out_row.Add(self.outdir, 1)
        out_row.Add(browse_out, 0, wx.LEFT, 4)

        self.view = wx.CheckBox(self, label="Show the 3D model in openEMS's viewer (AppCSXCAD) when the run ends")
        self.view.SetValue(bool(s['view']))
        self.view.SetToolTip('The model exactly as openEMS gets it: copper, board, port and mesh lines. '
                             'With Check model it opens in seconds.')

        note = wx.StaticText(self, label='Simulate fills the zones (like pressing B) and runs on a copy of the board as '
                                         'it is on screen. Your board file is not changed.')
        note.Wrap(560)

        self.run_btn = wx.Button(self, label='Simulate')
        self.run_btn.Bind(wx.EVT_BUTTON, self.on_run)
        self.stop_btn = wx.Button(self, label='Stop')
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        self.stop_btn.Disable()
        self.folder_btn = wx.Button(self, label='Open results folder')
        self.folder_btn.Bind(wx.EVT_BUTTON, lambda e: core.open_folder(os.path.join(self.out, 'results')))
        self.folder_btn.Disable()
        self.run_dir_btn = wx.Button(self, label='Open run folder')
        self.run_dir_btn.SetToolTip('The board copy, antenna_geom.m (the model Octave reads) and the sim_* folders.')
        self.run_dir_btn.Bind(wx.EVT_BUTTON, lambda e: core.open_folder(self.out))
        self.run_dir_btn.Disable()
        close = wx.Button(self, wx.ID_CLOSE, 'Close')
        close.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for b in (self.run_btn, self.stop_btn, self.folder_btn, self.run_dir_btn):
            buttons.Add(b, 0, wx.RIGHT, 6)
        buttons.AddStretchSpacer()
        buttons.Add(close)

        self.phase = wx.StaticText(self, label='')
        self.gauge = wx.Gauge(self, range=1000, size=(-1, 18))
        self.elapsed = wx.StaticText(self, label='')
        self.summary = wx.StaticText(self, label='')
        self.picture = wx.StaticBitmap(self)
        self.log = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 140))   # wraps: long lines stay readable
        self.log.SetFont(wx.Font(8, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(grid, 0, wx.ALL, 10)
        root.Add(feed_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(oct_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(ems_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(out_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(self.view, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(self.phase, 0, wx.LEFT | wx.RIGHT, 10)
        root.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        root.Add(self.elapsed, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(self.summary, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(self.picture, 0, wx.ALIGN_CENTER | wx.LEFT | wx.RIGHT, 10)
        root.Add(self.log, 1, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(root)
        self.SetMinSize((600, -1))
        self.Fit()
        if s['size']:
            self.SetSize(s['size'])
        self.apply_theme()

        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_tick, self.timer)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)
        self.show_previous()

    # ------------------------------------------------------------------ feed and settings

    def settings(self):
        return {'mode': self.mode_ctl.GetSelection(), 'f0': self.f0.GetValue().strip(), 'lo': self.lo.GetValue().strip(),
                'hi': self.hi.GetValue().strip(), 'octave': self.octave.GetValue().strip(),
                'openems': self.openems.GetValue().strip(), 'theme': self.theme_ctl.GetSelection(),
                'outdir': self.outdir.GetValue().strip(), 'view': self.view.GetValue(),
                'size': None if self.IsMaximized() else list(self.GetSize())}

    def apply_theme(self):
        """System leaves every colour to KiCad / the OS; Light and Dark set them on the window and its controls."""
        theme = self.theme_ctl.GetSelection()
        bg, fg, field = (wx.Colour(*c) for c in COLOURS[theme]) if theme else (wx.NullColour,) * 3
        dark = theme == 2 or (theme == 0 and wx.SystemSettings.GetAppearance().IsDark())
        for w in [self] + list(self.GetChildren()):
            w.SetBackgroundColour(field if isinstance(w, (wx.TextCtrl, wx.Choice, wx.Button)) else bg)
            w.SetForegroundColour(fg)
        if self.failed:
            self.summary.SetForegroundColour(wx.Colour(240, 90, 90) if dark else wx.Colour(170, 20, 20))
        self.Refresh()

    def set_summary(self, text, failed=False):
        self.summary_text, self.failed = text, failed
        self.apply_theme()
        self.wrap_summary()

    def wrap_summary(self):   # Wrap() puts line breaks into the label, so start again from the text
        self.summary.SetLabel(self.summary_text)
        self.summary.Wrap(-1)   # wx 3.3 skips a Wrap() to the width it already has, even after a new label
        self.summary.Wrap(max(560, self.GetClientSize().width - 20))

    def on_size(self, event):
        self.wrap_summary()
        event.Skip()

    def grow(self):
        """Makes room for a result; never shrinks the size the user gave the window."""
        self.Layout()
        (w, h), (bw, bh) = self.GetSize(), self.GetBestSize()
        if not self.IsMaximized():
            self.SetSize(max(w, bw), max(h, bh))

    def set_feed(self, feed, named=True):
        self.feed = feed
        self.feed_board = pcbnew.GetBoard().GetFileName()   # the pick belongs to this board only
        self.feed_txt.SetLabel(AUTO if feed is None else '%s pad %s' % feed + ('' if named else NOT_NAMED))
        self.Layout()

    def on_use_selected(self, _):
        hit = selected_feed()
        if hit is None:
            wx.MessageBox('Nothing is selected. Click the feed pad of the antenna in the PCB editor first.', TITLE)
        else:
            self.set_feed(hit[:2], hit[2])

    def on_browse(self, _):
        with wx.FileDialog(self, 'Octave program (octave-gui.exe or octave)') as d:
            if d.ShowModal() == wx.ID_OK:
                self.octave.SetValue(d.GetPath())

    def on_browse_openems(self, _):
        with wx.DirDialog(self, 'openEMS folder (the one with openEMS.exe and matlab)') as d:
            if d.ShowModal() == wx.ID_OK:
                self.openems.SetValue(d.GetPath())

    def on_browse_outdir(self, _):
        with wx.DirDialog(self, 'Folder to make the run folder in') as d:
            if d.ShowModal() == wx.ID_OK:
                self.outdir.SetValue(d.GetPath())

    def run_folder(self):
        return core.run_dir(pcbnew.GetBoard().GetFileName(), base=self.outdir.GetValue().strip())

    def show_previous(self):
        """Shows the newest earlier result of this board for the chosen mode."""
        try:
            out = self.run_folder()
        except ValueError:
            return
        mode = MODES[self.mode_ctl.GetSelection()][1]
        res = core.find_result(out, mode, 0)
        if res:
            self.out = out
            self.show_result(mode, res, 'Last run:')

    # ------------------------------------------------------------------ run

    def on_run(self, _):
        if self.proc is not None:
            return
        mode = MODES[self.mode_ctl.GetSelection()][1]
        f0, lo, hi = (c.GetValue().strip() for c in (self.f0, self.lo, self.hi))
        try:
            if float(f0) <= 0 or bool(lo) != bool(hi) or (lo and float(lo) >= float(hi)):
                raise ValueError
        except ValueError:
            wx.MessageBox('f0 must be a frequency in MHz. The band needs both ends (from below to), or none.', TITLE)
            return
        python = core.find_python()
        if not python:
            wx.MessageBox('Python 3 was not found: install it from python.org.', TITLE, wx.ICON_WARNING)
            return
        board = pcbnew.GetBoard()
        try:
            out = self.run_folder()
        except ValueError:
            wx.MessageBox('Save the board once first.', TITLE)
            return
        os.makedirs(out, exist_ok=True)
        lock = os.path.join(out, '.running')
        try:
            with open(lock) as f:
                if core.pid_alive(int(f.read().strip() or 0), 'python'):
                    wx.MessageBox('Another simulation is using this board folder:\n' + out, TITLE)
                    return
        except (OSError, ValueError):
            pass
        save_settings(self.settings())

        self.phase.SetLabel('Filling zones and saving a copy of the board')
        wx.SafeYield()
        if not pcbnew.ZONE_FILLER(board).Fill(board.Zones()):
            self.add_log('warning: the zone fill reported a problem')
        pcbnew.Refresh()
        copy = os.path.join(out, 'board.kicad_pcb')
        pcbnew.SaveBoard(copy, board, True)   # True: leave the open project's settings where they are

        if self.feed and self.feed_board != board.GetFileName():   # another board was opened under this window
            self.set_feed(None)
        ref, num = self.feed if self.feed else ('auto', '')
        cmd = core.build_cmd(python, script_path(), copy, out, mode, ref, num, f0, (lo, hi), self.gnd.GetValue().strip(),
                             self.view.GetValue())
        self.out, self.mode, self.started = out, mode, time.time()
        self.log_pos, self.log_rest, self.best, self.stopped = 0, '', 0.0, False
        self.log.Clear()
        self.add_log(' '.join(cmd))
        self.set_summary('')
        self.picture.SetBitmap(wx.NullBitmap)
        self.gauge.SetValue(0)
        self.phase.SetLabel('Starting')
        kw = {'creationflags': core.NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                         encoding='utf-8', errors='replace', cwd=out,
                                         env=child_env(python, self.octave.GetValue().strip(),
                                                       self.openems.GetValue().strip()), **kw)
        except OSError as e:
            self.phase.SetLabel('')
            wx.MessageBox('Could not start the simulation: %s' % e, TITLE, wx.ICON_WARNING)
            return
        with open(lock, 'w') as f:
            f.write(str(self.proc.pid))
        self.run_btn.Disable()
        self.stop_btn.Enable()
        self.run_dir_btn.Enable()   # the folder exists now: watch antenna_geom.m appear
        self.timer.Start(1000)
        threading.Thread(target=self.reader, args=(self.proc, lock), daemon=True).start()

    def reader(self, proc, lock):
        for line in proc.stdout:
            wx.CallAfter(self.add_log, line.rstrip())
        code = proc.wait()
        try:   # here, not in finished(): the dialog may be gone by now
            os.remove(lock)
        except OSError:
            pass
        wx.CallAfter(self.finished, code)

    def add_log(self, line):
        if not self:   # the dialog is gone
            return
        self.log.AppendText(line + '\n')
        ph = core.phase(line)
        if ph:
            self.phase.SetLabel(ph)

    def on_tick(self, _):
        if not self:
            return
        secs = int(time.time() - self.started)
        self.elapsed.SetLabel('%d:%02d elapsed' % (secs // 60, secs % 60))
        log = os.path.join(self.out, 'sim_' + ('coarse' if self.mode == 'dry' else self.mode), 'openEMS.log')
        try:   # a log older than this run is the previous run's
            if os.path.getmtime(log) < self.started:
                return
            if os.path.getsize(log) < self.log_pos:   # the folder was cleared and the log restarted
                self.log_pos, self.log_rest = 0, ''
            with open(log, 'rb') as f:
                f.seek(self.log_pos)
                data = f.read()
            self.log_pos += len(data)
        except OSError:
            return
        lines = (self.log_rest + data.decode('utf-8', 'replace')).split('\n')
        self.log_rest = lines.pop()
        target = core.TARGET_DB.get(self.mode)
        for line in lines:
            p = core.progress(line, target)
            if p is not None:
                self.best = max(self.best, p)
                self.gauge.SetValue(int(self.best * 1000))
                self.phase.SetLabel('Simulating %d %%' % int(self.best * 100))
            else:
                ph = core.phase(line)
                if ph:
                    self.phase.SetLabel(ph)

    def finished(self, code):
        if not self:
            return
        self.timer.Stop()
        self.proc = None
        self.run_btn.Enable()
        self.stop_btn.Disable()
        res = core.find_result(self.out, self.mode, self.started)
        if code == 0 and res:
            self.gauge.SetValue(1000)
            self.phase.SetLabel('Done')
            self.show_result(self.mode, res, '')
        else:
            self.phase.SetLabel('Stopped' if self.stopped else 'Failed')
            self.set_summary('Stopped.' if self.stopped else
                             (core.failure_line(self.log.GetValue().splitlines()) or 'Failed: see the log below.'), True)
        self.folder_btn.Enable(os.path.isdir(os.path.join(self.out, 'results')))
        self.run_dir_btn.Enable(os.path.isdir(self.out))
        self.grow()

    def show_result(self, mode, res, title):
        summary, name = res
        lines = core.summary_lines(summary) if summary else ['Model built: check the picture (ground grey, '
                                                             'antenna orange, port magenta on the feed pad).']
        if core.band_covered(lines):
            lines.append(GOOD)
        self.set_summary('\n'.join(([title] if title else []) + lines))
        pic = os.path.join(self.out, 'results', name + ('_geometry.png' if mode == 'dry' else '_%s_s11_zin.png' % mode))
        if os.path.isfile(pic):
            img = wx.Image(pic)
            if img.IsOk() and img.GetWidth() > 560:
                img.Rescale(560, int(img.GetHeight() * 560 / img.GetWidth()), wx.IMAGE_QUALITY_HIGH)
            self.picture.SetBitmap(wx.Bitmap(img))
        self.folder_btn.Enable()
        self.run_dir_btn.Enable()
        self.grow()

    # ------------------------------------------------------------------ stop and close

    def stop_run(self):
        if self.proc is not None:
            self.stopped = True
            core.kill_tree(self.proc)

    def on_stop(self, _):
        self.stop_run()

    def on_close(self, _):
        save_settings(self.settings())   # keeps the theme and the window size
        self.Destroy()

    def on_destroy(self, event):
        """Also runs when KiCad destroys the dialog with the PCB editor (no EVT_CLOSE then): end the run."""
        global _dialog
        if event.GetEventObject() is self:
            self.timer.Stop()
            self.stop_run()
            _dialog = None
        event.Skip()


class Kicad2antPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = 'kicad2ant: antenna simulation'
        self.category = 'Simulation'
        self.description = 'Simulate the PCB antenna of this board in openEMS (S11, band, gain, pattern)'
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(PLUGIN_DIR, 'icon.png')
        self.dark_icon_file_name = self.icon_file_name

    def Run(self):
        global _dialog
        if not pcbnew.GetBoard().GetFileName():
            wx.MessageBox('Save the board once first.', TITLE)
            return
        if _dialog:
            _dialog.Raise()
            return
        _dialog = Kicad2antDialog(wx.FindWindowByName('PcbFrame'))
        _dialog.Show()   # not modal: the feed pad can be clicked in the editor meanwhile


Kicad2antPlugin().register()
