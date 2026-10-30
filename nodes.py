"""0.3 independent tasks, reusable configuration and non-LLM text editing."""
import json
import math
import re
import time

from .client import ExpansionError, build_payload, parse_response, request_json, resolve_connection
from .images import encode_image
from .pipeline import run_pipeline, plan_schema, result_schema
from .prompts import (PRESETS, TASK_RULES, load_preset, require_text, runtime_fingerprint,
                      template_digest, build_prompts)

VERSION = '0.3.5'
SERVICE = 'SAMUEL_ENHANCER_SERVICE'
TEMPLATE = 'SAMUEL_ENHANCER_TEMPLATE'
CONFIG = 'SAMUEL_ENHANCER_CONFIG'
TEXT_MODES = {'创作扩写': 'creative_expand', '忠实润色': 'faithful_refine'}
REFERENCE_MODES = {'忠实反推': 'reference_describe', '参考图创作': 'reference_create'}
LENGTHS = {'详细': 'detailed', '简单': 'simple'}
QUALITIES = {'标准': 'standard', '精确': 'precise'}


def enum(value, choices, name):
    if value not in choices:
        raise ExpansionError(f'{name}无效。')
    return value


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ExpansionError(f'{name}须为 {low}—{high} 的整数。')
    return value


class SamuelEnhancerService:
    CATEGORY = 'Samuel-Enhancer/配置'
    RETURN_TYPES = (SERVICE,)
    RETURN_NAMES = ('service',)
    FUNCTION = 'configure'
    DESCRIPTION = '放在配置子图内。仅保存密钥环境变量名，执行任务时才读取密钥。'

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'provider': (['local', 'openai'], {'default': 'local'}),
            'base_url': ('STRING', {'default': 'http://127.0.0.1:8000/v1'}),
            'model': ('STRING', {'default': ''}),
            'api_type': (['auto', 'chat_completions', 'responses'], {'default': 'auto'}),
            'api_key_env': ('STRING', {'default': '', 'tooltip': '环境变量名，不填实际密钥。'}),
            'max_output_tokens': ('INT', {'default': 4096, 'min': 256, 'max': 65536, 'step': 256}),
            'timeout_seconds': ('INT', {'default': 300, 'min': 10, 'max': 1800}),
            'image_max_side': ('INT', {'default': 1536, 'min': 256, 'max': 4096, 'step': 64}),
            'use_temperature': ('BOOLEAN', {'default': False}),
            'temperature': ('FLOAT', {'default': 0.6, 'min': 0.0, 'max': 2.0, 'step': 0.05}),
            'advanced_json': ('STRING', {'default': '{}', 'multiline': True}),
        }}

    def configure(self, provider='local', base_url='http://127.0.0.1:8000/v1', model='', api_type='auto',
                  api_key_env='', max_output_tokens=4096, timeout_seconds=300, image_max_side=1536,
                  use_temperature=False, temperature=0.6, advanced_json='{}'):
        enum(provider, ('local', 'openai'), '服务类型')
        enum(api_type, ('auto', 'chat_completions', 'responses'), 'API 类型')
        model = require_text(model, '模型名称', False, 300)
        base_url = require_text(base_url, '服务地址', False, 2000)
        api_key_env = require_text(api_key_env, '密钥环境变量名', limit=200)
        if api_key_env and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', api_key_env):
            raise ExpansionError('api_key_env 只能填写环境变量名。')
        integer(max_output_tokens, 256, 65536, '输出 token 预算')
        integer(timeout_seconds, 10, 1800, '超时')
        integer(image_max_side, 256, 4096, '图片最长边')
        if type(use_temperature) is not bool or type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ExpansionError('温度设置无效。')
        advanced_json = require_text(advanced_json, '高级 JSON', limit=10000)
        # Validate without reading credentials or making a request.
        build_payload('chat_completions', provider, model, '', '', None, max_output_tokens,
                      use_temperature, temperature, advanced_json)
        return ({'provider': provider, 'base_url': base_url, 'model': model, 'api_type': api_type,
                 'api_key_env': api_key_env, 'max_output_tokens': max_output_tokens,
                 'timeout_seconds': timeout_seconds, 'image_max_side': image_max_side,
                 'use_temperature': use_temperature, 'temperature': temperature, 'advanced_json': advanced_json},)


