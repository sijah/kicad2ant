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
DEFAULTS = {'mode': 'fast', 'f0': '2440', 'lo': '', 'hi': '', 'octave': '', 'openems': '', 'theme': 0, 'size': None, 'outdir': '', 'view': False,
            'case': False, 'case_vals': [d for _, d in core.CASE_FIELDS], 'sim_sets': []}
LABELS = {'dry': 'Check model (seconds)', 'fast': 'Fast: S11 only (about a minute)',
          'coarse': 'Coarse: S11, gain, pattern (minutes)', 'fine': 'Fine: final numbers (much longer)'}
MODES = [(LABELS[m], m) for m, _ in core.MODES]   # (label, mode) in list order
HELP = dict(core.MODES)
AUTO = 'Auto: the AE* / ANT* / antenna footprint, pad 1'
GOOD = 'Good: the -10 dB band covers your target band.'
THEMES = ['System', 'Light', 'Dark']
COLOURS = {1: ((245, 245, 245), (20, 20, 20), (255, 255, 255)), 2: ((32, 32, 32), (225, 225, 225), (48, 48, 48))}   # window, text, field
NOT_NAMED = '  (not named AE* / ANT*: check it is the antenna, not a matching part)'
TITLE = 'kicad2ant'
VERSION = '0.3.1'   # build_pcm.py checks it against metadata.json
LOGO = os.path.join(PLUGIN_DIR, 'icon64.png')
if not os.path.isfile(LOGO):   # running from the repo
    LOGO = os.path.join(PLUGIN_DIR, '..', 'icon64.png')
_dialog = None


def script_path():
    installed = os.path.join(PLUGIN_DIR, 'scripts', 'kicad2ant.py')
    return installed if os.path.isfile(installed) else \
        os.path.normpath(os.path.join(PLUGIN_DIR, '..', '..', 'scripts', 'kicad2ant.py'))


sys.path.insert(0, os.path.dirname(script_path()))
import mesher  # noqa: E402  the run settings of each mode, for the Simulation tab


