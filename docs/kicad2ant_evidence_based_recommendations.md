# kicad2ant — Evidence-Based Architecture Recommendations

**Review basis:** `ARCHITECTURE.md` supplied by the project owner, the accompanying earlier `MESHING.md`, official openEMS and KiCad documentation, and the public implementations of PyEMS, pcbmodelgen and easyMesh4openEMS.

**Purpose:** Identify changes that have a defensible technical reason, distinguish them from optional enhancements, and define tests that would demonstrate whether each change improves kicad2ant.

---

## 1. Executive recommendation

Do **not** rewrite the overall architecture. The current division—KiCad/CLI front ends, Python geometry extraction and meshing, Octave model construction and openEMS execution, then post-processing—is sound for this project.

The strongest changes are:

1. **Add a mandatory mesh validator and mesh report before every FDTD run.**
2. **Separate exact geometric alignment constraints from lateral metal-edge refinement constraints.** In particular, distinguish the Z-plane alignment required by zero-thickness copper sheets from the X/Y 1/3–2/3 edge treatment recommended by openEMS.
3. **Make the mesher feature-aware and cost-aware:** resolve traces, gaps, vias, ports, dielectric interfaces and air using different rules; estimate the resulting cell count and smallest cell before launching the solver.
4. **Validate port geometry and NF2FF/PML clearance from the final mesh, in physical units.**
5. **Add per-layer dielectric stackup data where KiCad provides it, and warn when the stackup is incomplete.**
6. **Add reproducible run metadata and regression tests.** Keep the current `.m` geometry export unless a measured problem justifies changing it.
7. **Plan the KiCad plugin migration from SWIG/ActionPlugin to the IPC API.** This is a compatibility issue, not an optional architectural refinement.

Do not implement all advanced features at once. First make the existing mesh and model auditable, then use the AN043 MIFA case and VNA comparisons to justify further changes.

---

## 2. Evidence scale

- **A — Direct technical evidence:** Official openEMS or KiCad documentation specifies the behavior or constraint.
- **B — Implementation precedent:** A relevant open-source project implements the approach, but that alone does not prove it improves kicad2ant.
- **C — Engineering recommendation:** A sound reliability or maintainability practice; the project's own tests must demonstrate the benefit.

A recommendation can be important even when its evidence is C. The evidence label indicates what has actually been demonstrated, not the importance of the feature.

---

## 3. Recommended changes, ranked

### R1. Add a mesh validation gate before `RunOpenEMS`

**Priority:** P0 — implement first  
**Evidence:** A (openEMS) + B (pcbmodelgen)

#### Why this change is justified

openEMS explicitly warns that its smoothing ratio is not guaranteed as a post-condition. `SmoothMesh` / `SmoothMeshLines` can produce a neighbouring-cell ratio larger than the requested ratio, and the documentation instructs users to inspect the final mesh with `AnalyseMesh`. Therefore, a mesher that merely requests a ratio of 1.3 or 1.5 cannot assume that the final grid meets it.

The pcbmodelgen project also documents that its automatic mesh generation may fail to satisfy requested minimum-cell and neighbour-difference parameters for some PCB geometries; it exposes warnings in the generated output and tells users to evaluate the resulting mesh. This is direct precedent for treating mesh validation as a separate stage rather than assuming generation succeeded.

#### What to add

Create a Python `validate_mesh()` stage after `mesher.build()` and before writing the final geometry file. It should check:

- Each axis is finite, sorted and strictly increasing.
- No zero or negative cell widths exist.
- Minimum and maximum cell widths are reported per axis.
- Worst adjacent-cell ratio is measured per axis and globally.
- All mandatory coordinates (copper layer Z planes, dielectric interfaces, port alignment coordinates, model bounds) survive mesh generation.
- Required trace/gap resolution constraints are actually met after merging and smoothing.
- All mesh lines lie within the intended simulation bounds.
- PML cell count and NF2FF placement are consistent with the final grid.
- The minimum cell size is reported because it constrains the FDTD time step.

The validator should distinguish **error**, **warning** and **informational** conditions. A missing copper plane or invalid port alignment should fail the run. A grading ratio slightly above the requested target may be a warning or failure according to an explicit mode policy.

#### Suggested outputs

`mesh_report.json` plus a concise human-readable summary containing:

