"""Helpers for tuning an antenna on a copy of the board. Run with KiCad's own Python (it has pcbnew):
Windows "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe", Linux / macOS the python3 that imports pcbnew.

  fp_tools.py refill BOARD.kicad_pcb
      refills the zones and saves: do this after changing the antenna copper in a board copy, because
      kicad2ant reads the saved fills and those were made around the old antenna.
  fp_tools.py save-footprint BOARD.kicad_pcb REF LIB.pretty NAME
      saves footprint REF of the board as LIB.pretty/NAME.kicad_mod: unplaced, unrotated, pads without nets.
      This is how a tuned antenna gets from the simulated board copy into a footprint library.

Never run these on a board that is open in KiCad.
"""
import os, sys
import pcbnew

if len(sys.argv) == 3 and sys.argv[1] == 'refill':
    board = pcbnew.LoadBoard(sys.argv[2])
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(sys.argv[2], board)
    print('refilled', sys.argv[2])
elif len(sys.argv) == 6 and sys.argv[1] == 'save-footprint':
    path, ref, lib, name = sys.argv[2:]
    fp = pcbnew.LoadBoard(path).FindFootprintByReference(ref)
    if fp is None: sys.exit(f'no footprint {ref} on {path}')
    if fp.GetLayer() != pcbnew.F_Cu:   # shortcut: front-side footprints only, flip it back first when one is needed
        sys.exit(f'{ref} is on the back side: not supported')
    fp = pcbnew.Cast_to_FOOTPRINT(fp.Duplicate(False))
    fp.SetOrientationDegrees(0)
    fp.SetPosition(pcbnew.VECTOR2I(0, 0))
    for pad in fp.Pads(): pad.SetNetCode(0)
    fp.SetFPID(pcbnew.LIB_ID('', name))
    fp.SetReference('REF**')
    os.makedirs(lib, exist_ok=True)
    pcbnew.PCB_IO_MGR.FindPlugin(pcbnew.PCB_IO_MGR.KICAD_SEXP).FootprintSave(lib, fp)
    print('saved', os.path.join(lib, name + '.kicad_mod'))
else:
    sys.exit(__doc__)
