# Builds openems_ifa.kicad_pcb: the IFA from openEMS's own example (matlab/examples/antennas/inverted_f.m,
# (C) 2013 Stefan Mahr), same dimensions, so kicad2ant's result can be checked against openEMS's script.
# 80 x 80 x 1.5 mm substrate (core 1.465 + copper: kicad2ant counts the copper), er 4.3, tan d 1e-3 (the example's kappa at 2.45 GHz), top copper only:
# ground plane up to 10 mm from the top edge, the IFA in that clearance. KiCad y points down.
h, l, w1, w2, wf, fp, e = 8, 22.5, 4, 2.5, 1, 4, 10    # ifa.h, .l, .w1, .w2, .wf, .fp, .e from the example
X, Y = 100, 70                                         # ground edge at the feed = footprint origin
L = '(layers "F.Cu")'
ant = f'''(footprint "IFA_openEMS_example" (layer "F.Cu") (at {X} {Y})
 (property "Reference" "AE1" (at 0 2 0) (layer "F.SilkS"))
 (pad "1" smd rect (at {wf/2} {-(h + 0.5)/2}) (size {wf} {h - 0.5}) {L} (net 2 "RF"))
 (pad "2" smd rect (at {-fp - w1/2} {-h/2}) (size {w1} {h}) {L} (net 1 "GND"))
 (fp_rect (start {-fp - w1} {-h}) (end {-fp - w1 + l} {-h + w2}) (stroke (width 0)) (fill solid) (layer "F.Cu")))'''
rect = lambda x0, y0, x1, y1: f'(pts (xy {x0} {y0}) (xy {x1} {y0}) (xy {x1} {y1}) (xy {x0} {y1}))'
gnd = rect(X - 40, Y, X + 40, Y + 80 - e)            # the example's ground copper
m = 0.125   # half the zone's min_thickness
# KiCad 10 file version: with an older one KiCad grows the stored fill by min_thickness/2 when it loads the board
open('openems_ifa.kicad_pcb', 'w', newline='\n').write(f'''(kicad_pcb (version 20260206) (generator "pcbnew")
(general (thickness 1.535))
(layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))
(setup (stackup (layer "F.Cu" (type "copper") (thickness 0.035))
 (layer "dielectric 1" (type "core") (thickness 1.465) (material "FR4") (epsilon_r 4.3) (loss_tangent 0.001))
 (layer "B.Cu" (type "copper") (thickness 0.035))))
(net 0 "") (net 1 "GND") (net 2 "RF")
{ant}
(gr_rect (start {X - 40} {Y - e}) (end {X + 40} {Y + 80 - e}) (stroke (width 0.1)) (layer "Edge.Cuts"))
(zone (net 1) (net_name "GND") (layer "F.Cu") (connect_pads yes (clearance 0.2)) (min_thickness {2 * m})
 (polygon {gnd}) (filled_polygon (layer "F.Cu") {gnd}))
)
''')
# ground to the board edge as in the example: KiCad's default copper-to-edge clearance (0.5 mm) would pull a refill back
open('openems_ifa.kicad_pro', 'w', newline='\n').write(
    '{"board": {"design_settings": {"rules": {"min_copper_edge_clearance": 0.0}}}, "meta": {"filename": "openems_ifa.kicad_pro", "version": 3}}\n')