- `nx`, `ny`, `nz`, total Yee-cell count `(nx-1)*(ny-1)*(nz-1)`;
- `dx_min/max`, `dy_min/max`, `dz_min/max`;
- worst adjacent-cell ratio for X/Y/Z;
- count of cells in antenna ROI and in the full domain;
- minimum gap/trace resolution statistics;
- mandatory-line preservation results;
- estimated memory and mesh warnings;
- final NF2FF-to-PML distance.

#### Acceptance test

For every saved mesh fixture, validate the actual final mesh—not only the inputs to the smoother. Add a regression fixture where the smoother is asked for ratio 1.3 but the resulting final mesh contains a larger jump. The validator must report the actual jump.

**Convincing reason to change:** openEMS itself says the requested smoothing ratio is not a post-condition. This is not merely a software-design preference.

---

### R2. Separate Z-plane alignment from X/Y conductor-edge treatment

**Priority:** P0 — verify and correct current behavior  
**Evidence:** A (openEMS)

#### Why this change is justified

The openEMS mesh documentation specifies two different requirements:

1. A zero-thickness 2D metal object must coincide with an exact mesh line in the axis normal to that sheet. For a horizontal PCB copper layer, this means the copper Z height must be an exact Z mesh coordinate; otherwise the sheet may be ignored.
2. In the plane of the conductor, openEMS recommends the 1/3–2/3 edge rule around metal boundaries. It explains that simply aligning a mesh line exactly with a lateral conductor edge can degrade FDTD accuracy due to strong edge fields.

These are not contradictory. The first is the location of the zero-thickness sheet in Z; the second is how the mesh resolves the sheet's lateral edges in X/Y.

#### What to change or verify

Audit the current statement in `ARCHITECTURE.md` that the mesher “puts lines exactly on the copper edges.” Make the implementation and documentation explicit about which axis is intended.

- **Z:** Preserve an exact mesh plane at every zero-thickness copper layer height.
- **X/Y:** For supported straight metal edges, generate the appropriate 1/3–2/3 offset lines rather than universally forcing a line onto every lateral copper boundary.
- **Ports and vias:** Use their own alignment rules; do not apply the generic copper-edge rule blindly.
- **Diagonal/curved geometry:** Document that Cartesian-grid representation is approximate and validate it by convergence; do not claim exact edge conformity from a rectilinear mesh.

The 1/3–2/3 offsets must be represented as protected mesh constraints. Do not allow a later generic merge or smoothing pass to collapse them. openEMS documents a `highres` workaround because smoothing can otherwise subdivide or undo carefully placed 1/3–2/3 cells.

#### Acceptance test

Use a simple microstrip or copper-strip reference geometry and compare:

- edge-aligned XY mesh;
- 1/3–2/3 XY mesh;
- a finer reference mesh.

Compare S11, input impedance and propagation/phase behaviour where appropriate. Repeat for the AN043 MIFA geometry. Keep the change only if it improves agreement or reaches the same accuracy with fewer cells.

**Convincing reason to change:** this is an explicit openEMS meshing recommendation, not an aesthetic preference.

---

### R3. Make mesh constraints explicit and typed

**Priority:** P0/P1  
**Evidence:** A (openEMS) + B (PyEMS/easyMesh)

#### Why this change is justified

The current architecture already distinguishes copper geometry, ports, vias, dielectric layers and the simulation boundary. These entities do not all have the same mesh requirements. openEMS separately specifies sheet-plane alignment, port alignment, wavelength resolution, spatial resolution and conductor-edge treatment.

PyEMS demonstrates one practical approach: it builds bounded regions and classifies them as metal, nonmetal or air, then generates lines per region with material-dependent spacing and 1/3–2/3 handling at metal/nonmetal interfaces. It uses geometric-series spacing to transition across each bounded region. PyEMS also acknowledges an issue in its region-classification implementation, so copy the design idea, not its code blindly.

easyMesh4openEMS is another useful reference for material-aware meshing, edge/gap/diagonal heuristics, port hints and PML-aware boundary meshing. It operates on Python openEMS/CSXCAD bindings, so it is an algorithm reference rather than a drop-in replacement for this Octave pipeline.

#### What to add

Represent mesh inputs as typed constraints, for example:

