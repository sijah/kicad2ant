% kicad2ant: PCB antenna from a KiCad board: S11, Zin, directivity / efficiency / gain over
% frequency, pattern.  Normally started by kicad2ant.py, which extracts antenna_geom.m (the antenna
% footprint's copper, the GND net's zone fills, tracks and vias, the stackup, the outline, the feed port)
% into the run folder and sets the variables below.
% Model: one dielectric per copper pair, copper as PEC sheets, GND vias / plated holes as PEC lines,
% 50 ohm lumped port at the feed pad, board in air or in a box-shaped plastic case (case_box), PML_8 on all sides.  Other nets' copper and the
% parts are not modelled.
% kicad2ant.py copies this file into the run folder next to antenna_geom.m and writes run_sim.m there
% with the run's settings: run('<run folder>/run_sim.m') in Octave runs it again. By hand:
%   res='coarse'; f0=2.44e9; band_t=[2400 2483.5]*1e6; run('<run folder>/antenna_sim.m')
% add skip_fdtd=1 to redo only the post-processing on saved fields.

close all; clc;
if ~exist('res', 'var'), res = 'fast'; end          % 'fast' (S11 only) while tuning, 'coarse' to confirm, 'fine' to report
if ~exist('skip_fdtd', 'var'), skip_fdtd = 0; end   % 1 = re-run post-processing on the saved fields
if ~exist('dry_run', 'var'), dry_run = 0; end       % 1 = build the model, write the XML and geometry plot, stop
if ~exist('run_dir', 'var'), run_dir = pwd; end     % holds antenna_geom.m; sim_<res>/ and results/ go here
if ~exist('f0', 'var'), f0 = 2.44e9; end            % design frequency (Hz)
if ~exist('fc', 'var'), fc = 0.4 * f0; end          % sweep f0 -/+ fc, unless f_lo / f_hi are given
if ~exist('f_lo', 'var'), f_lo = f0 - fc; end       % sweep start and stop (Hz); kicad2ant.py --set f_start / f_stop
if ~exist('f_hi', 'var'), f_hi = f0 + fc; end
fc = (f_hi - f_lo) / 2;
% the run settings kicad2ant.py writes into run_sim.m (mesher.py MODES, --set): these defaults are for a run by hand
if ~exist('npts', 'var'), npts = 801; end            % sweep points
if ~exist('nrts', 'var'), nrts = 300000; end         % step limit: a run that hits it did not converge (warned in the summary)
if ~exist('threads', 'var'), threads = 0; end        % openEMS threads, 0 = all
if ~exist('f_pat', 'var'), f_pat = 0; end            % pattern frequency (Hz), 0 = the resonance
if ~exist('pat_step', 'var'), pat_step = 5; end      % full-sphere far-field step (deg)
if ~exist('band_t', 'var'), band_t = [2400 2483.5] * 1e6; end   % target band: marked on plots, checked in the summary
if ~exist('match_db', 'var'), match_db = -10; end   % match limit (dB): the band with S11 below it must cover band_t
if ~exist('band_name', 'var'), band_name = ''; end  % the preset's name, for the summary
% plastic case: a box shell around the board [epsR tanD wall gap_side gap_top gap_bottom], mm, top = the F.Cu side;
% [] = the bare board in air
if ~exist('case_box', 'var'), case_box = []; end
here = run_dir;
assert(isempty(strfind(here, ' ')), 'the run folder path has a space (%s): nf2ff.exe is run unquoted, use another', here);
% openEMS v0.37+ in a path WITHOUT spaces; its matlab folder must hold h5*_octave.oct built for this
% Octave (run `setup` there once).  ems = '' uses openEMS already on the Octave path (.octaverc).
% ems: the Windows zip's folder (matlab/, CTB/), or the prefix of a source build (share/openEMS/matlab, share/CSXCAD/matlab)
if ~exist('ems', 'var'), ems = getenv('OPENEMS'); end
if ~isempty(ems)                   % ahead of old paths in .octaverc
  if exist(fullfile(ems, 'matlab'), 'dir'), addpath(fullfile(ems, 'matlab'), fullfile(ems, 'CTB'), '-begin');
  else, addpath(fullfile(ems, 'share', 'openEMS', 'matlab'), fullfile(ems, 'share', 'CSXCAD', 'matlab'), '-begin'); end
end
assert(exist('InitFDTD', 'file') == 2, ['openEMS Octave scripts not found: install openEMS, then give its folder ' ...
       '(OPENEMS, or openEMS folder in the plugin): the one holding matlab/ on Windows, the install prefix elsewhere']);