def mode_values(mode):
    return mesher.MODES['coarse' if mode == 'dry' else mode]


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
        super().__init__(parent, title='%s %s: antenna simulation' % (TITLE, VERSION),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
        logo = wx.Image(LOGO) if os.path.isfile(LOGO) else None
        header = wx.BoxSizer(wx.HORIZONTAL)
        if logo is not None and logo.IsOk():
            self.SetIcon(wx.Icon(wx.Bitmap(logo)))
            header.Add(wx.StaticBitmap(self, bitmap=wx.Bitmap(logo.Scale(40, 40, wx.IMAGE_QUALITY_HIGH))), 0, wx.RIGHT, 10)
        name = wx.StaticText(self, label=TITLE)
        name.SetFont(name.GetFont().Scaled(1.6).Bold())
        about = wx.BoxSizer(wx.VERTICAL)
        about.Add(name)
        about.Add(wx.StaticText(self, label='version %s  ·  PCB antenna simulation in openEMS' % VERSION))
        header.Add(about, 0, wx.ALIGN_CENTER_VERTICAL)
        s = load_settings()
        self.proc = None
        self.out = ''
        self.mode = 'fast'
        self.target = None
        self.feed = None
        self.started = 0.0
        self.log_pos = 0
        self.log_rest = ''
        self.best = 0.0
        self.stopped = False
        self.failed = False
        self.summary_text = ''
        self.img = None   # the full-size wx.Image of the plot on the Results page
        self.pics = []

        self.book = wx.Notebook(self)
        run = wx.Panel(self.book)
        sim = wx.ScrolledWindow(self.book)
        resp = wx.Panel(self.book)
        self.book.AddPage(run, 'Run')
        self.book.AddPage(sim, 'Simulation')
        self.book.AddPage(resp, 'Results')

        self.mode_ctl = wx.Choice(run, choices=[m[0] for m in MODES])
        self.mode_ctl.SetSelection([m for _, m in MODES].index(core.mode_key(s['mode'])))
        self.mode_ctl.SetToolTip('\n'.join('%s: %s' % (label.split(':')[0].split(' (')[0], HELP[m]) for label, m in MODES))
        self.mode_help = wx.StaticText(run, label='')   # what the chosen mode does, in one line
        self.mode_ctl.Bind(wx.EVT_CHOICE, lambda e: (self.mode_help.SetLabel(HELP[MODES[self.mode_ctl.GetSelection()][1]]),
                                                     self.fill_sim()))
        self.mode_help.SetLabel(HELP[MODES[self.mode_ctl.GetSelection()][1]])
        self.f0 = wx.TextCtrl(run, value=s['f0'], size=(70, -1))
        self.lo = wx.TextCtrl(run, value=s['lo'], size=(70, -1))
        self.hi = wx.TextCtrl(run, value=s['hi'], size=(70, -1))
        for c in (self.lo, self.hi):
            c.SetToolTip('Target band in MHz. Leave empty: 2400 to 2483.5 at 2440 MHz, else f0 +/- 2 %.')
        self.gnd = wx.TextCtrl(run, size=(90, -1))
        self.gnd.SetToolTip('The ground net of this board. Leave empty: the net of the antenna\'s pad 2, else GND, '
                            'else the largest zone net with a ground name (AGND, GNDA, VSS ...).')
        self.theme_ctl = wx.Choice(run, choices=THEMES)
        self.theme_ctl.SetSelection(s['theme'] if s['theme'] in (0, 1, 2) else 0)
        self.theme_ctl.Bind(wx.EVT_CHOICE, lambda e: self.apply_theme())
        grid = wx.FlexGridSizer(0, 6, 6, 8)
        for label, ctl in (('Mode', self.mode_ctl), ('f0 (MHz)', self.f0), ('Ground net', self.gnd),
                           ('Band from (MHz)', self.lo), ('to (MHz)', self.hi), ('Theme', self.theme_ctl)):
            grid.Add(wx.StaticText(run, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(ctl, 0, wx.ALIGN_CENTER_VERTICAL)

        self.feed_txt = wx.StaticText(run, label=AUTO)
        use_sel = wx.Button(run, label='Use selected pad')
        use_sel.SetToolTip('Click the feed pad of the antenna in the PCB editor (this window stays open), then press this.')
        use_sel.Bind(wx.EVT_BUTTON, self.on_use_selected)
        auto = wx.Button(run, label='Auto')
        auto.Bind(wx.EVT_BUTTON, lambda e: self.set_feed(None))
        feed_row = wx.BoxSizer(wx.HORIZONTAL)
        feed_row.Add(wx.StaticText(run, label='Feed:'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        feed_row.Add(self.feed_txt, 1, wx.ALIGN_CENTER_VERTICAL)
        feed_row.Add(use_sel, 0, wx.LEFT, 6)
        feed_row.Add(auto, 0, wx.LEFT, 4)

        self.case_ctl = wx.Choice(run, choices=['Air (bare board)', 'Plastic case'])
        self.case_ctl.SetSelection(1 if s['case'] else 0)
        self.case_ctl.SetToolTip('Plastic case: a box shell around the board, with the wall thickness and the gaps '
                                 'to the board at the sides, on top (F.Cu side) and below, in mm. '
                                 'ABS about 3.0 / 0.01, PC 2.9 / 0.01, nylon 3.2-3.8 / 0.02. Plastic lowers the resonance.')
        vals = s['case_vals'] if len(s['case_vals']) == 6 else [d for _, d in core.CASE_FIELDS]
        self.case_vals = [wx.TextCtrl(run, value=str(v), size=(45, -1)) for v in vals]
        case_row = wx.BoxSizer(wx.HORIZONTAL)
        case_row.Add(wx.StaticText(run, label='Around the board:'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        case_row.Add(self.case_ctl, 0, wx.RIGHT, 8)
        for (label, _), c in zip(core.CASE_FIELDS, self.case_vals):
            case_row.Add(wx.StaticText(run, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)
            case_row.Add(c, 0, wx.RIGHT, 6)
        case_row.Add(wx.StaticText(run, label='mm'), 0, wx.ALIGN_CENTER_VERTICAL)
        self.case_ctl.Bind(wx.EVT_CHOICE, lambda e: self.enable_case())
        self.enable_case()

        self.octave = wx.TextCtrl(run, value=s['octave'])
        self.octave.SetToolTip('Leave empty to find Octave by itself. Set it if the run says Octave was not found.')
        browse = wx.Button(run, label='...', size=(30, -1))
        browse.Bind(wx.EVT_BUTTON, self.on_browse)
        oct_row = wx.BoxSizer(wx.HORIZONTAL)
        oct_row.Add(wx.StaticText(run, label='Octave (optional):'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        oct_row.Add(self.octave, 1)
        oct_row.Add(browse, 0, wx.LEFT, 4)

        self.openems = wx.TextCtrl(run, value=s['openems'])
        self.openems.SetToolTip('The openEMS folder, no spaces in the path: the one holding openEMS.exe and matlab on '
                                'Windows, the install prefix (e.g. ~/opt/openEMS) on Linux and macOS. '
                                'Leave empty to find openEMS by itself.')
        browse_ems = wx.Button(run, label='...', size=(30, -1))
        browse_ems.Bind(wx.EVT_BUTTON, self.on_browse_openems)
        ems_row = wx.BoxSizer(wx.HORIZONTAL)
        ems_row.Add(wx.StaticText(run, label='openEMS folder (optional):'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        ems_row.Add(self.openems, 1)
        ems_row.Add(browse_ems, 0, wx.LEFT, 4)

        self.outdir = wx.TextCtrl(run, value=s['outdir'])
        self.outdir.SetToolTip('Where the run folder <board>_kicad2ant is made. Leave empty: next to the board file. '
                               'A place with a space in its path cannot be used (openEMS): a folder in your '
                               'local app data is used then.')
        browse_out = wx.Button(run, label='...', size=(30, -1))
        browse_out.Bind(wx.EVT_BUTTON, self.on_browse_outdir)
        out_row = wx.BoxSizer(wx.HORIZONTAL)
        out_row.Add(wx.StaticText(run, label='Output in (optional):'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        out_row.Add(self.outdir, 1)
        out_row.Add(browse_out, 0, wx.LEFT, 4)

        self.view = wx.CheckBox(run, label="Show the 3D model in openEMS's viewer (AppCSXCAD) when the run ends")
        self.view.SetValue(bool(s['view']))
        self.view.SetToolTip('The model exactly as openEMS gets it: copper, board, port and mesh lines. '
                             'With Check model it opens in seconds.')

        note = wx.StaticText(run, label='Simulate fills the zones (like pressing B) and runs on a copy of the board as '
                                         'it is on screen. Your board file is not changed.')
        note.Wrap(560)

        self.run_btn = wx.Button(run, label='Simulate')
        self.run_btn.Bind(wx.EVT_BUTTON, self.on_run)
        self.stop_btn = wx.Button(run, label='Stop')
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        self.stop_btn.Disable()
        self.folder_btn = wx.Button(run, label='Open results folder')
        self.folder_btn.Bind(wx.EVT_BUTTON, lambda e: core.open_folder(os.path.join(self.out, 'results')))
        self.folder_btn.Disable()
        self.run_dir_btn = wx.Button(run, label='Open run folder')
        self.run_dir_btn.SetToolTip('The board copy, antenna_geom.m (the model Octave reads) and the sim_* folders.')
        self.run_dir_btn.Bind(wx.EVT_BUTTON, lambda e: core.open_folder(self.out))
        self.run_dir_btn.Disable()
        close = wx.Button(run, wx.ID_CLOSE, 'Close')
        close.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for b in (self.run_btn, self.stop_btn, self.folder_btn, self.run_dir_btn):
            buttons.Add(b, 0, wx.RIGHT, 6)
        buttons.AddStretchSpacer()
        buttons.Add(close)

        self.phase = wx.StaticText(run, label='')
        self.gauge = wx.Gauge(run, range=1000, size=(-1, 18))
        self.elapsed = wx.StaticText(run, label='')
        self.summary = wx.StaticText(resp, label='')
        self.plot_ctl = wx.Choice(resp)
        self.plot_ctl.Bind(wx.EVT_CHOICE, lambda e: self.show_picture())
        self.picture = wx.Panel(resp)   # draws the plot scaled to its own size on every paint
        self.picture.SetMinSize((300, 200))
        self.picture.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.picture.SetToolTip('Click to open the picture full size.')
        self.picture.Bind(wx.EVT_LEFT_DOWN, lambda e: self.img and core.open_folder(self.pics[self.plot_ctl.GetSelection()][1]))
        self.picture.Bind(wx.EVT_PAINT, self.on_paint_picture)
        self.picture.Bind(wx.EVT_SIZE, lambda e: (self.picture.Refresh(), e.Skip()))
        self.scaled = None   # (size, wx.Bitmap) of the last drawing
        self.log = wx.TextCtrl(run, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 140))   # wraps: long lines stay readable
        self.log.SetFont(wx.Font(8, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.copy_btn = wx.Button(run, label='Copy log')
        self.copy_btn.SetToolTip('Puts the whole log on the clipboard, e.g. to paste into an issue.')
        self.copy_btn.Bind(wx.EVT_BUTTON, self.on_copy_log)
        self.clear_btn = wx.Button(run, label='Clear log')
        self.clear_btn.Bind(wx.EVT_BUTTON, lambda e: self.log.Clear())
        log_row = wx.BoxSizer(wx.HORIZONTAL)
        log_row.Add(wx.StaticText(run, label='Log'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        log_row.Add(self.copy_btn, 0, wx.RIGHT, 6)
        log_row.Add(self.clear_btn)

        plot_row = wx.BoxSizer(wx.HORIZONTAL)
        plot_row.Add(wx.StaticText(resp, label='Plot'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        plot_row.Add(self.plot_ctl)
        res_box = wx.BoxSizer(wx.VERTICAL)
        res_box.Add(self.summary, 0, wx.ALL, 10)
        res_box.Add(plot_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        res_box.Add(self.picture, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        resp.SetSizer(res_box)

        # Simulation tab: the chosen mode's run settings (mesher.py MODES), each one can be changed
        self.sim_note = wx.StaticText(sim, label='')
        self.sim_ctl = {k: wx.TextCtrl(sim, size=(90, -1)) for k, _ in core.SIM_FIELDS}
        self.pattern = wx.CheckBox(sim, label='compute (gain, efficiency, pattern: near-to-far field)')
        sim_grid = wx.FlexGridSizer(0, 2, 6, 10)
        for k, label in core.SIM_FIELDS:
            if k == 'f_pat':
                sim_grid.Add(wx.StaticText(sim, label='Radiation pattern'), 0, wx.ALIGN_CENTER_VERTICAL)
                sim_grid.Add(self.pattern, 0, wx.ALIGN_CENTER_VERTICAL)
            sim_grid.Add(wx.StaticText(sim, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            sim_grid.Add(self.sim_ctl[k], 0, wx.ALIGN_CENTER_VERTICAL)
        reset = wx.Button(sim, label='Reset to the mode values')
        reset.Bind(wx.EVT_BUTTON, lambda e: self.fill_sim())
        sim_box = wx.BoxSizer(wx.VERTICAL)
        sim_box.Add(self.sim_note, 0, wx.ALL, 10)
        sim_box.Add(sim_grid, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sim_box.Add(reset, 0, wx.LEFT | wx.BOTTOM, 10)
        rules = wx.StaticText(sim, label='The board is always in PML_8 absorbers. Copper is zero-thickness PEC, ground vias PEC lines. '
                                        'Smaller cells and a lower end criterion are more accurate and slower; '
                                        'a run that hits Max timesteps did not converge.')
        rules.Wrap(520)
        sim_box.Add(rules, 0, wx.ALL, 10)
        sim.SetSizer(sim_box)
        sim.SetScrollRate(0, 10)
        self.fill_sim(s['sim_sets'])

        top = wx.BoxSizer(wx.VERTICAL)
        top.Add(header, 0, wx.ALL, 10)
        top.Add(self.book, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(grid, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        root.Add(self.mode_help, 0, wx.ALL, 10)
        root.Add(feed_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(case_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(oct_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(ems_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(out_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(self.view, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(self.phase, 0, wx.LEFT | wx.RIGHT, 10)
        root.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        root.Add(self.elapsed, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(log_row, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        root.Add(self.log, 1, wx.EXPAND | wx.ALL, 10)
        run.SetSizer(root)
        self.SetSizer(top)
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
        return {'mode': MODES[self.mode_ctl.GetSelection()][1], 'f0': self.f0.GetValue().strip(), 'lo': self.lo.GetValue().strip(),
                'hi': self.hi.GetValue().strip(), 'octave': self.octave.GetValue().strip(),
                'openems': self.openems.GetValue().strip(), 'theme': self.theme_ctl.GetSelection(),
                'outdir': self.outdir.GetValue().strip(), 'view': self.view.GetValue(),
                'case': self.case_ctl.GetSelection() == 1, 'case_vals': [c.GetValue().strip() for c in self.case_vals],
                'sim_sets': self.sim_sets_or_none(),
                'size': None if self.IsMaximized() else list(self.GetSize())}

    def fill_sim(self, sets=()):
        """The Simulation tab shows the chosen mode's values, then the saved changes in sets (KEY=VALUE)."""
        mode = MODES[self.mode_ctl.GetSelection()][1]
        v = dict(mode_values(mode))
        for kv in sets:
            k, _, x = kv.partition('=')
            if k in v:
                v[k] = x
        for k, c in self.sim_ctl.items():
            c.SetValue('%g' % float(v[k]))
        self.pattern.SetValue(bool(float(v['pattern'])))
        self.sim_note.SetLabel('The values of the %s mode. Change any of them for your runs; changing the mode resets '
                               'them.' % ('coarse' if mode == 'dry' else mode))

    def sim_sets(self, mode):
        """The changed run settings as KEY=VALUE; ValueError when one is not a number or out of range."""
        vals = {k: c.GetValue().strip() for k, c in self.sim_ctl.items()}
        vals['pattern'] = str(int(self.pattern.GetValue()))
        sets = core.sim_sets(vals, mode_values(mode))
        mesher.settings('coarse' if mode == 'dry' else mode, sets)   # the same check kicad2ant.py makes
        return sets

    def enable_case(self):
        for c in self.case_vals:
            c.Enable(self.case_ctl.GetSelection() == 1)

    def sim_sets_or_none(self):
        try:
            return self.sim_sets(MODES[self.mode_ctl.GetSelection()][1])
        except ValueError:
            return []

    def apply_theme(self):
        """System leaves every colour to KiCad / the OS; Light and Dark set them on the window and its controls."""
        theme = self.theme_ctl.GetSelection()
        bg, fg, field = (wx.Colour(*c) for c in COLOURS[theme]) if theme else (wx.NullColour,) * 3
        dark = theme == 2 or (theme == 0 and wx.SystemSettings.GetAppearance().IsDark())
        def walk(w):   # the pages' controls are grandchildren of the window
            yield w
            for c in w.GetChildren():
                yield from walk(c)
        for w in walk(self):
            w.SetBackgroundColour(field if isinstance(w, (wx.TextCtrl, wx.Choice, wx.Button)) else bg)
            w.SetForegroundColour(fg)
            w.Refresh()   # on Windows a page's labels keep their old colours until repainted
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
        case = ()
        if self.case_ctl.GetSelection() == 1:
            try:
                case = core.case_args(c.GetValue().strip() for c in self.case_vals)
            except ValueError:
                wx.MessageBox('Plastic case: εr is 1 or more, the wall more than 0 mm, tanδ and the gaps 0 or more.', TITLE)
                return
        try:
            sets = self.sim_sets(mode)
        except ValueError:
            self.book.SetSelection(1)
            wx.MessageBox('Simulation tab: every value must be a number. Cells, ratio above 1, points, steps and the '
                          'pattern step above 0; end criterion below 0 dB; the sweep start below its stop.', TITLE)
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
        if core.lock_holder(out):   # another run, from this window or the command line
            wx.MessageBox('Another simulation is using this board folder:\n' + out, TITLE)
            return
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
                             self.view.GetValue(), case, sets)
        self.out, self.mode, self.started = out, mode, time.time()
        self.target = None if mode == 'dry' else -float(self.sim_ctl['end_db'].GetValue())
        self.log_pos, self.log_rest, self.best, self.stopped = 0, '', 0.0, False
        self.log.Clear()
        self.add_log(' '.join(cmd))
        self.set_summary('')
        self.set_pictures([])
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
        core.take_lock(out, self.proc.pid)   # kicad2ant.py takes it too; the same pid either way
        self.run_btn.Disable()
        self.stop_btn.Enable()
        self.clear_btn.Disable()   # the log holds the failure reason until the run ends
        self.run_dir_btn.Enable()   # the folder exists now: watch antenna_geom.m appear
        self.timer.Start(1000)
        threading.Thread(target=self.reader, args=(self.proc, out), daemon=True).start()

    def reader(self, proc, out):
        for line in proc.stdout:
            wx.CallAfter(self.add_log, line.rstrip())
        code = proc.wait()
        core.release_lock(out, proc.pid)   # here, not in finished(): the dialog may be gone by now
        wx.CallAfter(self.finished, code)

    def on_copy_log(self, _):
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(self.log.GetValue()))
            wx.TheClipboard.Close()
            self.copy_btn.SetLabel('Copied')
            wx.CallLater(2000, lambda: self and self.copy_btn.SetLabel('Copy log'))

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
        target = self.target
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
        self.clear_btn.Enable()
        res = core.find_result(self.out, self.mode, self.started)
        if code == 0 and res:
            self.gauge.SetValue(1000)
            self.phase.SetLabel('Done')
            self.show_result(self.mode, res, '')
            self.book.SetSelection(1)   # the Results page
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
        self.set_pictures(core.result_pictures(self.out, name, mode))
        self.folder_btn.Enable()
        self.run_dir_btn.Enable()
        self.grow()

    def set_pictures(self, pics):
        self.pics = pics
        self.plot_ctl.Set([label for label, _ in pics])
        if pics:
            self.plot_ctl.SetSelection(0)
        self.show_picture()

    def show_picture(self):
        i = self.plot_ctl.GetSelection()
        self.img = wx.Image(self.pics[i][1]) if self.pics and i >= 0 else None
        if self.img is not None and not self.img.IsOk():
            self.img = None
        self.scaled = None
        self.picture.Refresh()

    def picture_bitmap(self):
        """The plot scaled to fit the picture panel (cached per panel size), or None."""
        if self.img is None:
            return None
        size = tuple(self.picture.GetClientSize())
        if self.scaled is None or self.scaled[0] != size:
            w, h = core.fit(self.img.GetWidth(), self.img.GetHeight(), max(size[0], 1), max(size[1], 1))
            self.scaled = size, wx.Bitmap(self.img.Scale(max(w, 1), max(h, 1), wx.IMAGE_QUALITY_HIGH))
        return self.scaled[1]

    def on_paint_picture(self, _):
        dc = wx.AutoBufferedPaintDC(self.picture)
        dc.SetBackground(wx.Brush(self.picture.GetParent().GetBackgroundColour()))
        dc.Clear()
        bmp = self.picture_bitmap()
        if bmp is not None:
            dc.DrawBitmap(bmp, 0, 0)

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