class SamuelEnhancerTemplate:
    CATEGORY = 'Samuel-Enhancer/配置'
    RETURN_TYPES = (TEMPLATE,)
    RETURN_NAMES = ('template',)
    FUNCTION = 'configure'
    DESCRIPTION = '选择预设自动切换正文和适配规则，各预设手稿分别保留。恢复默认按钮只重置当前预设。'

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'preset': (list(PRESETS), {'default': 'generation'}),
            'template_text': ('STRING', {'default': load_preset('generation'), 'multiline': True}),
            'task_rules': ('STRING', {'default': TASK_RULES, 'multiline': True}),
        }}

    def configure(self, preset='generation', template_text='', task_rules=TASK_RULES):
        enum(preset, PRESETS, '模板类型')
        template_text = require_text(template_text, '模板正文', False, 100000)
        task_rules = require_text(task_rules, '任务适配规则', False, 20000)
        return ({'preset': preset, 'text': template_text, 'task_rules': task_rules,
                 'sha256': template_digest(preset, template_text, task_rules)},)


class SamuelEnhancerConfig:
    CATEGORY = 'Samuel-Enhancer/配置'
    RETURN_TYPES = (CONFIG,)
    RETURN_NAMES = ('config',)
    FUNCTION = 'configure'
    DESCRIPTION = '在子图内合并服务、模板、语言。可选宽高只指导构图，不改变出图尺寸；0 表示未指定。'

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'service': (SERVICE,), 'template': (TEMPLATE,),
            'language': (['en', 'zh'], {'default': 'en'}),
            'output_policy': (['prefer_input', 'node_controls'], {'default': 'prefer_input'}),
            'refresh_id': ('INT', {'default': 0, 'min': 0, 'max': 2147483647,
                                   'tooltip': '重新扩写编号，不是 LLM 或生图 seed。'}),
        }, 'optional': {
            'target_width': ('INT', {'forceInput': True, 'default': 0, 'min': 0, 'max': 32768}),
            'target_height': ('INT', {'forceInput': True, 'default': 0, 'min': 0, 'max': 32768}),
        }}

    def configure(self, service, template, language='en', output_policy='prefer_input', refresh_id=0,
                  target_width=0, target_height=0):
        if not isinstance(service, dict) or not isinstance(template, dict):
            raise ExpansionError('请连接有效服务配置与模板预设。')
        # Revalidate API-prompt supplied objects too; never trust arbitrary serialized metadata.
        service = SamuelEnhancerService().configure(**service)[0]
        try:
            template = SamuelEnhancerTemplate().configure(template['preset'], template['text'], template['task_rules'])[0]
        except (KeyError, TypeError):
            raise ExpansionError('模板预设结构无效。') from None
        enum(language, ('en', 'zh'), '输出语言')
        enum(output_policy, ('prefer_input', 'node_controls'), '输出优先级')
        integer(refresh_id, 0, 2147483647, '重新扩写编号')
        integer(target_width, 0, 32768, '目标宽度')
        integer(target_height, 0, 32768, '目标高度')
        if bool(target_width) != bool(target_height):
            raise ExpansionError('目标宽高必须同时提供，或均为 0。')
        return ({'service': service, 'template': template, 'language': language, 'output_policy': output_policy,
                 'refresh_id': refresh_id, 'target_width': target_width, 'target_height': target_height},)


def task_schema(modes=None, image=False, optional_text=False):
    required = {'config': (CONFIG,)}
    if image:
        required['image'] = ('IMAGE',)
    if not optional_text:
        required['user_text'] = ('STRING', {'forceInput': True})
    if modes:
        required['task_mode'] = (list(modes), {'default': next(iter(modes))})
    required.update(length=(list(LENGTHS), {'default': '详细'}),
                    quality_mode=(list(QUALITIES), {'default': '标准'}))
    optional = {'must_keep': ('STRING', {'forceInput': True})}
    if optional_text:
        optional = {'user_text': ('STRING', {'forceInput': True}), **optional}
    return {'required': required, 'optional': optional}


