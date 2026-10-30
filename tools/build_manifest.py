"""Refresh asset hashes explicitly; runtime never mutates the approved presets."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data = {'node_version': '0.3.5', 'note': 'Only these approved production presets are loaded at runtime. Task adaptations are visible in the template editor.', 'presets': {}}
for name, baseline in [('generation', 'generation-production-v1.md'), ('editing', 'editing-production-v1.md')]:
    runtime = root / 'templates/presets' / (name + '.md')
    approved = root / 'docs/presets' / baseline
    assert runtime.read_bytes() == approved.read_bytes(), f'{name}: runtime differs from approved baseline'
    data['presets'][name] = {'file': runtime.relative_to(root).as_posix(),
                             'approved_baseline': approved.relative_to(root).as_posix(),
                             'sha256': hashlib.sha256(runtime.read_bytes()).hexdigest()}
(root / 'templates/manifest.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Verified two approved presets and refreshed manifest.')