- `SHEET_PLANE_Z` — exact Z coordinate for zero-thickness copper;
- `DIELECTRIC_INTERFACE` — exact layer interface;
- `PORT_ALIGNMENT` — exact coordinates needed by the selected port representation;
- `VIA_AXIS` / `VIA_SURFACE` — via-specific refinement;
- `METAL_EDGE_XY` — edge refinement rule and metal side;
- `GAP_BOUNDARY` — preserve a narrow gap and its two boundaries;
- `BACKGROUND_RESOLUTION` — soft mesh density target;
- `AIR_AND_PML_BOUNDARY` — outer domain and absorber constraints.

Each constraint should carry a source object ID, layer/material, priority, tolerance and whether it is immutable. The mesher can then merge background suggestions without deleting physical constraints.

#### Acceptance test

Add unit tests that prove:

- a background line cannot delete a port or sheet-plane coordinate;
- a duplicate line can be merged only if it is geometrically equivalent within tolerance;
- a 1/3–2/3 pair remains intact after smoothing;
- a close gap is not silently collapsed;
- each validation error identifies the originating KiCad object where possible.

**Convincing reason to change:** openEMS has different hard-alignment requirements for sheets and ports, while PyEMS demonstrates material/region-aware mesh generation.

---

### R4. Make resolution geometry-driven, but do not hard-code “four cells everywhere”

**Priority:** P1  
**Evidence:** A (openEMS) + B (PyEMS/easyMesh)

#### Why this change is justified

openEMS states that resolution must account for both wavelength and the smallest important geometric features, and recommends using fine cells only near important details while using a coarser mesh elsewhere. It gives `lambda/10` as a rule of thumb, not a guarantee of accuracy. It also explains that the smallest mesh cell limits the FDTD time step through the CFL-type timestep condition.

Therefore, a single global `cell_ant` is not a sufficient description of local requirements. However, “3–4 cells across every trace” should be treated as a starting heuristic, not a universal law. The final requirement should be established using a mesh-convergence study for representative antenna structures.

#### What to add

Calculate resolution locally from:

- trace width;
- gap width;
- via diameter and annular ring;
- feed-pad size and port dimensions;
- substrate thickness and layer interfaces;
- highest simulation frequency and dielectric properties;
- user-selected accuracy preset.

Use separate settings for metal, dielectric and air regions, similar to PyEMS' `metal_res` and `nonmetal_res` concept. Give the user a maximum cell count or estimated runtime budget so that a small feature does not unexpectedly create an impractical mesh.

#### Important openEMS limitation

openEMS' standard Cartesian mesh is rectilinear. Adding an X or Y coordinate creates a grid plane spanning the domain in the other directions; refinement is not a fully local unstructured triangle/tetrahedron mesh. Also, the smallest cell can constrain the timestep globally. Consequently, a mesh with very dense local features can become expensive even when the physical refined region is small.

Do not promise adaptive/local refinement in the AMR sense unless the implementation actually uses a supported subgridding method. For this project, call it **geometry-aware nonuniform Cartesian meshing**.

#### Acceptance test

For AN043 MIFA and at least one antenna with diagonal/curved copper:

- generate coarse, medium and fine meshes;
- record total cell count and smallest cell;
- compare S11, resonance, bandwidth and Zin;
- report the change in each RF metric between successive mesh levels;
- select the coarsest mesh that meets stated tolerances.

**Convincing reason to change:** openEMS documents both the spatial-resolution requirement and the global timestep penalty from the smallest cell.

---

### R5. Validate port geometry as a first-class object

**Priority:** P0/P1  
**Evidence:** A (openEMS)

#### Why this change is justified

openEMS documents that ports must align with the mesh: along an axis, the port must be either one-dimensional and lie on a mesh line, or two-dimensional and intersect/overlap two mesh lines (one cell). Its port documentation also explains that the selected port creates excitation, resistance, voltage and current probes, so port placement affects the measured waves and reference impedance.

The current architecture describes a 50-ohm lumped line at the feed-pad centre. This is preferable to leaving the port representation vague, but the generated port still needs an explicit geometry/alignment check.

#### What to add

For each port, report:

- start and stop coordinates;
- direction and axis;
- physical length and cross-section;
- exact mesh indices used by the port;
- whether the port is a line or box in each axis;
- reference resistance;
- measurement-plane position, if applicable;
- whether the port crosses the intended feed-to-ground region and no unintended conductor.

Keep port convergence separate from mesh convergence. When comparing a new mesh with a reference result, do not change the port representation at the same time.

