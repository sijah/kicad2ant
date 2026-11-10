% kicad2ant: PCB antenna from a KiCad board: S11, Zin, directivity / efficiency / gain over
% frequency, pattern.  Normally started by kicad2ant.py, which extracts antenna_geom.m (the antenna
% footprint's copper, the GND net's zone fills, tracks and vias, the stackup, the outline, the feed port)
% into the run folder and sets the variables below.
% Model: one dielectric per copper pair, copper as PEC sheets, GND vias / plated holes as PEC lines,
% 50 ohm lumped port at the feed pad, board in air, PML_8 on all sides.  Other nets' copper and the
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
if ~exist('fc', 'var'), fc = 0.4 * f0; end          % reported band f0 -/+ fc
if ~exist('band_t', 'var'), band_t = [2400 2483.5] * 1e6; end   % target band: marked on plots, checked in the summary
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

%% parameters
if strcmp(res, 'fine'), cell_ant = 0.2; air_div = 20; nz = 4; end_crit = 1e-5;
else                    cell_ant = 0.5; air_div = 15; nz = 2; end_crit = 1e-4; end
% fast: S11 only. No thirds-rule lines (larger timestep), MUR and lambda/8 air instead of PML and lambda/4, -30 dB, no far field
fast = strcmp(res, 'fast'); if fast, end_crit = 1e-3; end
air = max(5, c0 / f0 / unit / (4 + 4*fast));  % air on every side: lambda/4 at f0 (fast: lambda/8), then the boundary
% the excitation reaches 30 % of the band past its top: the far field comes out wrong near the
% upper edge of the Gaussian's band while S11 still looks fine (kicad2ems, docs/maintenance.md)
f_ex = f0 + 0.3 * fc; fc_ex = 1.3 * fc;

%% model
nrts = 300000;                     % step limit: a run that hits it did not converge (warned in the summary)
FDTD = InitFDTD('NrTS', nrts, 'EndCriteria', end_crit);
FDTD = SetGaussExcite(FDTD, f_ex, fc_ex);
if fast, FDTD = SetBoundaryCond(FDTD, {'MUR' 'MUR' 'MUR' 'MUR' 'MUR' 'MUR'});
else, FDTD = SetBoundaryCond(FDTD, {'PML_8' 'PML_8' 'PML_8' 'PML_8' 'PML_8' 'PML_8'}); end
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
[CSX, port] = AddLumpedPort(CSX, 5, 1, 50, geom.port(1:3), geom.port(4:6), geom.port_dir, true);

