"""kicad2ant IPC API plugin entry point. KiCad starts this script in its own Python process (plugin.json) with
KICAD_API_SOCKET / KICAD_API_TOKEN set, which kipy uses to connect back to the open PCB editor."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
APP_ID = 'com.github.sijah.kicad2ant'


def say_without_wx(msg):
    """KiCad runs plugins with pythonw on Windows, where stderr goes nowhere: also leave the message in a file."""
    if sys.stderr:
        sys.stderr.write(msg + '\n')
    try:
        with open(os.path.join(tempfile.gettempdir(), 'kicad2ant_plugin_error.txt'), 'w', encoding='utf-8') as f:
            f.write(msg + '\n')
    except OSError:
        pass


def raise_window(title):
    """Bring the already open kicad2ant window forward (it is another process). Windows only; False elsewhere."""
    if sys.platform != 'win32':   # shortcut: Linux/macOS get the "already open" message, add a socket ping if asked
        return False
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)   # SW_RESTORE: un-minimize
    user32.SetForegroundWindow(hwnd)
    return True


def main():
    try:
        import wx
    except ImportError:
        say_without_wx('kicad2ant needs wxPython in the Python KiCad uses (%s): install python3-wxgtk4.0, '
                       'or set the interpreter in Preferences > Plugins.' % sys.executable)
        return 1
    wx.Log.SetLogLevel(wx.LOG_Warning)   # wx's 'Adding duplicate image handler' debug notes, which KiCad shows as plugin messages
    import host
    if sys.platform == 'win32':   # its own taskbar button instead of being grouped under pythonw.exe
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    app = wx.App(False)
    import dialog
    theme = dialog.load_settings()['theme']
    if hasattr(app, 'SetAppearance'):   # wx 4.3: before the first window, or native controls stay light in Dark
        app.SetAppearance((wx.App.Appearance.System, wx.App.Appearance.Light, wx.App.Appearance.Dark)[theme if theme in (0, 1, 2) else 0])
    one = wx.SingleInstanceChecker('kicad2ant-' + wx.GetUserId())
    if one.IsAnotherRunning():   # each toolbar press starts a new process; the open window is already there
        if not raise_window('%s %s: antenna simulation' % (dialog.TITLE, dialog.VERSION)):
            wx.MessageBox('kicad2ant is already open: find its window on the taskbar.', 'kicad2ant')
        return 0
    try:
        board = host.connect()
    except host.HostError as e:
        wx.MessageBox(str(e), 'kicad2ant', wx.ICON_WARNING)
        return 1
    if not host.board_path(board):
        wx.MessageBox('Save the board once first.', 'kicad2ant')
        return 0
    dialog.Kicad2antDialog(None).Show()   # not modal: the feed pad can be clicked in the editor meanwhile
    app.MainLoop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
