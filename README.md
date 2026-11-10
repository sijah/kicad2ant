# kicad2ant

Check how well the antenna on your KiCad PCB works, before you build the board.
It reads your `.kicad_pcb` file, simulates the antenna, and gives you plots: how well it is matched
(S11), the band it works in, its gain and its radiation pattern.

## 1. Install (once)

- [Python 3](https://www.python.org/downloads/)
- [GNU Octave](https://octave.org/download)
- [openEMS](https://github.com/thliebig/openEMS-Project/releases): unzip to a folder without spaces,
  e.g. `C:\openEMS`, then in Octave run once: `cd C:\openEMS\matlab; setup`

## 2. Prepare your board

In KiCad: press **B** to fill zones, then **save**. Your antenna footprint should be named `AE1` / `ANT1`.

## 3. Run

Windows: **drag your `.kicad_pcb` file onto `scripts/kicad2ant.bat`.**

Or from a terminal:

```
python scripts/kicad2ant.py myboard.kicad_pcb
```

Results (plots and a summary) appear in `myboard_kicad2ant/results/`.
Open `*_geometry.png` first to check the antenna and ground look right.

Other frequency, e.g. 868 MHz: `python scripts/kicad2ant.py myboard.kicad_pcb --f0 868`

## Use it inside KiCad (KiCad 7 to 10)

After the installs in step 1:

1. Get `kicad2ant-<version>-pcm.zip` (or build it: `python kicad_plugin/build_pcm.py`, it lands in `dist/`).
2. KiCad: **Plugin and Content Manager > Install from File...** and pick the zip.
3. In the PCB editor press the kicad2ant button in the top toolbar (also under **Tools > External Plugins**).
   Run **Check model** first, then **Coarse**. Zones are filled for you and your board file is not changed.

If a run fails, the red text in the plugin window says what is missing (usually Octave or openEMS not found:
set the Octave path in the window). The Flatpak build of KiCad on Linux is not supported.

Full options and details: [docs/USAGE.md](docs/USAGE.md). Example board: [examples/ti_ifa](examples/ti_ifa).
