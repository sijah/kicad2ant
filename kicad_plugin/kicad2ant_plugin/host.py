"""The plugin's only link to KiCad: kipy (KiCad IPC API) calls, with errors turned into messages for the user.
kipy is imported inside functions, so CI (no kipy) can import this file."""
import os
import time

from core import is_antenna_ref

API_OFF = ('kicad2ant talks to KiCad through its API: turn on Preferences > Plugins > Enable KiCad API, '
           'then restart KiCad.')
NO_BOARD = 'Open a board in the PCB editor first.'
BUSY = 'KiCad is busy (filling zones?): try again when it is done.'
AS_BUSY = 7   # kipy.proto.common.ApiStatusCode.AS_BUSY: KiCad answers this while the zone fill runs


class HostError(Exception):
    """Its message is meant for the user."""


def _host_error(e):
    if type(e).__name__ == 'ConnectionError' or isinstance(e, OSError):   # kipy.errors.ConnectionError, or a dead pipe
        return HostError(API_OFF)
    if getattr(e, 'code', None) == AS_BUSY:
        return HostError(BUSY)
    return HostError('KiCad refused the request: %s' % e)


def connect():
    try:
        from kipy import KiCad
        kicad = KiCad()
    except Exception as e:
        raise _host_error(e) from None
    try:
        return kicad.get_board()
    except Exception as e:
        if type(e).__name__ == 'ApiError' and getattr(e, 'code', None) != AS_BUSY:   # no PCB editor open
            raise HostError(NO_BOARD) from None
        raise _host_error(e) from None


def board_path(board):
    """The open board's file, '' while it has never been saved."""
    try:
        return os.path.join(board.get_project().path, board.name) if board.name else ''
    except Exception as e:
        raise _host_error(e) from None


def footprints(board):
    """[(ref, lib id)] for core.auto_pick."""
    try:
        return [(fp.reference_field.text.value, str(fp.definition.id)) for fp in board.get_footprints()]
    except Exception as e:
        raise _host_error(e) from None


def feed_from_selection(items, fps):
    """(ref, pad number, named like an antenna) for one selected footprint (its pad 1) or a selected pad, else None.
    Anything else selected (a track, a zone, two footprints) gives None rather than a guess."""
    sel_fps = [it for it in items if type(it).__name__ == 'FootprintInstance']
    if len(sel_fps) > 1:
        return None
    if sel_fps:
        fp, num = sel_fps[0], '1'
    else:
        pad = next((it for it in items if type(it).__name__ == 'Pad'), None)
        if pad is None:
            return None
        fp = next((f for f in fps if any(p.id.value == pad.id.value for p in f.definition.pads)), None)
        if fp is None:
            return None
        num = pad.number
    ref = fp.reference_field.text.value
    return ref, num, is_antenna_ref(ref, str(fp.definition.id))


def selected_feed(board):
    try:
        return feed_from_selection(board.get_selection(), board.get_footprints())
    except Exception as e:
        raise _host_error(e) from None


def fill_and_copy(board, copy_path, wait=300, poll=0.5):
    """Refill the zones in the open board, then save a copy (without the project) once the fill is done.
    kipy 0.8.0's blocking refill never times out, so start it unblocked and retry the save while KiCad is busy:
    KiCad refuses it until the fill ends, so the copy never has stale fills."""
    deadline = time.time() + wait
    try:
        board.refill_zones(block=False)
        while True:
            try:
                board.save_as(copy_path, overwrite=True, include_project=False)
                return
            except Exception as e:
                if getattr(e, 'code', None) != AS_BUSY:
                    raise
            if time.time() > deadline:
                raise HostError('The zone fill did not finish in %d s: fill the zones (B) and run again.' % wait)
            time.sleep(poll)
    except HostError:
        raise
    except Exception as e:
        raise _host_error(e) from None
