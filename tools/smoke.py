"""Explicit live test for 0.3 tasks. Never invoked on import/startup or by unit tests."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', required=True)
parser.add_argument('--model', required=True)
parser.add_argument('--task', choices=['creative_expand', 'faithful_refine', 'reference_describe', 'reference_create', 'image_edit'], default='creative_expand')
parser.add_argument('--prompt', default='云海中的东方天宫，一位行者站在巨柱旁。')
parser.add_argument('--image')
parser.add_argument('--language', choices=['en', 'zh'], default='en')
parser.add_argument('--length', choices=['detailed', 'simple'], default='detailed')
parser.add_argument('--quality', choices=['standard', 'precise'], default='standard')
parser.add_argument('--api-type', choices=['auto', 'chat_completions', 'responses'], default='auto')
parser.add_argument('--advanced-json', default='{}')
parser.add_argument('--must-keep', default='')
parser.add_argument('--output-dir', required=True)
args = parser.parse_args()
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('samuel_enhancer_smoke', root / '__init__.py', submodule_search_locations=[str(root)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
from samuel_enhancer_smoke.nodes import SamuelEnhancerService, SamuelEnhancerTemplate, SamuelEnhancerConfig, SamuelEnhancerGeneration, SamuelEnhancerReverse, SamuelEnhancerEdit
from samuel_enhancer_smoke.prompts import load_preset

preset = 'editing' if args.task == 'image_edit' else 'generation'
service = SamuelEnhancerService().configure(base_url=args.base_url, model=args.model, api_type=args.api_type,
                                       advanced_json=args.advanced_json, timeout_seconds=600)[0]
template = SamuelEnhancerTemplate().configure(preset, load_preset(preset))[0]
config = SamuelEnhancerConfig().configure(service, template, language=args.language)[0]
options = {'user_text': args.prompt, 'must_keep': args.must_keep,
           'length': '详细' if args.length == 'detailed' else '简单',
           'quality_mode': '标准' if args.quality == 'standard' else '精确'}
image = None
if args.image:
    import numpy as np
    from PIL import Image, ImageOps
    with Image.open(args.image) as file:
        image = np.asarray(ImageOps.exif_transpose(file).convert('RGB'), dtype=np.float32)[None] / 255.0
if args.task.startswith('reference_'):
    node = SamuelEnhancerReverse()
    options.update(image=image, task_mode='忠实反推' if args.task == 'reference_describe' else '参考图创作')
elif args.task == 'image_edit':
    node = SamuelEnhancerEdit()
    options['image'] = image
else:
    node = SamuelEnhancerGeneration()
    options['task_mode'] = '创作扩写' if args.task == 'creative_expand' else '忠实润色'
output = Path(args.output_dir)
output.mkdir(parents=True, exist_ok=False)
prompt, info = node.execute(config, **options)
(output / 'prompt.txt').write_text(prompt, encoding='utf-8')
(output / 'info.json').write_text(info, encoding='utf-8')
print(info)
print('Saved:', output.resolve())
