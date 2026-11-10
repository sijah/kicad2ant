import glob
lib = glob.glob(r'C:\Program Files\KiCad\*\share\kicad\footprints\RF_Antenna.pretty')[-1]
n = 'Texas_SWRA117D_2.4GHz_Left'
src = open(lib + '/' + n + '.kicad_mod', encoding='utf8').read().replace('"REF**"', '"AE1"')
src = src.replace(f'(footprint "{n}"', f'(footprint "{n}" (at 100 50)', 1)
src = src.replace('(pad "1" connect rect', '(pad "1" connect rect (net 2 "RF")').replace('(pad "2" thru_hole rect', '(pad "2" thru_hole rect (net 1 "GND")')
def zone(l, y0):
    p = f'(pts (xy 85 {y0}) (xy 115 {y0}) (xy 115 80) (xy 85 80))'
    return f'(zone (net 1) (net_name "GND") (layer "{l}") (polygon {p}) (filled_polygon (layer "{l}") {p}))'
open('ifa.kicad_pcb', 'w', newline='\n').write(f'''(kicad_pcb (version 20240108) (generator "pcbnew")
(general (thickness 1.6))
(layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))
(setup (stackup (layer "F.Cu" (type "copper") (thickness 0.035))
 (layer "dielectric 1" (type "core") (thickness 1.51) (material "FR4") (epsilon_r 4.5) (loss_tangent 0.02))
 (layer "B.Cu" (type "copper") (thickness 0.035))))
(net 0 "") (net 1 "GND") (net 2 "RF")
{src}
(gr_rect (start 85 44) (end 115 80) (stroke (width 0.1)) (layer "Edge.Cuts"))
{zone("F.Cu", 51)}
{zone("B.Cu", 49.9)}
(via (at 90 52) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))
(via (at 110 52) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))
)
''')
