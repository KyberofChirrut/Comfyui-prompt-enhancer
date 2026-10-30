"""Produce independent 0.3 workflows with native ComfyUI configuration subgraphs."""
import importlib.util
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('samuel_enhancer_examples', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
from samuel_enhancer_examples.prompts import load_preset


def uid(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'samuel-enhancer/0.3/' + name))


def node(node_id, node_type, pos, values=None, title=None):
    cls = package.NODE_CLASS_MAPPINGS[node_type]
    schema = cls.INPUT_TYPES()
    inputs, widgets = [], []
    values = values or {}
    for name, definition in {**schema['required'], **schema.get('optional', {})}.items():
        kind = definition[0]
        options = definition[1] if len(definition) > 1 else {}
        if options.get('forceInput') or (not isinstance(kind, list) and kind not in ('STRING', 'INT', 'FLOAT', 'BOOLEAN')):
            inputs.append({'name': name, 'type': kind, 'link': None})
        else:
            default = options.get('default', kind[0] if isinstance(kind, list) else None)
            widgets.append(values.get(name, default))
    return {'id': node_id, 'type': node_type, 'pos': pos, 'size': [340, 200], 'flags': {},
            'order': 0, 'mode': 0, 'inputs': inputs,
            'outputs': [{'name': name, 'type': kind, 'links': [], 'slot_index': i}
                        for i, (name, kind) in enumerate(zip(cls.RETURN_NAMES, cls.RETURN_TYPES))],
            'properties': {'Node name for S&R': node_type}, 'widgets_values': widgets,
            'title': ('Samuel-Enhancer · ' + title if title else package.NODE_DISPLAY_NAME_MAPPINGS[node_type])}


def link(nodes, links, source, output, target, input_name, internal=False):
    origin, destination = nodes[source], nodes[target]
    slot = next(i for i, value in enumerate(destination['inputs']) if value['name'] == input_name)
    datatype = origin['outputs'][output]['type']
    assert datatype == destination['inputs'][slot]['type']
    link_id = len(links) + 1
    origin['outputs'][output]['links'].append(link_id)
    destination['inputs'][slot]['link'] = link_id
    value = {'id': link_id, 'origin_id': source, 'origin_slot': output,
             'target_id': target, 'target_slot': slot, 'type': datatype}
    links.append(value if internal else [link_id, source, output, target, slot, datatype])


def config_subgraph(preset, official=False):
    name = preset + ('-openai' if official else '-local')
    sub_id = uid(name)
    nodes = {
        1: node(1, 'SamuelEnhancerService', [100, 100],
                {'provider': 'openai' if official else 'local', 'model': ''}, 'LLM 服务：填写模型和地址'),
        2: node(2, 'SamuelEnhancerTemplate', [500, 100],
                {'preset': preset, 'template_text': load_preset(preset)}, '完整模板：可直接查看和修改'),
        3: node(3, 'SamuelEnhancerConfig', [1220, 100], title='输出语言／高级设置'),
    }
    nodes[1]['size'] = [340, 480]
    nodes[2]['size'] = [620, 800]
    nodes[3]['size'] = [340, 230]
    links = []
    link(nodes, links, 1, 0, 3, 'service', True)
    link(nodes, links, 2, 0, 3, 'template', True)
    nodes[3]['outputs'][0]['links'].append(3)
    links.append({'id': 3, 'origin_id': 3, 'origin_slot': 0, 'target_id': -20, 'target_slot': 0, 'type': 'SAMUEL_ENHANCER_CONFIG'})
    return {'id': sub_id, 'version': 1, 'revision': 0, 'name': 'Samuel-Enhancer · ' + ('编辑配置' if preset == 'editing' else '生图配置'),
            'state': {'lastGroupId': 0, 'lastNodeId': 3, 'lastLinkId': 3, 'lastRerouteId': 0},
            'config': {}, 'inputNode': {'id': -10, 'bounding': [0, 100, 120, 60]},
            'outputNode': {'id': -20, 'bounding': [1640, 100, 150, 80]},
            'inputs': [], 'outputs': [{'id': uid(name + '/output'), 'name': 'config', 'type': 'SAMUEL_ENHANCER_CONFIG', 'linkIds': [3]}],
            'widgets': [], 'nodes': list(nodes.values()), 'groups': [], 'links': links, 'extra': {}}