assert(exist(fullfile(here, 'antenna_geom.m'), 'file') == 2, 'no antenna_geom.m in %s: run kicad2ant.py', here);

physical_constants; unit = 1e-3;   % mm
clear geom; run(fullfile(here, 'antenna_geom.m'));
name = regexprep(geom.ref, '[^\w-]', '_');
% every picture gets the project and the run as a heading, and the software and date as a grey mark
if ~exist('project', 'var'), project = ''; end
if ~exist('k2a_ver', 'var'), k2a_ver = ''; end
if ~exist('board_txt', 'var'), board_txt = ''; end      % '1.6 mm, 2 copper layers, FR4 epsR 4.5, tanD 0.02' (kicad2ant.py)
if ~exist('board_short', 'var'), board_short = ''; end  % '1.6 mm FR4 epsR 4.5', in the heading
heading = strjoin([{project}(~isempty(project)), {sprintf('%s  %s', geom.ref, res)}, {board_short}(~isempty(board_short))], '  |  ');
mark = sprintf('kicad2ant %s  |  openEMS FDTD  |  %s', k2a_ver, datestr(now, 'yyyy-mm-dd HH:MM'));
% stamp(h, y): the heading at height y (0.96 top; the small model picture has no room above its titles: 0.03,
% just over the mark), the mark at the bottom left
stamp = @(h, y) [annotation(h, 'textbox', [0.01 y 0.98 0.04], 'string', heading, 'edgecolor', 'none', 'fontsize', 10, ...
                            'fontweight', 'bold', 'interpreter', 'none'), ...
                 annotation(h, 'textbox', [0.01 0 0.98 0.03], 'string', mark, 'edgecolor', 'none', 'fontsize', 8, ...
                            'color', [.55 .55 .55], 'interpreter', 'none')];

%% parameters
% the mesh itself is mesher.py's (cells per mode there)
if ~exist('end_crit', 'var'), end_crit = 10^(-4 - strcmp(res, 'fine') + strcmp(res, 'fast')); end   % -30 / -40 / -50 dB
% fast: S11 only. Larger cells (mesher.py), -30 dB, no far field. Same PML and lambda/4 air as coarse: MUR with
% lambda/8 air was 2.5 % off on the printed IFA and gave -9 dB for -21 dB on AN043
fast = strcmp(res, 'fast');
if ~exist('pattern', 'var'), pattern = ~fast; end    % far field: gain, efficiency, pattern
% the excitation reaches 30 % of the band past its top: the far field comes out wrong near the
% upper edge of the Gaussian's band while S11 still looks fine (kicad2ems, docs/maintenance.md)
f_ex = (f_lo + f_hi) / 2 + 0.3 * fc; fc_ex = 1.3 * fc;

