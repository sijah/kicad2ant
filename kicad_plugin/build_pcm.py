"""Builds the KiCad Plugin and Content Manager package: python kicad_plugin/build_pcm.py
-> dist/<identifier>-<version>.zip          install it with Plugin and Content Manager > Install from File...
-> dist/metadata_gitlab_submission.json     the same metadata with the download fields KiCad's addon repository needs
"""
import copy, hashlib, json, os, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLUGIN = os.path.join(HERE, 'kicad2ant_plugin')

with open(os.path.join(HERE, 'metadata.json'), encoding='utf-8') as f:
    meta = json.load(f)
version = meta['versions'][0]['version']
src = open(os.path.join(PLUGIN, '__init__.py'), encoding='utf-8').read()
assert "VERSION = '%s'" % version in src, 'set VERSION in kicad2ant_plugin/__init__.py to ' + version
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts', 'kicad2ant.py'), encoding='utf-8') as f:
    assert "VERSION = '%s'" % version in f.read(), 'set VERSION in scripts/kicad2ant.py to ' + version   # on the plots
files = {'metadata.json': os.path.join(HERE, 'metadata.json'),
         'plugins/LICENSE': os.path.join(ROOT, 'LICENSE'),
         'resources/icon.png': os.path.join(HERE, 'icon64.png'),
         'plugins/icon64.png': os.path.join(HERE, 'icon64.png')}   # the logo in the window
for name in ('__init__.py', 'core.py', 'icon.png'):
    files['plugins/' + name] = os.path.join(PLUGIN, name)
for name in ('kicad2ant.py', 'extract_antenna.py', 'mesher.py', 'antenna_sim.m'):
    files['plugins/scripts/' + name] = os.path.join(ROOT, 'scripts', name)

name = '%s-%s.zip' % (meta['identifier'], version)
out = os.path.join(ROOT, 'dist', name)
os.makedirs(os.path.dirname(out), exist_ok=True)
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for arc, src in sorted(files.items()):
        z.write(src, arc)

sub = copy.deepcopy(meta)
with open(out, 'rb') as f:
    sub['versions'][0].update(
        download_sha256=hashlib.sha256(f.read()).hexdigest(), download_size=os.path.getsize(out),
        download_url='%s/releases/download/v%s/%s' % (meta['resources']['homepage'], version, name),
        install_size=sum(os.path.getsize(p) for p in files.values()))
with open(os.path.join(ROOT, 'dist', 'metadata_gitlab_submission.json'), 'w', encoding='utf-8', newline='\n') as f:
    json.dump(sub, f, indent=4)
    f.write('\n')
print(out)
