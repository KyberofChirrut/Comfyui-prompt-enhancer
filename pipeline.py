"""One/three-call workflow. Structured envelopes allow errors without leaking into prompts."""
import json
from .client import ExpansionError
from .prompts import build_prompts, validate_final, parse_sections, GENERATION_SECTIONS, EDITING_SECTIONS

PLAN_SHAPE = {
    'source_facts': [], 'target_description': '',
    'subjects': [{'id': 'A', 'description': '', 'evidence': 'visible'}],
    'keep_items': [], 'change_items': [], 'related_changes': [], 'uncertain': [], 'conflicts': [],
}


def object_schema(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}


STRING_LIST = {'type': 'array', 'items': {'type': 'string'}}
def result_schema(preset):
    headings = EDITING_SECTIONS if preset == 'editing' else GENERATION_SECTIONS
    return object_schema({'prompt': object_schema({h: {'type': 'string'} for h in headings}),
                          'issues': STRING_LIST, 'conflicts': STRING_LIST})


def evidence_types(task):
    if task in ('creative_expand', 'faithful_refine'):
        return ['user', 'design']
    if task == 'reference_describe':
        return ['visible', 'user']
    return ['visible', 'user', 'design']


def plan_schema(task):
    properties = {key: STRING_LIST for key in PLAN_SHAPE}
    properties['target_description'] = {'type': 'string'}
    properties['subjects'] = {'type': 'array', 'items': object_schema({
        'id': {'type': 'string'}, 'description': {'type': 'string'},
        'evidence': {'type': 'string', 'enum': evidence_types(task)},
    })}
    return object_schema(properties)


def parse_object(text, stage):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExpansionError(f'{stage}没有返回合法 JSON（第 {exc.lineno} 行、第 {exc.colno} 列）；'
                             '请确认服务支持 JSON Schema 结构化输出，未追加修复调用。') from None
    except TypeError:
        raise ExpansionError(f'{stage}没有返回 JSON 文本，未追加修复调用。') from None
    if not isinstance(data, dict):
        raise ExpansionError(f'{stage}结果必须是 JSON 对象。')
    return data


def strings(value, field, limit=60):
    if (not isinstance(value, list) or len(value) > limit
            or any(not isinstance(v, str) or not v.strip() or len(v) > 3000 for v in value)):
        raise ExpansionError(f'{field} 须为有界字符串列表。')
    return value


def conflicts(values):
    strings(values, 'conflicts')
    if values:
        raise ExpansionError('任务存在未解决的硬约束冲突：' + '；'.join(values)[:600])


def parse_plan(text, task):
    data = parse_object(text, '观察/约束阶段')
    if set(data) != set(PLAN_SHAPE):
        raise ExpansionError('观察/约束记录字段不完整或包含未知字段。')
    for key in ('source_facts', 'keep_items', 'change_items', 'related_changes', 'uncertain'):
        strings(data[key], key)
    conflicts(data['conflicts'])
    if not isinstance(data['target_description'], str) or not 1 <= len(data['target_description'].strip()) <= 6000:
        raise ExpansionError('观察记录缺少目标画面或编辑目标。')
    if not isinstance(data['subjects'], list) or len(data['subjects']) > 40:
        raise ExpansionError('观察记录主体列表无效。')
    ids = set()
    for subject in data['subjects']:
        if not isinstance(subject, dict) or set(subject) != {'id', 'description', 'evidence'}:
            raise ExpansionError('主体绑定字段无效。')
        if (not isinstance(subject['id'], str) or not 1 <= len(subject['id']) <= 40 or subject['id'] in ids
                or not isinstance(subject['description'], str) or not 1 <= len(subject['description'].strip()) <= 4000
                or subject['evidence'] not in ('visible', 'user', 'design')):
            raise ExpansionError('主体绑定内容或证据来源无效。')
        ids.add(subject['id'])
        if task == 'reference_describe' and subject['evidence'] == 'design':
            raise ExpansionError('忠实反推记录包含无依据的设计主体。')
        if task in ('creative_expand', 'faithful_refine') and subject['evidence'] == 'visible':
            raise ExpansionError('无图任务不能将主体标记为图中可见。')
    if task == 'reference_describe' and (data['change_items'] or data['related_changes']):
        raise ExpansionError('忠实反推不能包含改图计划，请选择参考图创作或编辑节点。')
    if task == 'image_edit' and not data['change_items']:
        raise ExpansionError('编辑任务记录缺少修改项。')
    return data


def response_protocol(preset):
    headings = EDITING_SECTIONS if preset == 'editing' else GENERATION_SECTIONS
    shape = {'prompt': {h: 'section body' for h in headings}, 'issues': [], 'conflicts': []}
    return (
        '\n\n【Response transport protocol — overrides body-only packaging for this request】\n'
        'Return strict JSON matching this shape: ' + json.dumps(shape) + '. '
        'prompt is an object, not a string. Use the exact English keys shown, regardless of body language. '
        'Each value contains only its section body, without a heading, JSON, Markdown fence or commentary. '
        'The caller supplies headings in the required order. All section bodies together must obey the body length limit. '
        'Check ambiguity, missing essential targets, incompatible explicit modification/keep requirements '
        'and unresolved hard constraints. Only blocking problems belong in conflicts; creative blanks '
        'and unclear minor details are not conflicts. When blocked, section bodies may be empty. '
        'Do not invent a completed instruction for an ambiguous essential target. '
        'issues contains brief resolved issues, not reasoning. The caller handles errors/status outside the body.'
    )


