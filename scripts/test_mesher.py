"""Checks for mesher.py. Plain Python: python scripts/test_mesher.py (prints OK)."""
import mesher


def cells_in(v, a, b):
    return sum(1 for x, y in zip(v, v[1:]) if x >= a - 1e-9 and y <= b + 1e-9)


# axis(): a 0.5 mm trace at 1.0..1.5 with a hint line inside it, port planes at 3.0/3.1, edges 0.03 mm apart
big = lambda lo, hi: (0.25, 3)
v = mesher.axis([3.0, 3.1], [1.0, 1.5, 5.00, 5.03], [1.2, -10, 10], big, mesher.MERGE)
assert 1.0 in v and 1.5 in v, 'copper edges are grid lines'
assert 3.0 in v and 3.1 in v, 'port planes kept'
assert cells_in(v, 1.0, 1.5) >= 3, 'nmin cells across the trace, the hint line does not double them'
assert cells_in(v, 1.0, 1.5) <= 4, cells_in(v, 1.0, 1.5)
assert not any(5.0 <= x <= 5.03 for x in v) or sum(5.0 <= x <= 5.03 for x in v) == 1, 'edges within MERGE become one line'
assert mesher.ratio(v) <= 1.45, mesher.ratio(v)
assert v[0] == -10 and v[-1] == 10

# the least-cells rule is for traces and gaps between copper edges only: a via 0.1 mm off an edge is one cell
v = mesher.axis([], [1.0, 1.5], [0.9, -10, 10], big, mesher.MERGE)
assert min(b - a for a, b in zip(v, v[1:])) >= 0.099, v

# no cell below MERGE where the least-cells rule asks for one: a 0.072 mm step between two copper edges stays one cell
v = mesher.axis([], [0.0, 0.072, 2.0], [-10, 10], lambda lo, hi: (0.5, 2), mesher.MERGE)
assert cells_in(v, 0.0, 0.072) == 1 and min(q - p for p, q in zip(v, v[1:])) >= mesher.MERGE, v

# repair(): a cell over 1.5 times its neighbour is halved, and the lines already there stay
v = mesher.repair([0, 0.15, 0.3, 0.55, 0.8, 0.95])
assert {0, 0.15, 0.3, 0.55, 0.8, 0.95} <= set(v) and mesher.ratio(v) <= 1.5, v
# ... but a step into a ramp graded at 1.3 is left: halving it would halve every cell of the ramp (TI DN007 fast)
ramp = [0, 0.125, 0.325] + [0.325 + sum(0.2 * 1.3 ** j for j in range(1, n + 1)) for n in range(1, 12)]
assert mesher.repair(ramp) == ramp

# fill(): grows from both ends, never above smax, ends exactly on the gap
f = mesher.fill(0.0, 10.0, 0.1, 0.2, 1.0)
assert all(0 < x < 10 for x in f) and f == sorted(f)
d = [b - a for a, b in zip([0.0] + f, f + [10.0])]
assert max(d) <= 1.0 * mesher.RATIO + 1e-9 and mesher.ratio_cells([0.1] + d + [0.2]) <= 1.45

# build(): a 0.5 mm wide trace on a 1.6 mm board, coarse
for mode, rmax in (('coarse', 1.45), ('fine', 1.35), ('fast', 1.9)):
    g = mesher.build(mode, 2.44e9, [0, 0, 10, 0.5], [[0, 10], [0, 0.5]], [[], []], [0, 0, 1.6, 0.5, 0.5, 1.6],
                     [[], []], [], [(-20, -20), (20, -20), (20, 20), (-20, 20)], [0.0, 1.6], [(0.0, 1.6, 4.5, 0.02)])
    for k in 'xyz': assert mesher.ratio(g[k]) <= rmax, (mode, k, mesher.ratio(g[k]))
    assert cells_in(g['y'], 0, 0.5) >= mesher.MODES[mode]['nmin'], (mode, g['y'])
    assert 0.25 in g['x'] and 0.25 in g['y'], 'a line through the pad centre for the line port'
    assert 0.0 in g['z'] and 1.6 in g['z'] and cells_in(g['z'], 0, 1.6) >= mesher.MODES[mode]['nz']
    assert mesher.check(g, [0, 0, 1.6, 0.5, 0.5, 1.6], [0.0, 1.6], [(0.0, 1.6, 4.5, 0.02)]) == [], mode

# check(): catches a copper sheet off the z lines, a port off the grid, and lines out of order
g = {'x': [0, 1, 2], 'y': [0, 1, 2], 'z': [0, 0.8, 2]}
bad = mesher.check(g, [0.5, 0, 0, 0.5, 1, 0.8], [0, 1.6], [(0, 1.6, 4.5, 0.02)])
assert any('copper sheet z = 1.6' in b for b in bad) and any('port plane x = 0.5' in b for b in bad), bad
assert any('no y line inside the port' in b for b in bad), bad
assert mesher.check({'x': [0, 2, 1], 'y': [0], 'z': [0]}, [0] * 6, [0], []) == ['x lines not strictly increasing']
print('OK')