#### Acceptance test

Add a simple known feed geometry and compare its impedance and S-parameters across mesh levels while keeping the port coordinates and port type fixed. The validator should fail if the port cannot be mapped to the required mesh cells.

**Convincing reason to change:** openEMS explicitly specifies port/mesh alignment requirements; incorrect port mapping can invalidate the port or alter the measured response.

---

### R6. Check NF2FF clearance from the PML using physical distance

**Priority:** P1  
**Evidence:** A (openEMS)

#### Why this change is justified

The openEMS NF2FF documentation says the NF2FF box must enclose all radiating structures, must not intersect metal or lossy material, and must be at least a few cells away from the PML. The current architecture says the NF2FF box is placed a fixed ten mesh indices from each boundary while PML_8 is used.

A fixed cell-index offset does not guarantee a fixed physical clearance. Depending on the final mesh and PML placement, ten indices from the outer boundary may leave very little ordinary mesh between the NF2FF surface and the PML. This should be audited rather than assumed safe.

#### What to add

After final mesh generation:

- identify the first PML cell on each side;
- place or validate the NF2FF surface relative to that PML boundary;
- calculate and report the actual physical distance in mm;
- ensure the NF2FF box encloses all radiating copper and relevant lossy materials;
- ensure it does not intersect copper, dielectric-lossy regions or the PML;
- make a second run with greater air/PML clearance for a boundary-sensitivity check.

#### Acceptance test

Run the same antenna with at least two larger boundary clearances. Verify that S11 and far-field metrics remain within project-defined tolerances. If they change materially, the original boundary was too close or the NF2FF placement was invalid.

**Convincing reason to change:** the openEMS NF2FF documentation states these geometric requirements directly.

---

### R7. Parse and preserve per-layer dielectric stackup data

**Priority:** P1  
**Evidence:** A (KiCad format) + B (PyEMS)

#### Why this change is justified

KiCad's documented board file format includes stackup layer thickness, material, relative permittivity and loss tangent. PyEMS identifies independent dielectric properties for each substrate layer as a needed PCB microwave feature (listed as planned in the inspected repository documentation). This supports a layered material model rather than assuming one generic FR-4 value for the entire board.

#### What to add

- Parse each dielectric layer separately when the board contains stackup data.
- Preserve thickness, material label, epsilon-r and loss tangent as distinct fields.
- Map each dielectric interval to the correct Z coordinates.
- Allow a user override when manufacturer laminate data is more accurate than the KiCad label.
- Warn when the board stackup omits RF-relevant values; do not silently substitute generic material data without recording the assumption.

Do not add soldermask or copper roughness models as unconditional defaults. Make them optional model features because they require reliable thickness/material data and should be validated against a measured structure.

#### Acceptance test

Create a multilayer fixture with two different dielectric layers and verify that the generated model uses distinct material properties and correct Z boundaries. Compare results against a single-material approximation to quantify whether this matters for the test design.

**Convincing reason to change:** the KiCad file format already exposes these stackup fields; the extractor can preserve information that would otherwise be lost.

---

### R8. Add a run manifest and reproducibility checks; keep `antenna_geom.m` for now

**Priority:** P1  
**Evidence:** B (pcbmodelgen) + C (engineering reproducibility)

#### Why this change is justified

The current architecture stores the board copy, generated geometry, simulation script, run settings, openEMS output and results in one run folder. This is a good basis for reproducibility.

A direct KiCad-to-openEMS precedent, pcbmodelgen, generates Octave function files for both geometry and mesh lines. Therefore, there is no strong evidence that kicad2ant should replace its generated `antenna_geom.m` with JSON or MAT immediately. Such a format change would add migration work without proving a technical benefit.

The more defensible addition is a sidecar `run_manifest.json` recording the inputs and exact settings used for the run.

#### What to record

- source board SHA-256 and board-file version;
- antenna reference, feed pad, ground net and extracted-geometry hash;
- geometry schema version and mesher version / Git commit;
- mesh mode, all mesh parameters, final cell counts and mesh hash;
- stackup values and material overrides;
- excitation band, end criterion, boundary conditions and PML settings;
- port type, coordinates and reference impedance;
- openEMS, CSXCAD, Octave, Python and KiCad versions;
- simulation status, start/end time and result file hashes.

