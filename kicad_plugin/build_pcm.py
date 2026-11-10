"""Builds the KiCad Plugin and Content Manager zip: python kicad_plugin/build_pcm.py -> dist/kicad2ant-<version>-pcm.zip"""
import json, os, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLUGIN = os.path.join(HERE, 'kicad2ant_plugin')

with open(os.path.join(HERE, 'metadata.json'), encoding='utf-8') as f:
    version = json.load(f)['versions'][0]['version']
files = {'metadata.json': os.path.join(HERE, 'metadata.json'),
         'plugins/LICENSE': os.path.join(ROOT, 'LICENSE'),
         'resources/icon.png': os.path.join(HERE, 'icon64.png')}
for name in ('__init__.py', 'core.py', 'icon.png'):
    files['plugins/' + name] = os.path.join(PLUGIN, name)
for name in ('kicad2ant.py', 'extract_antenna.py', 'antenna_sim.m'):
    files['plugins/scripts/' + name] = os.path.join(ROOT, 'scripts', name)

out = os.path.join(ROOT, 'dist', 'kicad2ant-%s-pcm.zip' % version)
os.makedirs(os.path.dirname(out), exist_ok=True)
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for arc, src in sorted(files.items()):
        z.write(src, arc)
print(out)