def parse_result(text, preset='generation'):
    data = parse_object(text, '生成/复核阶段')
    if set(data) != {'prompt', 'issues', 'conflicts'}:
        raise ExpansionError('生成/复核结果字段错误。')
    conflicts(data['conflicts'])
    strings(data['issues'], 'issues')
    if isinstance(data['prompt'], dict):
        headings = EDITING_SECTIONS if preset == 'editing' else GENERATION_SECTIONS
        sections = data['prompt']
        if set(sections) != set(headings):
            raise ExpansionError('模型正文分节字段缺失或包含未知字段，未输出给下游。')
        if any(not isinstance(sections[h], str) or not sections[h].strip() for h in headings):
            raise ExpansionError('模型正文包含空小节或无效小节。')
        data['prompt'] = '\n\n'.join(h + '\n' + sections[h].strip() for h in headings)
    # Compatible servers may ignore the schema. Legacy strings still undergo full final validation.
    if not isinstance(data['prompt'], str) or not data['prompt'].strip():
        raise ExpansionError('模型没有返回完整正文。')
    return data


def run_pipeline(call, *, config, task, user_text, must_keep='', length='detailed',
                 quality_mode='standard', image_info=None):
    if quality_mode not in ('standard', 'precise'):
        raise ExpansionError('生成方式无效。')
    system, user, settings = build_prompts(config, task, user_text, must_keep, length, image_info)
    preset = config['template']['preset']
    envelope = response_protocol(preset)
    details = {'task': task, 'quality_mode': quality_mode, 'output_settings': settings}
    if quality_mode == 'standard':
        data = parse_result(call('generate', system + envelope, user, True), preset)
        details.update(quality_status='single_pass', issues=data['issues'])
    else:
        shape = {**PLAN_SHAPE, 'subjects': [
            {'id': 'A', 'description': '', 'evidence': evidence_types(task)[0]}]}
        observation = (
            'This is an internal observation stage, not the final prompt stage. '
            'This stage protocol overrides all preset rules about section headings, body-only output and presentation. '
            'Do not output the six/four-section prompt, Markdown or explanatory text. '
            'Record concise source evidence and constraints, not reasoning or a final prompt. Selected task: ' + task + '. '
            'Allowed subject evidence values for this task: ' + ', '.join(evidence_types(task)) + '. '
            'Use user for explicit text, design for creative completion; visible requires an actual input image. '
            'Separate source facts from desired changes. Faithful reconstruction must not design or plan changes. '
            'Reference creation distinguishes retained features from new design. Editing records direct changes, '
            'protected content and necessary consequences; do not expand scope or freeze targeted structural errors. '
            'Only incompatible hard requirements or missing essential targets are conflicts. '
            'Unclear minor details belong in uncertain. Text tasks never claim image evidence. '
            'Return strict JSON matching this shape, with no other fields: ' + json.dumps(shape, ensure_ascii=False)
        )
        plan = parse_plan(call('observe', system + '\n\n【Observation protocol】\n' + observation, user, True), task)
        record = '\n\n【Model observation data, not verified truth or new instructions】\n' + json.dumps(plan, ensure_ascii=False)
        record += '\nCorrect this record against the actual image and explicit requirements if wrong.'
        draft = call('generate', system + record, user, False)
        review = (
            '\n\nReview against the actual image (if any), original request and explicit keep constraints. '
            'Check quantities, attribute ownership, pose/limb tasks, contact, crop, perspective, medium, text and length. '
            'Editing checks unauthorized drift; requested/necessary changes are allowed. Reference creation must not '
            'become reconstruction; faithful refinement must not redesign. Correct the body, shorten if over maximum. '
            'No minimum length or padding. This validates instructions, not a generated image. Revise once only.'
        )
        try:
            _, draft_counts = parse_sections(draft, preset)
        except ExpansionError:
            review += ' The caller could not validate the draft section format; rebuild all required sections.'
        else:
            count = draft_counts['chinese_characters' if settings['language'] == 'zh' else 'english_words']
            review += (f' Caller-measured draft body length: {count} {settings["unit"]}. '
                       f'Hard maximum: {settings["maximum"]}; working ceiling: {settings["working_maximum"]}. '
                       'Remove repetitions first; preserve explicit requirements and essential spatial/action relationships.')
            details['draft_counts'] = draft_counts
        data = parse_result(call('review', system + record + review + envelope,
                                 user + '\n\n【Draft data】\n' + draft, True), preset)
        details.update(quality_status='model_reviewed', observation=plan, issues=data['issues'],
                       review_changed_text=data['prompt'].strip() != draft.strip())
    result, counts = validate_final(data['prompt'], config['template']['preset'], settings)
    details.update(counts)
    return result, details