Before `--post` reuses field dumps, compare the stored manifest with the current geometry and simulation settings. Refuse to reuse incompatible field data.

#### Acceptance test

Change one relevant input at a time (board geometry, mesh setting, port or solver setting). Verify that the manifest identifies the changed input and that `--post` refuses stale/incompatible simulation data.

**Convincing reason to change:** this materially improves repeatability and prevents accidental mixing of fields and geometry from different runs. The exact manifest format is a project engineering choice, not an openEMS requirement.

---

### R9. Plan the KiCad plugin migration to the IPC API

**Priority:** P1 — compatibility roadmap  
**Evidence:** A (KiCad official developer documentation)

#### Why this change is justified

The architecture currently uses `pcbnew.ActionPlugin` and SWIG-based Python bindings. KiCad's official developer documentation marks the SWIG PCB Python bindings deprecated as of KiCad 9 and says they are planned for removal in KiCad 11. KiCad recommends the IPC API for modern plugin development. The IPC API is intended as a stable interface that does not change with KiCad internal refactoring.

The IPC API has version-specific limitations: KiCad 9 and 10 require a running GUI instance; headless support via `kicad-cli` is documented for KiCad 11. Therefore, migration should be designed around the supported KiCad versions, not done as an untested one-shot replacement.

#### What to change

- Keep the standalone CLI and direct `.kicad_pcb` parser independent of `pcbnew`.
- Put all plugin-to-KiCad operations behind a small adapter interface.
- Keep the current KiCad 10 SWIG adapter for existing support if needed.
- Add an IPC adapter for newer KiCad versions and verify the APIs it needs (load board, selected footprint/pad, refill zones, save a copy, progress/results).
- Keep board analysis, geometry extraction and meshing in the existing Python CLI pipeline.

#### Acceptance test

Run the same board through CLI and plugin paths and compare extracted geometry hashes. Test supported KiCad versions explicitly. Do not claim compatibility with a version until the full plugin workflow has passed.

**Convincing reason to change:** this is based on KiCad's official deprecation/removal roadmap, not speculation about future API churn.

---

## 4. Features I would defer

These are potentially valuable, but there is not enough project-specific evidence to justify them before the P0/P1 work.

### A. True adaptive mesh refinement (AMR) or subgridding

Do not advertise the current or planned Cartesian line-density heuristics as AMR. Standard openEMS Cartesian meshing uses a global rectilinear grid; its official documentation describes cylindrical subgrids as a separate feature. First quantify the actual cell/time-step bottleneck and investigate whether a supported subgridding method solves that bottleneck for this antenna class.

### B. Full board copper and every component by default

More geometry is not automatically more accurate if it is inaccurate, and every added object can add mesh constraints and computational cost. Add optional nearby-net / component-metal modelling only when measured-versus-simulated results show that omitted structures are materially affecting the antenna.

### C. Copper roughness and finite-conductivity models by default

These can matter at RF, but require validated process/material inputs. Add as selectable model features and demonstrate their effect against measurements before making them defaults.

### D. Replace Octave with Python

There is no strong evidence that this is needed. openEMS supports both Python and Octave interfaces, and pcbmodelgen demonstrates an established KiCad-to-Octave-function workflow. A rewrite would increase risk without addressing the main meshing and model-validation issues.

### E. Replace `antenna_geom.m` with JSON/MAT immediately

Do not change this now. Add a versioned contract and manifest first. Revisit only if generated `.m` files become a demonstrated source of precision, size, debugging or compatibility problems.

---

## 5. What should count as proof that a change is better?

Use a fixed regression set and compare each candidate against a baseline.

### Required reference cases

1. TI AN043 MIFA: existing project regression geometry.
2. Straight microstrip / feed geometry: checks edge and port meshing.
3. Narrow-gap meandered IFA: checks local gap handling and cell merging.
4. Diagonal/arc-heavy antenna: checks Cartesian approximation and geometry conversion.
5. Multilayer board with distinct dielectric layers: checks stackup import and Z meshing.

### Keep variables controlled

When evaluating a mesher change, freeze geometry, material properties, port type/position, excitation, boundary conditions and solver version. Change only the mesh algorithm or mesh settings. When evaluating a port change, freeze the mesh. Do not change both in one comparison.

### Metrics to record