class TaskBase:
    CATEGORY = 'Samuel-Enhancer/任务'
    RETURN_TYPES = ('STRING', 'STRING')
    RETURN_NAMES = ('prompt', 'info')
    FUNCTION = 'execute'

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return runtime_fingerprint()

    def run(self, config, task, user_text='', must_keep='', length='详细', quality_mode='标准', image=None):
        if not isinstance(config, dict):
            raise ExpansionError('请连接任务配置。')
        try:
            config = SamuelEnhancerConfig().configure(**config)[0]
        except (KeyError, TypeError):
            raise ExpansionError('任务配置结构无效。') from None
        length = LENGTHS[enum(length, LENGTHS, '篇幅')]
        quality_mode = QUALITIES[enum(quality_mode, QUALITIES, '生成方式')]
        # Fail deterministic input errors before reading keys or making a request.
        preliminary_image = {'original_size': [0, 0]} if image is not None else None
        build_prompts(config, task, user_text, must_keep, length, preliminary_image)
        service = config['service']
        image_url, image_info = (None, None) if image is None else encode_image(image, service['image_max_side'])
        kind, endpoint, key = resolve_connection(service['provider'], service['api_type'], service['base_url'], service['api_key_env'])
        fingerprint = runtime_fingerprint()
        stages, usage = [], {}
        started = time.monotonic()
        try:
            from comfy.utils import ProgressBar
            from comfy.model_management import throw_exception_if_processing_interrupted
            progress = ProgressBar(3 if quality_mode == 'precise' else 1)
            check_interrupt = throw_exception_if_processing_interrupted
        except ImportError:
            progress, check_interrupt = None, lambda: None

        def call(stage, system, user, structured):
            check_interrupt()
            if runtime_fingerprint() != fingerprint:
                raise ExpansionError('运行代码在请求期间发生改变，请重新运行。')
            payload = build_payload(kind, service['provider'], service['model'], system, user, image_url,
                                    service['max_output_tokens'], service['use_temperature'],
                                    service['temperature'], service['advanced_json'],
                                    response_schema=(plan_schema(task) if stage == 'observe'
                                                     else result_schema(config['template']['preset']))
                                    if structured else None)
            stage_start = time.monotonic()
            try:
                text, token_usage = parse_response(kind, request_json(endpoint, key, payload, service['timeout_seconds']), allow_json=structured)
            except ExpansionError as exc:
                raise ExpansionError(f'{stage} 阶段失败（未自动重试）：{exc}') from None
            check_interrupt()
            stages.append({'stage': stage, 'seconds': round(time.monotonic() - stage_start, 2), 'usage': token_usage})
            for name, value in token_usage.items():
                usage[name] = usage.get(name, 0) + value
            if progress:
                progress.update_absolute(len(stages))
            return text

        prompt, details = run_pipeline(call, config=config, task=task, user_text=user_text, must_keep=must_keep,
                                       length=length, quality_mode=quality_mode, image_info=image_info)
        if runtime_fingerprint() != fingerprint:
            raise ExpansionError('运行期间代码发生改变，请重新运行。')
        warnings = []
        if image_info and config['target_width'] and task in ('reference_describe', 'image_edit'):
            width, height = image_info['original_size']
            if width * config['target_height'] != height * config['target_width']:
                warnings.append('目标画幅与原图不同；保真/编辑仍保留原图构图，实际尺寸由下游控制。')
        info = {'version': VERSION, **details, 'provider': service['provider'], 'model': service['model'],
                'api_type': kind, 'elapsed_seconds': round(time.monotonic() - started, 2),
                'request_count': len(stages), 'stages': stages, 'usage': usage, 'image': image_info,
                'template': config['template']['preset'], 'template_sha256': config['template']['sha256'],
                'runtime_sha256': fingerprint, 'refresh_id': config['refresh_id'], 'warnings': warnings}
        return prompt, json.dumps(info, ensure_ascii=False, indent=2)


