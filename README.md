# kicad2ant

Simulate the printed antenna on your KiCad board before you send it to fab.

kicad2ant reads your `.kicad_pcb`, builds a 3D model of the antenna and its ground plane, and runs it through
[openEMS](https://openems.de), a free FDTD solver. You get S11, the band the antenna covers, its gain and its
radiation pattern. You don't have to enter any geometry by hand.

You can run it from a toolbar button in KiCad 10's PCB editor, from the command line
(`python scripts/kicad2ant.py myboard.kicad_pcb`), or as a [Claude Code](https://claude.com/claude-code) skill
(`SKILL.md`). All three use the same code underneath.

| Model | Match | Pattern |
|---|---|---|
| ![geometry](examples/openems_ifa/openems_ifa_kicad2ant/results/AE1_geometry.png) | ![S11 and Zin](examples/openems_ifa/openems_ifa_kicad2ant/results/AE1_coarse_s11_zin.png) | ![pattern](examples/openems_ifa/openems_ifa_kicad2ant/results/AE1_coarse_pattern.png) |

*From [examples/openems_ifa](examples/openems_ifa): the 2.45 GHz inverted-F antenna from openEMS's own
`inverted_f.m` example, drawn as a KiCad board (coarse run). kicad2ant puts its resonance at 2438 MHz,
openEMS's script at 2420 MHz. A meandered IFA from KiCad's footprint library is in
[examples/ti_ifa](examples/ti_ifa).*

This is version 0.1.0 and still being tested. I develop it on Windows with KiCad 10.0.8, Octave 11.1 and
openEMS v0.37. The Linux and macOS code paths are there but I haven't tried them yet. See
[Known limits](#known-limits).

## Why kicad2ant

Every tool in the chain is open source: kicad2ant, KiCad, GNU Octave and openEMS. There's no licence and no
account, and everything runs on your own PC, so nothing gets uploaded. It reads the antenna from the board file
itself, so there's no second copy of the design to keep in sync. Each run also leaves its model behind as
Octave files you can read, edit and run again. It's GPL-3.0, and issues and pull requests are welcome.

## What you get

- S11, input impedance and a Smith chart, the −10 dB band, and whether that band covers your target
- Directivity, radiation efficiency, gain and realized gain across the band
- Pattern cuts at resonance, plus a 3D pattern you can open in ParaView
- A Touchstone `.s1p` for designing the matching network
- Your VNA measurement drawn over the plots, if you have one
- A picture of the model (`*_geometry.png`), ready in a few seconds, so you can check the port and ground
  before a long run

Here's what it takes from the board:

| On the board | In the model |
|---|---|
| copper in the antenna footprint, on any layer: lines, arcs, polygons, pads, footprint zones | the antenna |
| filled zones, tracks and vias of the ground net, on every copper layer | the ground |
| Board Setup > Physical Stackup | one dielectric per copper pair (thickness, εr, loss) |
| Edge.Cuts, on the board and in footprints | the board outline and cutouts |
| the feed pad | a 50 Ω port to the ground under or beside it |

It works for inverted-F (IFA), meandered IFA, meander, monopole and patch antennas, and for loops above 100 MHz.

## Requirements

You need three free programs. kicad2ant doesn't bundle any of them.

| Program | Notes |
|---|---|
| KiCad 10 | for the plugin. The command line only needs the `.kicad_pcb` file |
| [GNU Octave](https://octave.org/download) | tested with 11.1 |
| [openEMS](https://github.com/thliebig/openEMS-Project/releases) v0.37 or newer | must be in a folder without spaces |
| Python 3 | command line only. The plugin uses KiCad's own Python |

Setting up openEMS, once:

- Windows: unzip the release somewhere without spaces, say `C:\openEMS`. Open Octave and run
  `cd C:\openEMS\matlab; setup` to build the file readers for your Octave version.
- Linux / macOS: install or build openEMS the way its docs say (usually into `~/opt/openEMS`).

kicad2ant looks for Octave and openEMS on its own: on `PATH`, in `C:\Program Files\GNU Octave` (newest version
first), and in any `openEMS*` folder up to two levels deep on drives C to H. If it doesn't find them, set the
**Octave** and **openEMS folder** fields in the plugin window, or the `OCTAVE` and `OPENEMS` environment
variables. On Windows the openEMS folder is the one containing `matlab/`. On Linux and macOS it's the install
prefix (the folder with `bin/` and `share/`).

## Installing the KiCad plugin

### Plugin and Content Manager

1. Download `com.github.sijah.kicad2ant-0.1.0.zip` from [Releases](https://github.com/sijah/kicad2ant/releases),
   or build it with `python kicad_plugin/build_pcm.py` (the zip ends up in `dist/`).
2. In KiCad, open the **Plugin and Content Manager**, click **Install from File…** and pick the zip.
3. Open the PCB editor. The kicad2ant button is in the top toolbar and under **Tools → External Plugins**. If
   you don't see it, try **Tools → External Plugins → Refresh Plugins** or restart KiCad.

### By hand

Unzip the package and copy what's inside its `plugins/` folder into a new `kicad2ant` folder here:

| OS | Folder |
|---|---|
| Windows | `C:\Users\<user>\Documents\KiCad\10.0\scripting\plugins\kicad2ant\` |
| Linux | `~/.local/share/kicad/10.0/scripting/plugins/kicad2ant/` |
| macOS | `~/Documents/KiCad/10.0/scripting/plugins/kicad2ant/` |

It's a classic action plugin (SWIG), so you don't need to enable the API or install any Python packages.
KiCad plans to drop the SWIG runtime in KiCad 11, so this version targets KiCad 10 only.

## Using it in KiCad

The antenna has to be a footprint, either from KiCad's `RF_Antenna` library or one of your own. Open the board
and click the kicad2ant button. The window stays open next to the editor.

1. Set **Mode** to *Check model* and click **Simulate**. A few seconds later you'll see the model, with the
   ground in grey, the antenna in orange and the port in magenta. Make sure the port is on the feed pad and the
   ground is where you expect. It's worth doing this every time.
2. Switch to *Fast* and simulate. It gives S11, Zin, the resonance and the −10 dB band in seconds to a
   minute, so use it for every tuning step.
3. Use *Coarse* to confirm the version you settled on. It adds gain, efficiency and the pattern, and takes minutes.
4. Use *Fine* for the numbers you report. It takes much longer and can use several GB of memory on a big board.

When a run ends the window switches to the **Results** tab: the summary, and a **Plot** list with S11 / Zin,
Smith, Pattern and Model. Click a plot to open it full size.

### Which mode?

| Mode | What it does | Use it |
|---|---|---|
| Check model | builds the model and draws it, no simulation (seconds) | first, to see the port and the ground |
| Fast | rougher model: S11, Zin, resonance and the −10 dB band, no gain or pattern | for each tuning step |
| Coarse | also directivity, efficiency, gain and pattern | to confirm the version you chose |
| Fine | finer mesh, runs to −50 dB (much longer, several GB) | for the numbers you report |

Measured on the two example boards (one run at a time, Windows laptop):

| Board | Fast | Coarse |
|---|---|---|
| `examples/ti_ifa` | 26 s, resonance 2391 MHz | 8 min, 2413 MHz |
| `examples/openems_ifa` | 13 s, 2408 MHz | 3.5 min, 2438 MHz |

Fast's resonance comes out about 1 % below Coarse.

`examples/openems_ifa` is the antenna from openEMS's own `inverted_f.m` example, drawn as a KiCad board, so
the two can be compared directly:

| | openEMS `inverted_f.m` | kicad2ant Coarse | kicad2ant Fast |
|---|---|---|---|
| resonance | 2420 MHz, −29.8 dB | 2438 MHz (+0.7 %), −28.2 dB | 2408 MHz (−0.5 %), −21.1 dB |
| Zin at 2450 MHz | 49.4 + 8.3j Ω | 52.1 + 4.8j Ω | 38.5 + 8.1j Ω |
| directivity, radiation efficiency | 2.55 dBi, 99 % | 2.83 dBi, 98–99 % | not computed |

Coarse lands within 1 % of openEMS's own model. Fast gets the resonance about right but the match and the
impedance only roughly, which is why it's for tuning steps and not for the numbers you report. While tuning,
compare Fast runs with Fast runs, then check the final version with Coarse.

The fields:

| Field | What it does | Default |
|---|---|---|
| Mode | Check model, Fast, Coarse or Fine (see [Which mode?](#which-mode)) | Fast |
| f0 (MHz) | design frequency | 2440 |
| Band from / to (MHz) | your target band. The result tells you if the −10 dB band covers it | 2400–2483.5 at 2440 MHz, otherwise f0 ± 2 % |
| Ground net | the board's ground net | detected, see [below](#how-it-finds-the-antenna-the-feed-and-the-ground) |
| Feed | click the feed pad in the editor, then *Use selected pad*. *Auto* resets it | pad 1 of the antenna footprint |
| Octave | path to `octave-gui.exe` or `octave` | detected |
| openEMS folder | where openEMS lives | detected |
| Output in | where the `<board>_kicad2ant` run folder goes | next to the board file |
| Show the 3D model… | opens the model in openEMS's viewer (AppCSXCAD) when the run finishes: copper, board, port and mesh. With *Check model* that's a few seconds | off |
| Theme | System, Light or Dark | System |

During a run you see the current phase, a progress bar (taken from openEMS's log) and the elapsed time.
**Stop** kills the run and everything it started. When it's done, the window shows the results and the S11
plot. **Open results folder** takes you to the output files, and **Open run folder** to the model:

| File | What it is |
|---|---|
| `antenna_geom.m` | geometry read from the board: antenna, ground, stackup, outline, port |
| `antenna_sim.m` | a copy of the openEMS model and run script that was used |
| `run_sim.m` | this run's settings. Run it in Octave to repeat the simulation, or edit it first |
| `board.kicad_pcb` | the copy of the board that was simulated |
| `sim_<mode>/` | openEMS's files: `antenna.xml` (the model), the log and field dumps |

Two things to know:

- Your board file isn't touched. Simulate refills the zones (same as pressing **B**), saves a copy of the
  board as it is on screen into the run folder, and simulates that copy.
- The run folder is `<board>_kicad2ant/` next to the board, or wherever **Output in** points. openEMS can't
  handle spaces in paths, so if your board's path has one, the run goes into `kicad2ant/<board>_<id>/` under
  your local app-data folder (Windows) or your home folder (Linux, macOS). The window tells you where.

If a run fails, the red line explains why. The usual causes are listed under [Troubleshooting](#troubleshooting).

## Using it from the command line

Fill the zones in KiCad (press **B**) and save first. Then:

```
python scripts/kicad2ant.py myboard.kicad_pcb --mode dry                    # check the model first
python scripts/kicad2ant.py myboard.kicad_pcb                               # fast: S11 only, under a minute
python scripts/kicad2ant.py myboard.kicad_pcb --mode coarse                 # adds gain and pattern, minutes
python scripts/kicad2ant.py myboard.kicad_pcb --mode fine                   # numbers you report
python scripts/kicad2ant.py myboard.kicad_pcb AE2 --f0 868 --band 863 870   # another antenna and band
```

On Windows you can also drop a `.kicad_pcb` onto `scripts/kicad2ant.bat` for a fast 2.4 GHz run.

| Option | Default |
|---|---|
| `REF` | the single footprint with an `AE*` / `ANT*` reference, or with "antenna" in its library name |
| `--mode dry\|fast\|coarse\|fine` | `fast`. `dry` only builds the model and its picture |
| `--f0 MHz`, `--band LO HI` | 2440 and 2400–2483.5. For any other f0 the band is f0 ± 2 % |
| `--feed PAD` | pad `1` of the antenna footprint |
| `--gnd NET` | detected, see below |
| `--out DIR` | `myboard_kicad2ant/` next to the board. No spaces in the path |
| `--post` | redo only the post-processing on saved fields, e.g. after adding `measured.s1p` |
| `--view` | open the 3D model in AppCSXCAD when the run finishes |

Full option list and model details: [docs/USAGE.md](docs/USAGE.md).

## How it finds the antenna, the feed and the ground

- Antenna: the one footprint whose reference is `AE` or `ANT` plus a number, or whose library name contains
  "antenna". If it finds none or several, it stops and lists them. Then give the reference on the command
  line, or in the plugin click a pad of the antenna and press *Use selected pad*. The plugin accepts any
  footprint you pick, but asks you to confirm if the name doesn't look like an antenna.
- Feed: pad `1` of that footprint, or the pad you picked.
- Ground net, in this order: the net you gave it, then the net on the antenna's pad `2` (an IFA's shorting
  pin), then a net named `GND`, then the largest zone net with a common ground name (`AGND`, `GNDA`, `DGND`,
  `VSS`, `0V`, …, including inside a sheet path like `/rf/GND`). The result says which net it used.
- Port: from the feed pad straight down or up to ground copper on another layer. If there isn't any, it goes
  sideways from the pad edge to the nearest ground copper on the same layer. If that copper is only diagonal
  from the pad, it stops, because that port wouldn't actually touch ground.

## Results

Everything lands in `<run folder>/results/`:

| File | What it is |
|---|---|
| `<REF>_geometry.png` | the model, layer by layer. Look at this first |
| `<REF>_<mode>_summary.txt` | resonance, −10 dB band vs. your target, Zin at f0, convergence, gain table (not in Fast) |
| `<REF>_<mode>_s11_zin.png` | S11 and input impedance around f0, with the target band shaded and the resonance marked |
| `<REF>_<mode>_smith.png` | Smith chart with f0 and band edges marked |
| `<REF>_<mode>_pattern.png` | pattern cuts in the xz, yz and xy planes (not in Fast) |
| `<REF>_<mode>.s1p` | Touchstone S11 at the feed pad, for matching-network design |
| `<REF>_<mode>_pattern.vtk` | 3D pattern for ParaView (not in Fast) |

To compare against a measurement, save your VNA's 1-port file as `measured.s1p` in the run folder and rerun
with `--post`. It's drawn over the S11 and Smith plots.

Reading the result: if resonance is away from f0, the antenna is the wrong length and needs retuning. If it
resonates at f0 but S11 is poor, it needs a matching network, which you can design from the `.s1p`.

## Known limits

Mention these whenever you share a result.

- Only the antenna footprint and the ground net are modelled. Other nets, components and any enclosure are
  left out. The board sits bare in air.
- The matching network and feed line aren't modelled. S11 is at the feed pad.
- Copper is lossless, so radiation efficiency only includes dielectric loss.
- Chip antennas can't be modelled, since they're a component and not copper.
- It won't run below 100 MHz (NFC and other low-frequency loops). An FDTD solver would need millions of
  timesteps there.
- No spaces in the openEMS path or the run folder path. That's an openEMS limitation.
- Fast and Coarse runs show trends. Do the final tuning on the real board with a VNA.
- Not tested yet: Linux, macOS, paths with non-English characters, and KiCad's Flatpak build (not supported).

## Troubleshooting

| Red line says | Fix |
|---|---|
| `Octave not found` | install Octave, or set **Octave** in the window (`OCTAVE` on the command line) |
| `openEMS Octave scripts not found` | install openEMS, or set **openEMS folder** (`OPENEMS`) |
| `openEMS is in a path with a space` | move openEMS to a folder without spaces |
| an error mentioning `h5readatt_octave` or `setup` | run `setup` once in openEMS's `matlab` folder, using the Octave kicad2ant uses |
| `cannot pick the antenna footprint` | click a pad of the antenna, then *Use selected pad* (or give `REF`) |
| `needs exactly one pad "1" as the feed` | pick the feed pad with *Use selected pad* (or `--feed`) |
| `cannot tell the ground net` | type it into **Ground net** (or `--gnd`). The message lists nets that have zones |
| `no filled … zones` | the ground net has no zone copper. Check the net name, press **B**, save |
| `Edge.Cuts outline is not closed near …` | close the gap in the board outline at that point |
| `the nearest … copper to feed pad … is diagonal` | put ground copper straight across from the feed pad, or under it |
| `no stackup` warning, or wrong εr | set up **Board Setup > Physical Stackup** |
| `NOT CONVERGED` in the result | the run hit its step limit and the numbers aren't reliable. Check the model picture |
| `another kicad2ant run is using …` | a run is already going in that run folder. Wait for it, or give another `--out` |

Anything else: click **Copy log** and paste the log into an issue.

## For developers

```
python scripts/test_extract.py     # board reader: stackup, outline, copper, ground, port, error messages
python kicad_plugin/test_core.py   # plugin helpers
python kicad_plugin/build_pcm.py   # build the plugin package into dist/
```

Both tests print `OK`, need only Python 3, and run on every push (`.github/workflows/test.yml`). The package
uses KiCad's Plugin and Content Manager layout (`metadata.json`, `plugins/`, `resources/icon.png`). The build
also writes `dist/metadata_gitlab_submission.json`, which is the metadata plus the download fields KiCad's
addon repository wants.

| Path | What it is |
|---|---|
| `scripts/kicad2ant.py` | command line: extracts, finds Octave and openEMS, runs |
| `scripts/extract_antenna.py` | `.kicad_pcb` → `antenna_geom.m` |
| `scripts/antenna_sim.m` | model, mesh, openEMS run, post-processing |
| `scripts/fp_tools.py` | tuning helpers for a board copy (runs in KiCad's Python): refill zones, save a board footprint to a library |
| `kicad_plugin/kicad2ant_plugin/` | the plugin: `__init__.py` (window), `core.py` (helpers) |
| `kicad_plugin/metadata.json`, `build_pcm.py` | package metadata and builder |
| `examples/ti_ifa/` | example board with coarse results |
| `examples/openems_ifa/` | openEMS's own `inverted_f.m` antenna as a KiCad board, with fast and coarse results |
| `SKILL.md` | the Claude Code skill |
| `CHANGELOG.md` | changes per version |

## Licence and credits

GPL-3.0-or-later, see [LICENSE](LICENSE). openEMS and CSXCAD are © Thorsten Liebig and contributors.

Some design ideas came from [kicad2ems](https://github.com/lowprocess/kicad2ems) (air box size, excitation
beyond the band, gain table) and Antmicro's [gerber2ems](https://github.com/antmicro/gerber2ems) (VNA overlay,
Smith chart, convergence check). No code was copied from either.