- Resonance frequency;
- minimum S11;
- S11 at the design frequency;
- -10 dB bandwidth;
- complex Zin at the design frequency;
- total Yee cells;
- minimum cell size and worst neighbour ratio;
- simulation runtime and peak memory;
- directivity, realized gain and radiation efficiency where NF2FF is valid;
- deviation from a reference S1P / reference XML model.

### Convergence criterion

A mesh preset is not “accurate” merely because it has 3 or 4 cells across a trace. Demonstrate convergence: refine the mesh while holding every other model parameter fixed, and show that the RF quantities of interest change by less than project-defined tolerances. Establish the tolerances from intended use (antenna tuning vs. pre-compliance vs. final correlation), not from convenience.

---

## 6. Proposed implementation sequence

### Phase 1 — trust the mesh (first)

- Add `mesh_report.json` and a Python validator.
- Audit exact copper Z alignment vs. lateral X/Y edge treatment.
- Classify hard constraints and soft mesh hints.
- Check port alignment and PML/NF2FF clearance.
- Add unit tests for every validator condition.

### Phase 2 — improve physical fidelity

- Add per-layer dielectric stackup parsing and warnings.
- Add feature-driven mesh sizing for trace, gap, via and feed regions.
- Add mesh cost / smallest-cell preflight warnings.
- Run AN043 and the other regression structures at multiple mesh levels.

### Phase 3 — make runs reproducible and maintainable

- Add `run_manifest.json` and content hashes.
- Reject stale field data during `--post`.
- Add numerical regression CI for a small, deterministic case where solver CI is practical.
- Add CLI/plugin geometry-hash equivalence tests.
- Design the KiCad IPC adapter and test against the supported KiCad versions.

### Phase 4 — optional advanced modelling

- Nearby copper / component conductors;
- soldermask and copper-loss models;
- uncertainty/tolerance analysis;
- advanced refinement only after performance and accuracy limitations are measured.

---

## 7. Source references

### Official openEMS documentation

- Mesh requirements, Cartesian/nonuniform grids, cell grading, 1/3–2/3 rule, zero-thickness plane alignment, port alignment, and CFL/timestep implications: https://docs.openems.de/en/stable/concepts/mesh.html
- `SmoothMesh` and algorithm choices: https://docs.openems.de/en/latest/octave/autogenerated/CSXCAD/SmoothMesh.html
- `AutoSmoothMeshLines`: https://docs.openems.de/en/latest/octave/autogenerated/CSXCAD/AutoSmoothMeshLines.html
- Ports and port alignment concepts: https://docs.openems.de/en/latest/concepts/ports.html
- Lumped port API: https://docs.openems.de/en/latest/octave/autogenerated/openEMS/ports.html
- Boundary conditions and PML clearance: https://docs.openems.de/en/stable/concepts/bc.html
- NF2FF setup and clearance: https://docs.openems.de/en/latest/concepts/nf2ff.html
- FAQ on very small cells and FDTD timestep: https://docs.openems.de/en/stable/faq.html

### Open-source implementation references

- PyEMS (automatic mesh generation; bounded-region / material classification, geometric-series spacing and edge treatment): https://github.com/matthuszagh/pyems
- pcbmodelgen (KiCad to Octave function files and mesh lines; zero-thickness metal, automatic mesh settings, warnings on unmet mesh constraints): https://github.com/jcyrax/pcbmodelgen
- easyMesh4openEMS (material-aware, edge/gap/diagonal, port and PML-aware automatic meshing): https://github.com/MustafaAlchalabi/easyMesh4openEMS

### Official KiCad documentation

- `.kicad_pcb` S-expression format, version field, objects, tracks/arcs/vias, zones and stackup: https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/index.html
- PCB Python binding deprecation and IPC API recommendation: https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/
- IPC API add-on developer guide and KiCad-version limitations: https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/

---

## 8. Bottom line

The evidence strongly supports improving **mesh validation, constraint handling, metal-edge treatment, port alignment, boundary/NF2FF checks, and stackup fidelity**. It also strongly supports planning the KiCad plugin's IPC migration.

The evidence does **not** support a wholesale Python/Octave rewrite, an immediate switch away from `antenna_geom.m`, unconditional inclusion of every PCB component, or calling the current approach true AMR.

The most defensible engineering strategy is to keep the architecture, make the generated mesh independently verifiable, and require each new algorithm to prove its benefit on fixed RF regression cases.