%% mesh: thirds rule on straight antenna edges, port planes kept exactly, other lines merged
% within cell_ant/2 of a kept one, graded to lambda/air_div, 8 PML cells outside the air
lam = c0 / (f_ex + fc_ex) / unit;                  % shortest excited wavelength (mm)
d_sub = lam / sqrt(max(geom.diel(:, 3))) / air_div; % largest cell inside the board
o = geom.outline; bb = [min(o, [], 1) max(o, [], 1)];
fine = [geom.ant_box(1:2) - 3, geom.ant_box(3:4) + 3];
axn = 'xy';
for a = 1:2
  e = geom.(['edge_' axn(a)]);
  if fast, pri = [geom.port([a a+3]), e(:, 1)'];   % lines on the copper edges themselves
  else, pri = [geom.port([a a+3]), e(:, 1)' + e(:, 2)' * cell_ant/3, e(:, 1)' - e(:, 2)' * 2*cell_ant/3]; end
  low = [geom.(['mesh_' axn(a)]), fine(a):cell_ant:fine(a+2), bb(a):d_sub:bb(a+2), bb(a), bb(a+2), bb(a) - air, bb(a+2) + air];
  for pass = 1:2                   % before and after smoothing
    p = sort(pri); keep = p(1);
    for t = p(2:end), if t - keep(end) > cell_ant/3, keep(end+1) = t; end, end
    w = sort(low); w = w(arrayfun(@(t) min(abs(keep - t)) > cell_ant/2, w));
    v = sort([keep w]); out = v(1);
    for t = v(2:end), if t - out(end) > cell_ant/4 * (1 + fast) || any(keep == t), out(end+1) = t; end, end   % fast: no cell under cell_ant/2 between grids
    mesh.(axn(a)) = out;
    if pass == 1, low = SmoothMeshLines(out, lam / air_div, 1.4); end
  end
end
zl = unique([geom.cu_z, geom.diel(:, 1)', geom.diel(:, 2)', -air, zmax + air]);
for k = 1:size(geom.diel, 1)
  d = geom.diel(k, :); zl = [zl, linspace(d(1), d(2), max(nz, ceil((d(2) - d(1)) / cell_ant)) + 1)];
end
zl = unique(round(zl * 1e5) / 1e5);
mesh.z = SmoothMeshLines(zl, lam / air_div, 1.4);
dmax = lam / air_div;              % the PML: 8 more cells on every side
if ~fast, for a = 'xyz', v = mesh.(a); mesh.(a) = [v(1) - (8:-1:1) * dmax, v, v(end) + (1:8) * dmax]; end, end
CSX = DefineRectGrid(CSX, unit, mesh);
ncell = numel(mesh.x) * numel(mesh.y) * numel(mesh.z);
dmin = min([diff(mesh.x) diff(mesh.y) diff(mesh.z)]);
rmax = max(cellfun(@(v) max([diff(v(2:end)) ./ diff(v(1:end-1)), diff(v(1:end-1)) ./ diff(v(2:end))]), {mesh.x, mesh.y, mesh.z}));
fprintf('%s mesh: %d x %d x %d = %.2f Mcells, smallest cell %.3f mm, worst neighbour ratio %.2f\n', res, numel(mesh.x), numel(mesh.y), numel(mesh.z), ncell/1e6, dmin, rmax);
if ~fast, [CSX, nf2ff] = CreateNF2FFBox(CSX, 'nf2ff', [mesh.x(10) mesh.y(10) mesh.z(10)], [mesh.x(end-9) mesh.y(end-9) mesh.z(end-9)]); end

%% geometry plot: every copper layer, whole board and around the antenna
out = fullfile(here, 'results'); [~,~] = mkdir(out);
nl = numel(geom.cu_name); h = figure('visible', 'off', 'position', [0 0 360*nl 720]);
for r = 1:2, for k = 1:nl
  subplot(2, nl, (r-1)*nl + k); hold on; axis equal; box on;
  title(sprintf('%s z=%.3f', geom.cu_name{k}, geom.cu_z(k)), 'interpreter', 'none');
  plot(o([1:end 1], 1), o([1:end 1], 2), 'k');
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
print(h, fullfile(out, [name '_geometry.png']), '-dpng', '-r100');

%% run
Sim_Path = fullfile(here, ['sim_' res]); Sim_CSX = 'antenna.xml';
P = struct('geom', geom, 'f0', f0, 'fc', fc, 'f_ex', f_ex, 'fc_ex', fc_ex, 'mesh', mesh, 'end_crit', end_crit);
pfile = fullfile(Sim_Path, 'params.mat');
files = {fullfile(out, [name '_' res '_summary.txt']), fullfile(out, [name '_' res '.s1p'])};
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
  tic; RunOpenEMS(Sim_Path, Sim_CSX, '', struct('LogFile', 'openEMS.log', 'Silent', 1)); t_run = toc;
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

% measured S11 from a VNA, if the run folder holds measured.s1p (Touchstone, any unit / RI / MA / DB, 50 ohm)
meas = fullfile(here, 'measured.s1p'); have_meas = exist(meas, 'file') == 2;
if have_meas
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
end

%% results: match
freq = linspace(f0 - fc, f0 + fc, 801);
port = calcPort(port, Sim_Path, freq);
s11 = port.uf.ref ./ port.uf.inc; Zin = port.uf.tot ./ port.if.tot;
s11dB = 20*log10(abs(s11));
[s_min, i_min] = min(s11dB); f_res = freq(i_min);
at_edge = i_min == 1 || i_min == numel(freq);
lo = i_min; hi = i_min;            % the -10 dB band is the stretch around the minimum only
while lo > 1 && s11dB(lo-1) < -10, lo = lo - 1; end
while hi < numel(freq) && s11dB(hi+1) < -10, hi = hi + 1; end
[~, i0] = min(abs(freq - f0));
ix = find(diff(sign(imag(Zin))) ~= 0);              % reactance zero crossings
f_x = freq(ix) - imag(Zin(ix)) .* (freq(ix+1) - freq(ix)) ./ (imag(Zin(ix+1)) - imag(Zin(ix)));

%% results: far field over frequency (coarse full sphere), pattern at the resonance (not in fast)
if ~fast
ffr =unique([linspace(f0 - fc, f0 + fc, 11), f0, f_res]);
pf = calcPort(port, Sim_Path, ffr);
th = 0:5:180; ph = 0:5:355;
sph = CalcNF2FF(nf2ff, Sim_Path, ffr, th*pi/180, ph*pi/180, 'Outfile', 'ff_sphere.h5', 'Mode', 1);
D = sph.Dmax(:)'; eff = sph.Prad(:)' ./ pf.P_acc(:)'; reff = sph.Prad(:)' ./ pf.P_inc(:)';
s11f = 20*log10(abs(pf.uf.ref ./ pf.uf.inc));
if at_edge, f_pat = f0; else, f_pat = f_res; end   % a minimum at the sweep edge is not a resonance
[~, ip] = min(abs(ffr - f_pat));
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
  fprintf(fd, 'board: %d copper layers, %.3f mm, epsR %s; ground %s; port %s\n', numel(geom.cu_z), zmax, ...
          mat2str(round(geom.diel(:, 3)' * 100) / 100), geom.gnd_net, geom.port_kind);
  if fast, fprintf(fd, 'fast (S11 only, no far field): confirm with coarse\n'); end
  if at_edge
    fprintf(fd, 'min S11 %.1f dB at %.0f MHz = SWEEP EDGE: no resonance in %.0f..%.0f MHz (retune, or widen fc)\n', s_min, f_res/1e6, freq(1)/1e6, freq(end)/1e6);
  else
    fprintf(fd, 'resonance (min S11) %.1f dB at %.0f MHz\n', s_min, f_res/1e6);
  end
  if s_min >= -10, fprintf(fd, 'no -10 dB band\n');
  else
    verdict = {'MISSES', 'covers'}; covers = freq(lo) <= band_t(1) + (freq(2) - freq(1)) && freq(hi) >= band_t(2) - (freq(2) - freq(1));
    fprintf(fd, 'S11 < -10 dB: %.0f .. %.0f MHz, %s the %.1f..%.1f MHz target\n', freq(lo)/1e6, freq(hi)/1e6, verdict{covers + 1}, band_t/1e6);
  end
  fprintf(fd, 'at %.0f MHz: S11 %.1f dB, Zin %.1f %+.1fj ohm\n', f0/1e6, s11dB(i0), real(Zin(i0)), imag(Zin(i0)));
  fprintf(fd, 'reactance crosses zero at: %s MHz\n', mat2str(round(f_x/1e6)));
  rnote = ''; if rmax > 2, rnote = ' (above 2: abrupt cell jump, check the fine run agrees)'; end
  fprintf(fd, 'run: %s; mesh worst neighbour ratio %.2f%s\n', conv, rmax, rnote);
  if have_meas
    fprintf(fd, 'measured (measured.s1p): min S11 %.1f dB at %.0f MHz, %+.0f MHz from the simulation\n', sm_min, fm(im)/1e6, (fm(im) - f_res)/1e6);
  end
  if fast, continue; end
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

% S11 / Zin: f0 +/- 15 %, widened to the -10 dB band, within the sweep; target band shaded
xr = [f0*0.85, f0*1.15];
if s_min < -10, xr = [min(xr(1), freq(lo)), max(xr(2), freq(hi))]; end
xr = [max(xr(1), freq(1)), min(xr(2), freq(end))] / 1e6;
ylo = min(-40, 10*floor(s_min/10) - 5);
h = figure('visible', 'off', 'paperunits', 'inches', 'paperposition', [0 0 10 8]);   % 2000 x 1600 px at -r200: sharp when opened full size
set(h, 'defaultaxesfontsize', 12, 'defaulttextfontsize', 12, 'defaultlinelinewidth', 2);
subplot(2,1,1); hold on;
patch(band_t([1 2 2 1])/1e6, [ylo ylo 0 0], [.85 .92 1], 'edgecolor', 'none');
plot(xr, [-10 -10], 'r--', 'linewidth', 1);
if s_min < -10, plot([freq(lo) freq(lo); freq(hi) freq(hi)]'/1e6, [ylo 0], 'r:', 'linewidth', 1); end
plot(freq/1e6, s11dB, 'k');
if have_meas, plot(fm/1e6, 20*log10(abs(sm)), 'color', [0 .6 0]); end
if ~at_edge
  plot(f_res/1e6, s_min, 'o', 'color', 'k', 'markerfacecolor', 'r', 'markersize', 8);
  text(f_res/1e6, s_min, sprintf('  %.0f MHz, %.1f dB', f_res/1e6, s_min), 'verticalalignment', 'top');
end
grid on; box on; ylabel('|S11| (dB)'); ylim([ylo 0]); xlim(xr);
title(sprintf('%s %s: S11 (blue = target band, red = -10 dB%s)', name, res, repmat(', green = measured', 1, have_meas)));
subplot(2,1,2); plot(freq/1e6, real(Zin), 'b', freq/1e6, imag(Zin), 'r--'); hold on;
k = freq >= xr(1)*1e6 & freq <= xr(2)*1e6; zr = [real(Zin(k)) imag(Zin(k))];
grid on; box on; xlabel('MHz'); ylabel('Z_{in} (\Omega)'); xlim(xr); title('Z_{in}: blue = Re, red dashed = Im');
ylim([min(-50, min(zr)), max(100, max(zr))] .* [1.1 1.1]);
print(h, fullfile(out, [name '_' res '_s11_zin.png']), '-dpng', '-r200');

% Smith chart of S11 (50 ohm): circle = f0, squares = target band edges
h = figure('visible', 'off', 'paperunits', 'inches', 'paperposition', [0 0 8 8]); hold on; axis equal; axis off;
G = @(z) (z - 1) ./ (z + 1); gc = [.8 .8 .8];
r = [0 logspace(-3, 4, 500)]; s = [-fliplr(r) r];
for rr = [0 0.2 0.5 1 2 5], plot(real(G(rr + 1j*s)), imag(G(rr + 1j*s)), 'color', gc); end
for xx = [-5 -2 -1 -0.5 -0.2 0.2 0.5 1 2 5], plot(real(G(r + 1j*xx)), imag(G(r + 1j*xx)), 'color', gc); end
plot([-1 1], [0 0], 'color', gc);
plot(real(s11), imag(s11), 'k', 'LineWidth', 1.5);
if have_meas, k = fm >= freq(1) & fm <= freq(end); plot(real(sm(k)), imag(sm(k)), 'g', 'LineWidth', 1.2); end
plot(real(s11(i0)), imag(s11(i0)), 'ko', 'markerfacecolor', 'r');
for bt = band_t, [~, k] = min(abs(freq - bt)); plot(real(s11(k)), imag(s11(k)), 'bs', 'markerfacecolor', 'b'); end
title({sprintf('%s %s: S11 %.0f..%.0f MHz', name, res, freq(1)/1e6, freq(end)/1e6), ...
       sprintf('red = %.0f MHz, blue = target band edges%s', f0/1e6, repmat(', green = measured', 1, have_meas))});
print(h, fullfile(out, [name '_' res '_smith.png']), '-dpng', '-r200');

if fast, return; end
h = figure('visible', 'off', 'paperunits', 'inches', 'paperposition', [0 0 10 6]);
set(h, 'defaultaxesfontsize', 12, 'defaulttextfontsize', 12);
plot(tc,dB(cut.E_norm{1}(:, 1)), 'b', tc, dB(cut.E_norm{1}(:, 2)), 'r--', tc, dB(cxy.E_norm{1}), 'k:', 'LineWidth', 2.5);
grid on; xlim([-180 180]); ylim([-30 ceil(10*log10(D(ip))) + 2]);
xlabel('angle (deg): \theta for xz / yz (negative = \phi+180 side), \phi for xy'); ylabel('directivity (dBi)');
legend('xz (\phi = 0)', 'yz (\phi = 90)', 'xy (\theta = 90)', 'location', 'south');
title(sprintf('%s %s: pattern cuts at %.0f MHz (x right, y up as in KiCad, z = top normal)', name, res, ffr(ip)/1e6));
print(h, fullfile(out, [name '_' res '_pattern.png']), '-dpng', '-r200');
DumpFF2VTK(fullfile(out, [name '_' res '_pattern.vtk']), sph.E_norm{ip} / emax * D(ip), th, ph);