class SamuelEnhancerGeneration(TaskBase):
    DESCRIPTION = '独立文本创作/忠实润色。用户文字从外部文本框连接；无负面词接口。'

    @classmethod
    def INPUT_TYPES(cls):
        return task_schema(TEXT_MODES)

    def execute(self, config, user_text, task_mode='创作扩写', length='详细', quality_mode='标准', must_keep=''):
        return self.run(config, TEXT_MODES[enum(task_mode, TEXT_MODES, '任务模式')], user_text, must_keep, length, quality_mode)


class SamuelEnhancerReverse(TaskBase):
    DESCRIPTION = '忠实反推可不接用户文字；参考图创作需连接新想法。始终读取实际参考图。'

    @classmethod
    def INPUT_TYPES(cls):
        return task_schema(REFERENCE_MODES, image=True, optional_text=True)

    def execute(self, config, image, task_mode='忠实反推', length='详细', quality_mode='标准', user_text='', must_keep=''):
        return self.run(config, REFERENCE_MODES[enum(task_mode, REFERENCE_MODES, '任务模式')], user_text, must_keep, length, quality_mode, image)


class SamuelEnhancerEdit(TaskBase):
    DESCRIPTION = '根据原图生成四节编辑指令；不生成图像，不输出六节完整场景。'

    @classmethod
    def INPUT_TYPES(cls):
        return task_schema(image=True)

    def execute(self, config, image, user_text, length='详细', quality_mode='标准', must_keep=''):
        return self.run(config, 'image_edit', user_text, must_keep, length, quality_mode, image)


class SamuelEnhancerTextInput:
    CATEGORY = 'Samuel-Enhancer/文本'
    RETURN_TYPES = ('STRING',)
    RETURN_NAMES = ('text',)
    FUNCTION = 'output'

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'text': ('STRING', {'default': '', 'multiline': True})}}

    def output(self, text=''):
        require_text(text, '文本')
        return (text,)


class SamuelEnhancerPreview:
    CATEGORY = 'Samuel-Enhancer/文本'
    RETURN_TYPES = ('STRING',)
    RETURN_NAMES = ('text',)
    FUNCTION = 'preview'
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'text': ('STRING', {'forceInput': True})}}

    def preview(self, text):
        return {'ui': {'text': [text]}, 'result': (text,)}


class SamuelEnhancerPromptEditor:
    CATEGORY = 'Samuel-Enhancer/文本'
    RETURN_TYPES = ('STRING',)
    RETURN_NAMES = ('prompt',)
    FUNCTION = 'edit'
    OUTPUT_NODE = True
    DESCRIPTION = '先预览原稿，点击载入原稿后手改，再运行下游。上游更新不覆盖手稿；本节点不调用模型。'

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'source': ('STRING', {'forceInput': True}),
            'mode': (['直接使用', '完整编辑', '追加补充'], {'default': '直接使用'}),
            'edited_text': ('STRING', {'default': '', 'multiline': True}),
        }, 'optional': {'addition': ('STRING', {'forceInput': True,
                         'tooltip': '追加补充模式使用；连接外部文本框，只拼接，不自动消除语义冲突。'})}}

    def edit(self, source, mode='直接使用', edited_text='', addition=''):
        require_text(source, '生成原稿')
        require_text(edited_text, '最终提示词')
        require_text(addition, '追加内容')
        enum(mode, ('直接使用', '完整编辑', '追加补充'), '文本编辑方式')
        if mode == '完整编辑':
            if not edited_text.strip():
                raise ExpansionError('完整编辑模式下正文为空，请先载入原稿或手动填写。')
            result = edited_text
        elif mode == '追加补充':
            result = source.rstrip() + ('\n\n' + addition.strip() if addition.strip() else '')
        else:
            result = source
        return {'ui': {'source': [source], 'text': [result]}, 'result': (result,)}