%% model
FDTD = InitFDTD('NrTS', nrts, 'EndCriteria', end_crit);
FDTD = SetGaussExcite(FDTD, f_ex, fc_ex);
FDTD = SetBoundaryCond(FDTD, {'PML_8' 'PML_8' 'PML_8' 'PML_8' 'PML_8' 'PML_8'});
CSX = InitCSX();
zmax = max(geom.cu_z);
for k = 1:size(geom.diel, 1)       % one dielectric per copper pair, extruded over the outline
  d = geom.diel(k, :); m = sprintf('sub%d', k);
  CSX = AddMaterial(CSX, m);
  CSX = SetMaterialProperty(CSX, m, 'Epsilon', d(3), 'Kappa', d(4) * 2*pi*f0 * EPS0 * d(3));
  CSX = AddLinPoly(CSX, m, 1, 2, d(1), geom.outline', d(2) - d(1));
end
if ~isempty(geom.holes)            % cutouts: air over the dielectric
  CSX = AddMaterial(CSX, 'cutout'); CSX = SetMaterialProperty(CSX, 'cutout', 'Epsilon', 1);
  for k = 1:numel(geom.holes), CSX = AddLinPoly(CSX, 'cutout', 2, 2, 0, geom.holes{k}', zmax); end
end
CSX = AddMetal(CSX, 'gnd'); CSX = AddMetal(CSX, 'ant');
for k = 1:numel(geom.gnd), CSX = AddPolygon(CSX, 'gnd', 10, 2, geom.gnd{k}.z, geom.gnd{k}.pts'); end
for k = 1:numel(geom.ant), CSX = AddPolygon(CSX, 'ant', 10, 2, geom.ant{k}.z, geom.ant{k}.pts'); end
for k = 1:size(geom.lines, 1)      % GND vias and plated antenna holes: PEC lines
  L = geom.lines(k, :); CSX = AddBox(CSX, 'gnd', 10, [L(1:2) L(3)], [L(1:2) L(4)]);
end
o = geom.outline; bb = [min(o, [], 1) max(o, [], 1)];
co = [bb(1:2) 0 bb(3:4) zmax];     % what the air is measured from: the board, or the case's outside
if ~isempty(case_box)              % six plastic walls, below the board's priority (a gap of 0 touches it)
  assert(numel(case_box) == 6 && case_box(1) >= 1 && all(case_box(2:6) >= 0) && case_box(3) > 0, ...
         'case_box: [epsR tanD wall gap_side gap_top gap_bottom], epsR >= 1, wall > 0, the rest >= 0');
  w = case_box(3); ci = [bb(1:2) - case_box(4), -case_box(6), bb(3:4) + case_box(4), zmax + case_box(5)];
  co = ci + [-w -w -w w w w];
  CSX = AddMaterial(CSX, 'case');
  CSX = SetMaterialProperty(CSX, 'case', 'Epsilon', case_box(1), 'Kappa', case_box(2) * 2*pi*f0 * EPS0 * case_box(1));
  for a = 1:3
    hi = co(4:6); hi(a) = ci(a); CSX = AddBox(CSX, 'case', 0, co(1:3), hi);
    lo = co(1:3); lo(a) = ci(a+3); CSX = AddBox(CSX, 'case', 0, lo, co(4:6));
  end
end
% the port: a line along port_dir through the pad centre, as a commercial EM tool's; a port box over the whole pad cost
% 11 dB of match depth and +1 % in frequency on the AN043 reference (docs/MESHING.md section 7)
pk = find(abs(geom.port_dir) > 0.5); ps = (geom.port(1:3) + geom.port(4:6)) / 2;
gl = {geom.grid_x, geom.grid_y, geom.grid_z};   % a line port off the grid lines excites nothing: snap it onto them
for k = 1:3, [~, i] = min(abs(gl{k} - ps(k))); ps(k) = gl{k}(i); end
pe = ps;
ps(pk) = geom.port(pk); pe(pk) = geom.port(pk + 3);
[CSX, port] = AddLumpedPort(CSX, 5, 1, 50, ps, pe, geom.port_dir, true);

%% mesh: the grid lines come from mesher.py, written into antenna_geom.m by extract_antenna.py (lines on the copper
% edges, at least 3-4 cells across every trace and gap, cells growing by at most 1.3; docs/MESHER.md); 8 PML cells
% outside the air are added here
assert(isfield(geom, 'grid_x'), 'antenna_geom.m has no grid lines (made by an older kicad2ant): run kicad2ant.py again without --post');
fine = [geom.ant_box(1:2) - 3, geom.ant_box(3:4) + 3];   % the antenna region (the geometry plot zooms to it)
mesh.x = geom.grid_x; mesh.y = geom.grid_y; mesh.z = geom.grid_z;
% PML cells as big as the last air cell on that side (uniform, as PML wants), so there is no jump into it
for a = 'xyz', v = mesh.(a); mesh.(a) = [v(1) - (8:-1:1) * (v(2) - v(1)), v, v(end) + (1:8) * (v(end) - v(end-1))]; end
CSX = DefineRectGrid(CSX, unit, mesh);
ncell = numel(mesh.x) * numel(mesh.y) * numel(mesh.z);
dmin = min([diff(mesh.x) diff(mesh.y) diff(mesh.z)]);
rmax = max(cellfun(@(v) max([diff(v(2:end)) ./ diff(v(1:end-1)), diff(v(1:end-1)) ./ diff(v(2:end))]), {mesh.x, mesh.y, mesh.z}));
fprintf('%s mesh: %d x %d x %d = %.2f Mcells, smallest cell %.3f mm, worst neighbour ratio %.2f\n', res, numel(mesh.x), numel(mesh.y), numel(mesh.z), ncell/1e6, dmin, rmax);
% NF2FF box one cell inside the PML (lines 1..9 are its 8 cells), around the board and case (it must not cut the
% dielectric). 4 cells in was tried on AN043: D 2.47 dBi / eff 76 % against the reference's 2.13 / 90 %, which this gives
nb = [mesh.x(10) mesh.y(10) mesh.z(10) mesh.x(end-9) mesh.y(end-9) mesh.z(end-9)];
if pattern
  assert(all(nb(1:3) < co(1:3)) && all(nb(4:6) > co(4:6)), 'NF2FF box cuts the board or case: too little air (mesher.py)');
  [CSX, nf2ff] = CreateNF2FFBox(CSX, 'nf2ff', nb(1:3), nb(4:6));
end

%% geometry plot: every copper layer, whole board and around the antenna
out = fullfile(here, 'results'); [~,~] = mkdir(out);
nl = numel(geom.cu_name); h = figure('visible', 'off', 'position', [0 0 360*nl 720]);
for r = 1:2, for k = 1:nl
  subplot(2, nl, (r-1)*nl + k); hold on; axis equal; box on;
  title(sprintf('%s z=%.3f', geom.cu_name{k}, geom.cu_z(k)), 'interpreter', 'none');
  plot(o([1:end 1], 1), o([1:end 1], 2), 'k');
  if ~isempty(case_box) && r == 1, for c = {co, ci}, plot(c{1}([1 4 4 1 1]), c{1}([2 2 5 5 2]), 'c--'); end, end
  for j = 1:numel(geom.holes), hh = geom.holes{j}; plot(hh([1:end 1], 1), hh([1:end 1], 2), 'k'); end
  for j = 1:numel(geom.gnd), g = geom.gnd{j}; if strcmp(g.layer, geom.cu_name{k}), fill(g.pts(:,1), g.pts(:,2), [.75 .75 .75], 'edgecolor', 'none'); end, end
  for j = 1:numel(geom.ant), g = geom.ant{j}; if strcmp(g.layer, geom.cu_name{k}), fill(g.pts(:,1), g.pts(:,2), [.85 .35 .1], 'edgecolor', 'none'); end, end
  if ~isempty(geom.lines), plot(geom.lines(:,1), geom.lines(:,2), 'b.'); end
  p = geom.port;
  if geom.cu_z(k) >= p(3) - 1e-6 && geom.cu_z(k) <= p(6) + 1e-6
    plot(p([1 4 4 1 1]), p([2 2 5 5 2]), 'm-', 'linewidth', 2);
  end
  if r == 2, axis([fine(1) fine(3) fine(2) fine(4)]); end
end, end
stamp(h, 0.03); print(h, fullfile(out, [name '_geometry.png']), '-dpng', '-r250');   % sharp when the Results tab draws it large

%% run
Sim_Path = fullfile(here, ['sim_' res]); Sim_CSX = 'antenna.xml';
P = struct('geom', geom, 'f0', f0, 'fc', fc, 'f_ex', f_ex, 'fc_ex', fc_ex, 'mesh', mesh, 'end_crit', end_crit, 'pattern', pattern);
pfile = fullfile(Sim_Path, 'params.mat');
files = {fullfile(out, [name '_' res '_summary.txt']), fullfile(out, [name '_' res '.s1p'])};
old = dir(files{2});   % keep the result this run replaces in history/, named by when it was made, for the overlay
if ~skip_fdtd && ~dry_run && ~isempty(old) && old.bytes > 0
  [~,~] = mkdir(fullfile(here, 'history'));
  % not copyfile: on Windows it runs xcopy, which asks "file or directory?" and hangs with no console
  fid = fopen(fullfile(here, 'history', [name '_' res '_' datestr(old.datenum, 'yyyymmdd-HHMMSS') '.s1p']), 'w');
  fwrite(fid, fileread(files{2})); fclose(fid);
end
for k = 1:2, fid = fopen(files{k}, 'a'); assert(fid > 0, 'cannot write %s (open in another program?)', files{k}); fclose(fid); end
t_run = 0;
if dry_run
  [~,~] = mkdir(Sim_Path); WriteOpenEMS(fullfile(Sim_Path, Sim_CSX), FDTD, CSX);
  fprintf('dry run: model in %s, geometry in %s\n', fullfile(Sim_Path, Sim_CSX), fullfile(out, [name '_geometry.png']));
  return
end
if ~skip_fdtd
  try confirm_recursive_rmdir(false, 'local'); end
  [~,~] = rmdir(Sim_Path, 's'); [~,~] = mkdir(Sim_Path);
  WriteOpenEMS(fullfile(Sim_Path, Sim_CSX), FDTD, CSX);
  save(pfile, 'P', '-mat');
  % on Windows RunOpenEMS writes a log only when silent; the log is how we know the run converged
  fprintf('openEMS running, progress in %s\n', fullfile(Sim_Path, 'openEMS.log'));
  tic; RunOpenEMS(Sim_Path, Sim_CSX, repmat(sprintf('--numThreads=%d', threads), 1, threads > 0), struct('LogFile', 'openEMS.log', 'Silent', 1)); t_run = toc;
else
  % the port and NF2FF box are rebuilt from the current board and parameters: they must match the saved fields
  assert(exist(pfile, 'file') == 2, 'no params.mat in %s: re-run the FDTD', Sim_Path);
  Q = load(pfile); assert(isequal(Q.P, P), 'board or parameters changed since this run: re-run the FDTD');
end
n_ts = NaN; logf = fullfile(Sim_Path, 'openEMS.log');
if exist(logf, 'file') == 2
  n = regexp(fileread(logf), 'Time for (\d+) iterations', 'tokens');
  if isempty(n), n = regexp(fileread(logf), 'Timestep:\s+(\d+)', 'tokens'); end
  if ~isempty(n), n_ts = str2double(n{end}{1}); end
end
if isnan(n_ts), conv = 'unknown (no openEMS.log)';
elseif n_ts >= nrts, conv = sprintf('NOT CONVERGED: hit the %d step limit before the end criterion; results unreliable', nrts);
else, conv = sprintf('converged in %d steps', n_ts); end

% measured S11 from a VNA (or an earlier run's .s1p): every measured*.s1p in the run folder, in number order
% (measured.s1p, measured1.s1p, measured2.s1p ...); Touchstone, any unit / RI / MA / DB, 50 ohm
mf = {dir(fullfile(here, 'measured*.s1p')).name};
[~, o] = sort(max(0, str2double(regexprep(mf, '^measured|\.s1p$', '')))); mf = mf(o);   % no number = 0, then 1, 2 .. 10
hf = sort({dir(fullfile(here, 'history', [name '_' res '_*.s1p'])).name});
mf = [mf, cellfun(@(f) ['history/' f], hf(max(1, end-1):end), 'uniformoutput', false)];   % + the last 2 earlier runs
M = {}; have_meas = ~isempty(mf);
mcol = [0 .6 0; .9 .45 0; .6 0 .75; 0 .6 .7; .55 .55 0; .9 0 .45];   % measured curves, cycled
for q = 1:numel(mf)
  meas = fullfile(here, mf{q});
  opt = 'GHZ S MA R 50'; num = {};  % the Touchstone default when there is no # line
  for l = strsplit(fileread(meas), {"\r\n", "\n"})
    s = strtrim(regexprep(l{1}, '!.*', ''));
    if isempty(s), continue; end
    if s(1) == '#', opt = upper(s(2:end)); else, num{end+1} = sscanf(s, '%f')'; end
  end
  num = vertcat(num{:}); tok = strsplit(strtrim(opt));
  assert(size(num, 2) == 3 && any(strcmp(tok, 'S')), '%s: need a 1-port S-parameter file', meas);
  ri = find(strcmp(tok, 'R')); assert(isempty(ri) || str2double(tok{ri+1}) == 50, '%s: reference must be 50 ohm', meas);
  u = struct('HZ', 1, 'KHZ', 1e3, 'MHZ', 1e6, 'GHZ', 1e9); ut = tok(isfield(u, tok)); fm = num(:, 1)' * u.(ut{1});
  a = num(:, 2)'; b = num(:, 3)';
  if any(strcmp(tok, 'RI')), sm = a + 1j*b;
  elseif any(strcmp(tok, 'DB')), sm = 10.^(a/20) .* exp(1j*b*pi/180);
  else, sm = a .* exp(1j*b*pi/180); end
  [sm_min, im] = min(20*log10(abs(sm)));
  M{end+1} = struct('name', mf{q}, 'f', fm, 's', sm, 'min', sm_min, 'fmin', fm(im), 'c', mcol(mod(q - 1, rows(mcol)) + 1, :));
end

%% results: match
freq = linspace(f_lo, f_hi, npts);
port = calcPort(port, Sim_Path, freq);
s11 = port.uf.ref ./ port.uf.inc; Zin = port.uf.tot ./ port.if.tot;
s11dB = 20*log10(abs(s11));
% the resonance is the dip nearest f0, not the sweep's deepest point (a higher mode or the feed can be deeper):
% a dip below match_db nearest f0, else a dip standing >= 1 dB out of its shoulders nearest f0, else the deepest point
im = find(s11dB(2:end-1) <= s11dB(1:end-2) & s11dB(2:end-1) < s11dB(3:end)) + 1;
pick = im(s11dB(im) <= match_db);
if isempty(pick)
  for i = im
    l = i; while l > 1 && s11dB(l-1) >= s11dB(l), l = l - 1; end
    r = i; while r < numel(s11dB) && s11dB(r+1) >= s11dB(r), r = r + 1; end
    if min(s11dB(l), s11dB(r)) - s11dB(i) >= 1, pick(end+1) = i; end
  end
end
if isempty(pick), [~, i_min] = min(s11dB);
else, [~, k] = min(abs(freq(pick) - f0)); i_min = pick(k); end
s_min = s11dB(i_min); f_res = freq(i_min);
at_edge = i_min == 1 || i_min == numel(freq);
lo = i_min; hi = i_min;            % the matched band is the stretch around the minimum only
while lo > 1 && s11dB(lo-1) < match_db, lo = lo - 1; end
while hi < numel(freq) && s11dB(hi+1) < match_db, hi = hi + 1; end
[~, i0] = min(abs(freq - f0));
ix = find(diff(sign(imag(Zin))) ~= 0);              % reactance zero crossings
f_x = freq(ix) - imag(Zin(ix)) .* (freq(ix+1) - freq(ix)) ./ (imag(Zin(ix+1)) - imag(Zin(ix)));

%% results: far field over frequency (coarse full sphere), pattern at the resonance (not in fast)
if pattern
if f_pat > 0, fp = f_pat; elseif at_edge, fp = f0; else, fp = f_res; end   % a minimum at the sweep edge is not a resonance
ffr = unique([linspace(f_lo, f_hi, 11), f0, fp]);
pf = calcPort(port, Sim_Path, ffr);
th = 0:pat_step:180; ph = 0:pat_step:360 - pat_step;
sph = CalcNF2FF(nf2ff, Sim_Path, ffr, th*pi/180, ph*pi/180, 'Outfile', 'ff_sphere.h5', 'Mode', 1);
D = sph.Dmax(:)'; eff = sph.Prad(:)' ./ pf.P_acc(:)'; reff = sph.Prad(:)' ./ pf.P_inc(:)';
s11f = 20*log10(abs(pf.uf.ref ./ pf.uf.inc));
[~, ip] = min(abs(ffr - fp));
emax = max(sph.E_norm{ip}(:));
tc = -180:2:180;
cut = CalcNF2FF(nf2ff, Sim_Path, ffr(ip), tc*pi/180, [0 90]*pi/180, 'Outfile', 'ff_cuts.h5', 'Mode', 1);
cxy = CalcNF2FF(nf2ff, Sim_Path, ffr(ip), pi/2, tc*pi/180, 'Outfile', 'ff_xy.h5', 'Mode', 1);
dB = @(E) 20*log10(max(E(:)' / emax, 1e-6)) + 10*log10(D(ip));   % directivity, dBi; floor -120 dB below the peak (the fields themselves are ~1e-13)
end

%% report
fid = fopen(files{1}, 'w'); assert(fid > 0, 'cannot write %s', files{1});
for fd = [1 fid]
  fprintf(fd, '%s %s run (%.0f s, %d x %d x %d cells, smallest %.3f mm)\n', name, res, t_run, numel(mesh.x), numel(mesh.y), numel(mesh.z), dmin);
  if ~isempty(board_txt), fprintf(fd, 'board: %s\n', board_txt); end
  fprintf(fd, 'model: %d copper sheets over %.3f mm of dielectric, epsR %s; ground %s; port %s\n', numel(geom.cu_z), zmax, ...
          mat2str(round(geom.diel(:, 3)' * 100) / 100), geom.gnd_net, geom.port_kind);
  if isempty(case_box), fprintf(fd, 'case: none, the board in air\n');
  else, fprintf(fd, 'case: plastic epsR %.3g tanD %.3g, wall %.3g mm, gap side %.3g top %.3g bottom %.3g mm\n', case_box); end
  if ~pattern, fprintf(fd, '%s (S11 only, no far field): confirm with coarse\n', res); end
  if at_edge
    fprintf(fd, 'min S11 %.1f dB at %.0f MHz = SWEEP EDGE: no resonance in %.0f..%.0f MHz (retune, or widen fc)\n', s_min, f_res/1e6, freq(1)/1e6, freq(end)/1e6);
  else
    fprintf(fd, 'resonance (min S11) %.1f dB at %.0f MHz\n', s_min, f_res/1e6);
  end
  bn = ''; if ~isempty(band_name), bn = [' (' band_name ')']; end
  if s_min >= match_db, fprintf(fd, 'no %g dB band\n', match_db);
  else
    verdict = {'MISSES', 'covers'}; covers = freq(lo) <= band_t(1) + (freq(2) - freq(1)) && freq(hi) >= band_t(2) - (freq(2) - freq(1));
    fprintf(fd, 'S11 < %g dB: %.0f .. %.0f MHz, %s the %.1f..%.1f MHz target%s\n', match_db, freq(lo)/1e6, freq(hi)/1e6, ...
            verdict{covers + 1}, band_t/1e6, bn);
  end
  fprintf(fd, 'at %.0f MHz: S11 %.1f dB, Zin %.1f %+.1fj ohm\n', f0/1e6, s11dB(i0), real(Zin(i0)), imag(Zin(i0)));
  fprintf(fd, 'reactance crosses zero at: %s MHz\n', mat2str(round(f_x/1e6)));
  rnote = ''; if rmax > 2, rnote = ' (above 2: abrupt cell jump, check the fine run agrees)'; end
  fprintf(fd, 'run: %s; mesh worst neighbour ratio %.2f%s\n', conv, rmax, rnote);
  for q = 1:numel(M)
    fprintf(fd, '%s: min S11 %.1f dB at %.0f MHz, %+.0f MHz from the simulation\n', M{q}.name, M{q}.min, M{q}.fmin/1e6, (M{q}.fmin - f_res)/1e6);
  end
  if ~pattern, continue; end
  fprintf(fd, '   f MHz  S11 dB   D dBi  rad eff %%  gain dBi  realized gain dBi\n');
  for k = 1:numel(ffr)
    flag = ''; if s11f(k) > -3, flag = '  (mismatched: rad eff is rough)'; end
    if abs(ffr(k) - ffr(ip)) < 1, flag = [flag '  <- pattern']; end
    fprintf(fd, '%8.0f %7.1f %7.2f %9.0f %9.2f %18.2f%s\n', ffr(k)/1e6, s11f(k), 10*log10(D(k)), 100*eff(k), ...
            10*log10(D(k)*eff(k)), 10*log10(D(k)*reff(k)), flag);
  end
end
fclose(fid);

% Touchstone for matching-network design
fid = fopen(files{2}, 'w'); assert(fid > 0, 'cannot write %s', files{2});
fprintf(fid, '! %s openEMS %s: lumped port at the feed pad (%s), not de-embedded\n# Hz S RI R 50\n', name, res, geom.port_kind);
fprintf(fid, '%.0f %.6f %.6f\n', [freq; real(s11); imag(s11)]);
fclose(fid);

% S11 / Zin: f0 +/- 15 %, widened to the matched band, within the sweep; target band shaded
xr = [f0*0.85, f0*1.15];
if s_min < match_db, xr = [min(xr(1), freq(lo)), max(xr(2), freq(hi))]; end
xr = [max(xr(1), freq(1)), min(xr(2), freq(end))] / 1e6;
ylo = min(-40, 10*floor(s_min/10) - 5);
h = figure('visible', 'off', 'paperunits', 'inches', 'paperposition', [0 0 10 8]);   % 2000 x 1600 px at -r200: sharp when opened full size
set(h, 'defaultaxesfontsize', 12, 'defaulttextfontsize', 12, 'defaultlinelinewidth', 2);
a1 = subplot(2,1,1); hold on;
patch(band_t([1 2 2 1])/1e6, [ylo ylo 0 0], [.85 .92 1], 'edgecolor', 'none');
plot(xr, [match_db match_db], 'r--', 'linewidth', 1);
if s_min < match_db, plot([freq(lo) freq(lo); freq(hi) freq(hi)]'/1e6, [ylo 0], 'r:', 'linewidth', 1); end
hm = [];
for q = 1:numel(M), hm(end+1) = plot(M{q}.f/1e6, 20*log10(abs(M{q}.s)), 'color', M{q}.c); end
hs = plot(freq/1e6, s11dB, 'k');   % last: on top of an overlay that matches it
if ~at_edge
  plot(f_res/1e6, s_min, 'o', 'color', 'k', 'markerfacecolor', 'r', 'markersize', 8);
  text(f_res/1e6, s_min, sprintf('  %.0f MHz, %.1f dB', f_res/1e6, s_min), 'verticalalignment', 'top');
end
% under the plot, in one row: inside it covered the dip and the resonance mark; names without folder and .s1p
if have_meas, legend([hs hm], [{'simulation'}, cellfun(@(m) regexprep(m.name, '^.*[\\/]|\.s1p$', ''), M, 'uniformoutput', false)], ...
                     'location', 'southoutside', 'orientation', 'horizontal', 'interpreter', 'none'); end
grid on; box on; ylabel('|S11| (dB)'); ylim([ylo 0]); xlim(xr);
title(sprintf('%s %s: S11 (blue = target band, red = %g dB)', name, res, match_db), 'interpreter', 'none');   % ANT__: no TeX subscripts
a2 = subplot(2,1,2); plot(freq/1e6, real(Zin), 'b', freq/1e6, imag(Zin), 'r--'); hold on;
k = freq >= xr(1)*1e6 & freq <= xr(2)*1e6; zr = [real(Zin(k)) imag(Zin(k))];
grid on; box on; xlabel('MHz'); ylabel('Z_{in} (\Omega)'); xlim(xr); title('Z_{in}: blue = Re, red dashed = Im');
ylim([min(-50, min(zr)), max(100, max(zr))] .* [1.1 1.1]);
stamp(h, 0.96); print(h, fullfile(out, [name '_' res '_s11_zin.png']), '-dpng', '-r200');
% for the plugin's readout under the mouse: the plot area in the picture (x from the left, y from the top, as
% fractions: S11 top to Zin bottom), its MHz range, and the traces (colour, name, .s1p in the run folder)
p1 = get(a1, 'position'); p2 = get(a2, 'position');
fid = fopen(fullfile(out, [name '_' res '_s11_zin.txt']), 'w');
if fid > 0
  fprintf(fid, 'box %.5f %.5f %.5f %.5f\nxlim %.8g %.8g\n', p1(1), p1(1) + p1(3), 1 - p1(2) - p1(4), 1 - p2(2), xr);
  fprintf(fid, 'trace 0 0 0 simulation\tresults/%s_%s.s1p\n', name, res);
  for q = 1:numel(M), fprintf(fid, 'trace %g %g %g %s\t%s\n', M{q}.c, regexprep(M{q}.name, '^.*[\\/]|\.s1p$', ''), M{q}.name); end
  fclose(fid);
end

% Smith chart of S11 (50 ohm): circle = f0, squares = target band edges
h = figure('visible', 'off', 'paperunits', 'inches', 'paperposition', [0 0 8 8]); hold on; axis equal; axis off;
G = @(z) (z - 1) ./ (z + 1); gc = [.8 .8 .8];
r = [0 logspace(-3, 4, 500)]; s = [-fliplr(r) r];
for rr = [0 0.2 0.5 1 2 5], plot(real(G(rr + 1j*s)), imag(G(rr + 1j*s)), 'color', gc); end
for xx = [-5 -2 -1 -0.5 -0.2 0.2 0.5 1 2 5], plot(real(G(r + 1j*xx)), imag(G(r + 1j*xx)), 'color', gc); end
plot([-1 1], [0 0], 'color', gc);
hs = plot(real(s11), imag(s11), 'k', 'LineWidth', 1.5); hm = [];
for q = 1:numel(M)
  k = M{q}.f >= freq(1) & M{q}.f <= freq(end); hm(end+1) = plot(real(M{q}.s(k)), imag(M{q}.s(k)), 'color', M{q}.c, 'LineWidth', 1.2);
end
plot(real(s11(i0)), imag(s11(i0)), 'ko', 'markerfacecolor', 'r');
for bt = band_t, [~, k] = min(abs(freq - bt)); plot(real(s11(k)), imag(s11(k)), 'bs', 'markerfacecolor', 'b'); end
if have_meas, legend([hs hm], [{'simulation'}, cellfun(@(m) m.name, M, 'uniformoutput', false)], 'location', 'southoutside', 'interpreter', 'none'); end
title({sprintf('%s %s: S11 %.0f..%.0f MHz', name, res, freq(1)/1e6, freq(end)/1e6), ...
       sprintf('red = %.0f MHz, blue = target band edges', f0/1e6)}, 'interpreter', 'none');
stamp(h, 0.96); print(h, fullfile(out, [name '_' res '_smith.png']), '-dpng', '-r200');

if ~pattern, return; end
h = figure('visible', 'off', 'paperunits', 'inches', 'paperposition', [0 0 10 6]);
set(h, 'defaultaxesfontsize', 12, 'defaulttextfontsize', 12);
axes('position', [0.13 0.11 0.775 0.76]);   % room above the title for the heading
plot(tc,dB(cut.E_norm{1}(:, 1)), 'b', tc, dB(cut.E_norm{1}(:, 2)), 'r--', tc, dB(cxy.E_norm{1}), 'k:', 'LineWidth', 2.5);
grid on; xlim([-180 180]); ylim([-30 ceil(10*log10(D(ip))) + 2]);
xlabel('angle (deg): \theta for xz / yz (negative = \phi+180 side), \phi for xy'); ylabel('directivity (dBi)');
legend('xz (\phi = 0)', 'yz (\phi = 90)', 'xy (\theta = 90)', 'location', 'south');
title(sprintf('%s %s: pattern cuts at %.0f MHz (x right, y up as in KiCad, z = top normal)', name, res, ffr(ip)/1e6), 'interpreter', 'none');
stamp(h, 0.96); print(h, fullfile(out, [name '_' res '_pattern.png']), '-dpng', '-r200');
DumpFF2VTK(fullfile(out, [name '_' res '_pattern.vtk']), sph.E_norm{ip} / emax * D(ip), th, ph);
