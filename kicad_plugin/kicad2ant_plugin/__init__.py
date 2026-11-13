"""kicad2ant KiCad plugin: simulate the antenna of the open board in openEMS from a toolbar button.

It fills the zones, saves a copy of the board as it is on screen into the run folder and runs scripts/kicad2ant.py
on that copy (the user's .kicad_pcb / .kicad_pro are never written). Progress comes from openEMS's own log file."""
import json, os, re, subprocess, sys, threading, time

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
GOOD = 'Good: the -10 dB band covers your target band.'
THEMES = ['System', 'Light', 'Dark']
COLOURS = {1: ((245, 245, 245), (20, 20, 20), (255, 255, 255)), 2: ((32, 32, 32), (225, 225, 225), (48, 48, 48))}   # window, text, field
NOT_NAMED = '  (not named AE* / ANT*: check it is the antenna, not a matching part)'
TITLE = 'kicad2ant'
VERSION = '0.3.3'   # build_pcm.py checks it against metadata.json
LOGO = os.path.join(PLUGIN_DIR, 'icon64.png')
if not os.path.isfile(LOGO):   # running from the repo
    LOGO = os.path.join(PLUGIN_DIR, '..', 'icon64.png')
_dialog = None
SIM_GROUPS = (('Sweep', ('f_start', 'f_stop', 'npts')), ('Mesh', ('cell', 'nmin', 'nz', 'merge', 'ratio', 'air')),
              ('Run', ('end_db', 'nrts', 'threads')), ('Far field', ('pattern', 'f_pat', 'pat_step')))


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
        if logo is not None and logo.IsOk():
            self.SetIcon(wx.Icon(wx.Bitmap(logo)))
        s = load_settings()
        self.proc = None
        self.out = ''
        self.mode = 'fast'
        self.target = None
        self.feed = None
        self.feed_board = None
        self.started = 0.0
        self.log_pos = 0
        self.log_rest = ''
        self.best = 0.0
        self.samples = []   # (seconds, dB) from openEMS's log, for the time left
        self.stopped = False
        self.failed = False
        self.summary_text = ''
        self.img = None   # the full-size wx.Image of the plot on the Results page
        self.pics = []

        self.book = wx.Notebook(self)
        run = wx.Panel(self.book)
        sim = wx.ScrolledWindow(self.book)
        resp = wx.Panel(self.book)
        setup = wx.Panel(self.book)
        for page, label in ((run, 'Run'), (sim, 'Simulation'), (resp, 'Results'), (setup, 'Setup')):
            self.book.AddPage(page, label)

        # ---- Run: what to simulate, then run it
        self.mode_ctl = wx.Choice(run, choices=[m[0] for m in MODES])
        self.mode_ctl.SetSelection([m for _, m in MODES].index(core.mode_key(s['mode'])))
        self.mode_ctl.SetToolTip('\n'.join('%s: %s' % (label.split(':')[0].split(' (')[0], HELP[m]) for label, m in MODES))
        self.mode_ctl.Bind(wx.EVT_CHOICE, lambda e: self.on_mode())
        self.mode_help = wx.StaticText(run, label='')   # what the chosen mode does, in one line
        self.f0 = wx.TextCtrl(run, value=s['f0'], size=(70, -1))
        self.lo = wx.TextCtrl(run, value=s['lo'], size=(70, -1))
        self.hi = wx.TextCtrl(run, value=s['hi'], size=(70, -1))
        for c in (self.lo, self.hi):
            c.SetToolTip('Target band in MHz. Leave empty for the default shown in grey: 2400 to 2483.5 at 2440 MHz, '
                         'else f0 +/- 2 %.')
        self.gnd = wx.TextCtrl(run, size=(110, -1))
        self.gnd.SetHint('auto')
        self.gnd.SetToolTip('The ground net of this board. Leave empty: the net of the antenna\'s pad 2, else GND, '
                            'else the largest zone net with a ground name (AGND, GNDA, VSS ...).')
        band = wx.BoxSizer(wx.HORIZONTAL)
        band.Add(self.lo, 0, wx.ALIGN_CENTER_VERTICAL)
        band.Add(wx.StaticText(run, label=' to '), 0, wx.ALIGN_CENTER_VERTICAL)
        band.Add(self.hi, 0, wx.ALIGN_CENTER_VERTICAL)
        grid = wx.FlexGridSizer(0, 4, 6, 8)
        for label, ctl in (('Mode', self.mode_ctl), ('f0 (MHz)', self.f0), ('Band (MHz)', band), ('Ground net', self.gnd)):
            grid.Add(wx.StaticText(run, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(ctl, 0, wx.ALIGN_CENTER_VERTICAL)

        self.feed_txt = wx.StaticText(run, label='')
        use_sel = wx.Button(run, label='Use selected pad')
        use_sel.SetToolTip('Click the feed pad of the antenna in the PCB editor (this window stays open), then press this.')
        use_sel.Bind(wx.EVT_BUTTON, self.on_use_selected)
        auto = wx.Button(run, label='Auto')
        auto.SetToolTip('The one footprint named AE* / ANT* or from an antenna library, pad 1.')
        auto.Bind(wx.EVT_BUTTON, lambda e: self.set_feed(None))
        feed_row = wx.BoxSizer(wx.HORIZONTAL)
        feed_row.Add(wx.StaticText(run, label='Antenna'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
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
        case_row = wx.WrapSizer(wx.HORIZONTAL)   # the plastic fields wrap in a narrow window
        case_row.Add(wx.StaticText(run, label='Board in'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        case_row.Add(self.case_ctl, 0, wx.RIGHT, 8)
        self.case_widgets = list(self.case_vals)   # shown only for a plastic case
        for (label, _), c in zip(core.CASE_FIELDS, self.case_vals):
            t = wx.StaticText(run, label=label)
            self.case_widgets.append(t)
            case_row.Add(t, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 3)
            case_row.Add(c, 0, wx.RIGHT, 6)
        mm = wx.StaticText(run, label='mm')
        self.case_widgets.append(mm)
        case_row.Add(mm, 0, wx.ALIGN_CENTER_VERTICAL)
        self.case_ctl.Bind(wx.EVT_CHOICE, lambda e: self.enable_case())

        self.sim_line = wx.StaticText(run, label='')   # the Simulation tab's changes, so the mode label never misleads
        edit = wx.Button(run, label='Edit')
        edit.Bind(wx.EVT_BUTTON, lambda e: self.book.SetSelection(1))
        sim_row = wx.BoxSizer(wx.HORIZONTAL)
        sim_row.Add(self.sim_line, 1, wx.ALIGN_CENTER_VERTICAL)
        sim_row.Add(edit, 0, wx.LEFT, 6)

        self.view = wx.CheckBox(run, label="Open the 3D model in openEMS's viewer (AppCSXCAD) when the run ends")
        self.view.SetValue(bool(s['view']))
        self.view.SetToolTip('The model exactly as openEMS gets it: copper, board, port and mesh lines. '
                             'With Check model it opens in seconds.')

        self.run_btn = wx.Button(run, label='Simulate')
        self.run_btn.SetToolTip('Fills the zones (like pressing B) and runs on a copy of the board as it is on screen. '
                                'Your board file is not changed.')
        self.run_btn.Bind(wx.EVT_BUTTON, self.on_run)
        self.stop_btn = wx.Button(run, label='Stop')
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        self.stop_btn.Disable()
        self.open_btn = wx.Button(run, label='Open folder \u25be')
        self.open_btn.SetToolTip('The results (plots, summary, .s1p) or the run folder (board copy, model, openEMS files).')
        self.open_btn.Bind(wx.EVT_BUTTON, self.on_open_menu)
        self.open_btn.Disable()
        close = wx.Button(run, wx.ID_CLOSE, 'Close')
        close.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for b in (self.run_btn, self.stop_btn, self.open_btn):
            buttons.Add(b, 0, wx.RIGHT, 6)
        buttons.AddStretchSpacer()
        buttons.Add(close)

        self.phase = wx.StaticText(run, label='')
        self.elapsed = wx.StaticText(run, label='')
        status = wx.BoxSizer(wx.HORIZONTAL)
        status.Add(self.phase, 1, wx.ALIGN_CENTER_VERTICAL)
        status.Add(self.elapsed, 0, wx.ALIGN_CENTER_VERTICAL)
        self.gauge = wx.Gauge(run, range=1000, size=(-1, 14))

        self.log_pane = wx.CollapsiblePane(run, label='Log', style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE)
        pane = self.log_pane.GetPane()
        self.log = wx.TextCtrl(pane, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 140))   # wraps: long lines stay readable
        self.log.SetFont(wx.Font(8, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.copy_btn = wx.Button(pane, label='Copy log')
        self.copy_btn.SetToolTip('Puts the whole log on the clipboard, e.g. to paste into an issue.')
        self.copy_btn.Bind(wx.EVT_BUTTON, self.on_copy_log)
        self.clear_btn = wx.Button(pane, label='Clear log')
        self.clear_btn.Bind(wx.EVT_BUTTON, lambda e: self.log.Clear())
        log_btns = wx.BoxSizer(wx.HORIZONTAL)
        log_btns.Add(self.copy_btn, 0, wx.RIGHT, 6)
        log_btns.Add(self.clear_btn)
        log_box = wx.BoxSizer(wx.VERTICAL)
        log_box.Add(log_btns, 0, wx.BOTTOM, 6)
        log_box.Add(self.log, 1, wx.EXPAND)
        pane.SetSizer(log_box)
        self.log_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, lambda e: self.layout_log())

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(grid, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        root.Add(self.mode_help, 0, wx.ALL, 10)
        for row in (feed_row, case_row, sim_row):
            root.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(self.view, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        root.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(self.log_pane, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        run.SetSizer(root)
        self.run_sizer = root

        # ---- Results
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
        plot_row = wx.BoxSizer(wx.HORIZONTAL)
        plot_row.Add(wx.StaticText(resp, label='Plot'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        plot_row.Add(self.plot_ctl)
        res_box = wx.BoxSizer(wx.VERTICAL)
        res_box.Add(self.summary, 0, wx.ALL, 10)
        res_box.Add(plot_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        res_box.Add(self.picture, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        resp.SetSizer(res_box)

        # ---- Simulation: the chosen mode's run settings (mesher.py MODES), in groups; changed ones in bold
        label_of = dict(core.SIM_FIELDS)
        self.sim_note = wx.StaticText(sim, label='')
        self.sim_ctl = {}
        groups = wx.BoxSizer(wx.VERTICAL)
        for title, keys in SIM_GROUPS:
            sb = wx.StaticBoxSizer(wx.VERTICAL, sim, title)
            box = sb.GetStaticBox()
            g = wx.FlexGridSizer(0, 2, 6, 10)
            for k in keys:
                if k == 'pattern':
                    self.pattern = wx.CheckBox(box, label='compute gain, efficiency and pattern')
                    self.pattern.Bind(wx.EVT_CHECKBOX, lambda e: self.sim_changed())
                    g.Add(self.pattern, 0, wx.ALIGN_CENTER_VERTICAL)
                    g.AddSpacer(0)
                    continue
                c = wx.TextCtrl(box, size=(80, -1))
                c.Bind(wx.EVT_TEXT, lambda e: self.sim_changed())
                self.sim_ctl[k] = c
                g.Add(wx.StaticText(box, label=label_of[k]), 0, wx.ALIGN_CENTER_VERTICAL)
                g.Add(c, 0, wx.ALIGN_CENTER_VERTICAL)
            sb.Add(g, 0, wx.ALL, 6)
            groups.Add(sb, 0, wx.EXPAND | wx.BOTTOM, 8)
        reset = wx.Button(sim, label='Reset to the mode values')
        reset.Bind(wx.EVT_BUTTON, lambda e: self.fill_sim())
        sim_box = wx.BoxSizer(wx.VERTICAL)
        sim_box.Add(self.sim_note, 0, wx.ALL, 10)
        sim_box.Add(groups, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sim_box.Add(reset, 0, wx.LEFT | wx.BOTTOM, 10)
        sim.SetSizer(sim_box)
        sim.SetScrollRate(10, 10)
        self.sim_note.SetToolTip('The board is always in PML_8 absorbers; copper is zero-thickness PEC, ground vias PEC '
                                 'lines. Smaller cells and a lower end criterion are more accurate and slower; a run '
                                 'that hits Max timesteps did not converge.')

        # ---- Setup: set once
        self.theme_ctl = wx.Choice(setup, choices=THEMES)
        self.theme_ctl.SetSelection(s['theme'] if s['theme'] in (0, 1, 2) else 0)
        self.theme_ctl.Bind(wx.EVT_CHOICE, lambda e: self.apply_theme())
        self.octave = wx.TextCtrl(setup, value=s['octave'])
        self.octave.SetHint('found by itself')
        self.octave.SetToolTip('Set it only if the run says Octave was not found: octave-gui.exe or octave.')
        self.openems = wx.TextCtrl(setup, value=s['openems'])
        self.openems.SetHint('found by itself')
        self.openems.SetToolTip('The openEMS folder, no spaces in the path: the one holding openEMS.exe and matlab on '
                                'Windows, the install prefix (e.g. ~/opt/openEMS) on Linux and macOS.')
        self.outdir = wx.TextCtrl(setup, value=s['outdir'])
        self.outdir.SetHint('next to the board file')
        self.outdir.SetToolTip('Where the run folder <board>_kicad2ant is made. A place with a space in its path cannot '
                               'be used (openEMS): a folder in your local app data is used then.')
        sg = wx.FlexGridSizer(0, 3, 8, 8)
        sg.AddGrowableCol(1)
        for label, ctl, handler in (('Octave', self.octave, self.on_browse), ('openEMS folder', self.openems, self.on_browse_openems),
                                    ('Run folders in', self.outdir, self.on_browse_outdir)):
            b = wx.Button(setup, label='...', size=(30, -1))
            b.Bind(wx.EVT_BUTTON, handler)
            sg.Add(wx.StaticText(setup, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            sg.Add(ctl, 1, wx.EXPAND)
            sg.Add(b)
        sg.Add(wx.StaticText(setup, label='Theme'), 0, wx.ALIGN_CENTER_VERTICAL)
        sg.Add(self.theme_ctl)
        setup_box = wx.BoxSizer(wx.VERTICAL)
        setup_box.Add(sg, 0, wx.EXPAND | wx.ALL, 10)
        setup.SetSizer(setup_box)

        top = wx.BoxSizer(wx.VERTICAL)
        top.Add(self.book, 1, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(top)

        self.sweep_shown = None   # the default sweep the tab shows, to follow f0 until the user changes it
        self.mode_help.SetLabel(HELP[MODES[self.mode_ctl.GetSelection()][1]])
        self.fill_sim(s['sim_sets'])
        self.f0.Bind(wx.EVT_TEXT, lambda e: self.on_f0())
        self.band_hints()
        self.set_feed(None)
        self.enable_case()
        self.SetMinSize((600, -1))
        self.Fit()
        if s['size']:
            self.SetSize(s['size'])
        self.apply_theme()

        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_tick, self.timer)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_ACTIVATE, lambda e: (self.feed is None and e.GetActive() and self.set_feed(None), e.Skip()))
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
        v = self.sim_defaults(mode)
        for kv in sets:
            k, _, x = kv.partition('=')
            if k in v:
                v[k] = x
        for k, c in self.sim_ctl.items():
            c.ChangeValue('%g' % float(v[k]))
        self.pattern.SetValue(bool(float(v['pattern'])))
        self.sweep_shown = core.auto_sweep(self.f0.GetValue().strip())
        self.sim_note.SetLabel('The values of the %s mode; the ones you change show in bold. Changing the mode resets '
                               'them.' % ('coarse' if mode == 'dry' else mode))
        self.sim_changed()

    def sim_changed(self):
        """Bold for the values that differ from the mode, pattern fields only with the pattern on, and the one-line
        account on the Run tab."""
        if not hasattr(self, 'pattern'):
            return
        mode = MODES[self.mode_ctl.GetSelection()][1]
        d = self.sim_defaults(mode)
        for k, c in list(self.sim_ctl.items()) + [('pattern', self.pattern)]:
            try:
                v = float(c.GetValue())
                changed = v != float(d[k])
            except ValueError:
                changed = True
            f = c.GetFont()
            f.SetWeight(wx.FONTWEIGHT_BOLD if changed else wx.FONTWEIGHT_NORMAL)
            c.SetFont(f)
        for k in ('f_pat', 'pat_step'):
            self.sim_ctl[k].Enable(self.pattern.GetValue())
        name = 'Coarse' if mode == 'dry' else mode.capitalize()
        try:
            sets = self.sim_sets(mode)
            self.sim_line.SetLabel('Simulation: %d change%s from %s (%s)' % (len(sets), 's' * (len(sets) > 1), name,
                                                                        core.describe_sets(sets))
                                   if sets else 'Simulation: the %s values' % name)
        except ValueError:
            self.sim_line.SetLabel('Simulation: a value is not valid, see the Simulation tab')
        self.sim_line.GetParent().Layout()

    def on_mode(self):
        self.mode_help.SetLabel(HELP[MODES[self.mode_ctl.GetSelection()][1]])
        self.fill_sim()

    def on_f0(self):
        self.follow_f0()
        self.band_hints()
        self.sim_changed()

    def band_hints(self):
        """The default target band, in grey in the empty band fields."""
        band = core.default_band(self.f0.GetValue().strip())
        self.lo.SetHint('%g' % band[0] if band else '')
        self.hi.SetHint('%g' % band[1] if band else '')

    def layout_log(self):
        """The open log takes the free height; folded, it gives it back."""
        self.run_sizer.GetItem(self.log_pane).SetProportion(0 if self.log_pane.IsCollapsed() else 1)
        self.log_pane.GetParent().Layout()
        if not self.log_pane.IsCollapsed():
            self.grow()

    def on_open_menu(self, _):
        m = wx.Menu()
        res = m.Append(wx.ID_ANY, 'Results folder: plots, summary, .s1p')
        res.Enable(os.path.isdir(os.path.join(self.out, 'results')))
        run = m.Append(wx.ID_ANY, 'Run folder: board copy, model, openEMS files')
        m.Bind(wx.EVT_MENU, lambda e: core.open_folder(os.path.join(self.out, 'results')), res)
        m.Bind(wx.EVT_MENU, lambda e: core.open_folder(self.out), run)
        self.open_btn.PopupMenu(m)
        m.Destroy()

    def sim_sets(self, mode):
        """The changed run settings as KEY=VALUE; ValueError when one is not a number or out of range."""
        vals = {k: c.GetValue().strip() for k, c in self.sim_ctl.items()}
        vals['pattern'] = str(int(self.pattern.GetValue()))
        sets = core.sim_sets(vals, self.sim_defaults(mode))
        m = mesher.settings('coarse' if mode == 'dry' else mode, sets)   # the same checks kicad2ant.py makes
        try:
            f0 = float(self.f0.GetValue()) * 1e6
        except ValueError:
            return sets   # on_run reports the bad f0
        lo, hi = mesher.sweep(m, f0)
        if lo >= hi:   # one end typed, the other the default: only the resolved sweep shows it
            raise ValueError('sweep start %g MHz is not below its stop %g MHz' % (lo / 1e6, hi / 1e6))
        return sets

    def sim_defaults(self, mode):
        """The mode's values, with the default sweep (0 in mesher.py) as numbers for the f0 on the Run tab."""
        v = dict(mode_values(mode))
        auto = core.auto_sweep(self.f0.GetValue().strip())
        if auto and not v['f_start'] and not v['f_stop']:
            v['f_start'], v['f_stop'] = auto
        return v

    def follow_f0(self):
        """A new f0 moves the shown default sweep with it; a sweep the user typed stays."""
        shown = tuple(c.GetValue().strip() for c in (self.sim_ctl['f_start'], self.sim_ctl['f_stop']))
        auto = core.auto_sweep(self.f0.GetValue().strip())
        if auto and self.sweep_shown and shown == tuple('%g' % x for x in self.sweep_shown):
            self.sim_ctl['f_start'].ChangeValue('%g' % auto[0])
            self.sim_ctl['f_stop'].ChangeValue('%g' % auto[1])
            self.sweep_shown = auto

    def enable_case(self):
        for w in self.case_widgets:
            w.Show(self.case_ctl.GetSelection() == 1)
        self.case_ctl.GetParent().Layout()

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
            if isinstance(w, wx.Gauge):   # the native bar keeps its own colours; set ones draw it as a white block
                continue
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
        board = pcbnew.GetBoard()
        self.feed_board = board.GetFileName()   # the pick belongs to this board only
        if feed is not None:
            text = '%s pad %s' % feed + ('' if named else NOT_NAMED)
        else:   # say what Auto finds, not the rule
            ref, why = core.auto_pick([(fp.GetReference(), fp.GetFPIDAsString()) for fp in board.GetFootprints()])
            text = ('Auto: %s pad 1' % ref + ('  (reference not annotated: annotate the board)' if re.search(r'[*?]', ref) else '')
                    if ref else 'Auto finds %s: select the feed pad and press Use selected pad' % why)
        self.feed_txt.SetLabel(text)
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
        self.log_pos, self.log_rest, self.best, self.stopped, self.samples = 0, '', 0.0, False, []
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
        self.open_btn.Enable()   # the folder exists now: watch antenna_geom.m appear
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
        left = core.time_left(self.samples, self.target)
        self.elapsed.SetLabel('%d:%02d' % (secs // 60, secs % 60) + ('' if left is None else '  ·  about %s left' % (
            '%d s' % left if left < 90 else '%d min' % round(left / 60))))
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
                e = core.energy(line)
                if e:
                    self.samples.append(e)
                self.best = max(self.best, p)
                self.gauge.SetValue(int(self.best * 1000))
                self.phase.SetLabel('Converging: -%d of -%d dB' % (int(self.best * target), target))
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
            self.book.SetSelection(2)   # the Results page (Run, Simulation, Results)
        else:
            self.phase.SetLabel('Stopped' if self.stopped else 'Failed')
            if not self.stopped:   # the reason is in the log: show it
                self.log_pane.Expand()
                self.layout_log()
            self.set_summary('Stopped.' if self.stopped else
                             (core.failure_line(self.log.GetValue().splitlines()) or 'Failed: see the log below.'), True)
        self.open_btn.Enable(os.path.isdir(self.out))
        self.grow()

    def show_result(self, mode, res, title):
        summary, name = res
        lines = core.summary_lines(summary) if summary else ['Model built: check the picture (ground grey, '
                                                             'antenna orange, port magenta on the feed pad).']
        if core.band_covered(lines):
            lines.append(GOOD)
        self.set_summary('\n'.join(([title] if title else []) + lines))
        self.set_pictures(core.result_pictures(self.out, name, mode))
        self.open_btn.Enable()
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
