"""Build a shareable distributable from an explicit allowlist; exclude local archives and logs."""

import argparse
import hashlib
from pathlib import Path
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('--output-dir', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
output = Path(args.output_dir).resolve()
output.mkdir(parents=True, exist_ok=True)
archive = output / 'Comfyui-prompt-enhancer-0.3.5.zip'
top = {'__init__.py', 'client.py', 'images.py', 'nodes.py', 'prompts.py', 'pipeline.py', 'routes.py',
       'README.md', 'requirements.txt', '.gitignore', '.gitattributes', 'LICENSE', 'CHANGELOG.md'}
folders = {'templates', 'examples', 'docs', 'web', 'tests', 'tools'}
suffixes = {'.py', '.md', '.json', '.js', '.mjs'}
files = [root / name for name in top]
for folder in sorted(folders):
    if folder == 'templates':
        # Only current production assets; historical rules are kept in the workspace.
        files.extend(p for p in (root / folder / 'presets').rglob('*') if p.is_file() and p.suffix in suffixes)
        files.append(root / folder / 'manifest.json')
    elif folder == 'docs':
        # Publish current instructions only. Earlier validation logs and source notes stay local.
        files.extend(root / 'docs' / name for name in
                     ('USAGE.md', 'TROUBLESHOOTING.md', 'CHANGES-0.3.5.md', 'VALIDATION-0.3.5.md'))
        files.extend(p for p in (root / 'docs/presets').glob('*.md') if p.is_file())
        files.extend(p for p in (root / 'docs/images').glob('*.png') if p.is_file())
    else:
        files.extend(p for p in (root / folder).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix in suffixes)
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
    for file in sorted(files):
        bundle.write(file, 'Comfyui-prompt-enhancer/' + file.relative_to(root).as_posix())
with zipfile.ZipFile(archive) as bundle:
    assert bundle.testzip() is None
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(output / (archive.name + '.sha256')).write_text(digest + '  ' + archive.name + '\n', encoding='ascii')
print(str(archive))
print('Files:', len(files), 'Bytes:', archive.stat().st_size, 'SHA256:', digest)