def workflow(task='text', creative=False, refine=False, precise=False, official=False):
    preset = 'editing' if task == 'edit' else 'generation'
    subgraph = config_subgraph(preset, official)
    config = {'id': 1, 'type': subgraph['id'], 'title': subgraph['name'], 'pos': [30, 30], 'size': [310, 90],
              'flags': {}, 'order': 0, 'mode': 0, 'inputs': [],
              'outputs': [{'name': 'config', 'type': 'SAMUEL_ENHANCER_CONFIG', 'links': [], 'slot_index': 0}],
              'properties': {}, 'widgets_values': []}
    request = ('云海中的东方天宫，一位行者站在巨柱旁，构图庄严而清寂。' if task == 'text'
               else '保留人物服装和姿态，设计为雨夜街道。' if creative
               else '将蓝色长袍改为白色，保持人物身份、站姿和原有构图。' if task == 'edit'
               else '')
    task_type = {'text': 'SamuelEnhancerGeneration', 'reference': 'SamuelEnhancerReverse', 'edit': 'SamuelEnhancerEdit'}[task]
    settings = {'quality_mode': '精确' if precise else '标准'}
    if task == 'reference':
        settings['task_mode'] = '参考图创作' if creative else '忠实反推'
    if task == 'text':
        settings['task_mode'] = '忠实润色' if refine else '创作扩写'
    nodes = {
        1: config,
        2: node(2, 'SamuelEnhancerTextInput', [30, 190], {'text': request}, '用户需求（反推可留空）'),
        3: node(3, task_type, [520, 30], settings),
        4: node(4, 'SamuelEnhancerPromptEditor', [960, 30], title='先生成原稿，载入后手改，再运行下游'),
        5: node(5, 'SamuelEnhancerPreview', [1660, 30], title='最终提示词'),
        6: node(6, 'SamuelEnhancerPreview', [960, 930], title='运行信息（不是模型思考过程）'),
    }
    nodes[2]['size'] = [440, 260]
    nodes[3]['size'] = [340, 200]
    nodes[4]['size'] = [620, 680]
    nodes[5]['size'] = [600, 760]
    nodes[6]['size'] = [640, 300]
    links = []
    link(nodes, links, 1, 0, 3, 'config')
    link(nodes, links, 2, 0, 3, 'user_text')
    link(nodes, links, 3, 0, 4, 'source')
    link(nodes, links, 4, 0, 5, 'text')
    link(nodes, links, 3, 1, 6, 'text')
    if task != 'text':
        nodes[7] = {'id': 7, 'type': 'LoadImage', 'pos': [30, 530], 'size': [400, 340],
                    'flags': {}, 'order': 0, 'mode': 0, 'inputs': [],
                    'outputs': [{'name': 'IMAGE', 'type': 'IMAGE', 'links': [], 'slot_index': 0},
                                {'name': 'MASK', 'type': 'MASK', 'links': [], 'slot_index': 1}],
                    'properties': {'Node name for S&R': 'LoadImage'}, 'widgets_values': ['select-reference.png', 'image']}
        link(nodes, links, 7, 0, 3, 'image')
    for index, item in enumerate(nodes.values()):
        item['order'] = index
    return {'id': uid(f'workflow/{task}/{creative}/{refine}/{precise}/{official}'), 'revision': 0,
            'last_node_id': max(nodes), 'last_link_id': len(links), 'nodes': list(nodes.values()), 'links': links,
            'definitions': {'subgraphs': [subgraph]}, 'groups': [], 'config': {},
            'extra': {'ds': {'scale': 0.65, 'offset': [20, 20]}, 'frontendVersion': '1.24.3'}, 'version': 0.4}


def main():
    output = ROOT / 'examples'
    output.mkdir(exist_ok=True)
    # Explicit obsolete filenames only: do not remove user-authored workflows.
    for old in ('text-local', 'image-local', 'image-edit-local', 'text-openai', 'image-openai',
                'text-precise-local', 'image-precise-local', 'image-edit-precise-local'):
        (output / (old + '.json')).unlink(missing_ok=True)
    variants = {'text-create': {}, 'text-refine': {'refine': True},
                'reference-describe': {'task': 'reference'}, 'reference-create': {'task': 'reference', 'creative': True},
                'image-edit': {'task': 'edit'}, 'reference-precise': {'task': 'reference', 'precise': True},
                'text-openai': {'official': True}}
    for name, options in variants.items():
        (output / (name + '.json')).write_text(json.dumps(workflow(**options), ensure_ascii=False, indent=2), encoding='utf-8')
    print('Wrote', len(variants), 'independent workflows with editable native configuration subgraphs.')


if __name__ == '__main__':
    main()
