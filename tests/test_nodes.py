"""Offline node/protocol tests using a real loopback HTTP endpoint. No remote LLM."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from unittest.mock import patch

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('samuel_enhancer_test', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
from samuel_enhancer_test.client import ExpansionError, build_payload, clean_text, parse_response, resolve_connection
from samuel_enhancer_test.images import encode_image
from samuel_enhancer_test.nodes import (SamuelEnhancerService, SamuelEnhancerTemplate, SamuelEnhancerConfig, SamuelEnhancerGeneration,
                                    SamuelEnhancerReverse, SamuelEnhancerEdit, SamuelEnhancerPromptEditor)
from samuel_enhancer_test.prompts import load_preset, GENERATION_SECTIONS, EDITING_SECTIONS, validate_final, output_language, parse_sections


def body(edit=False, content='A clear visual scene.'):
    return '\n\n'.join(h + '\n' + content for h in (EDITING_SECTIONS if edit else GENERATION_SECTIONS))


def envelope(prompt=None, conflicts=None):
    text = body() if prompt is None else prompt
    headings = EDITING_SECTIONS if text.startswith('Edit Goal') else GENERATION_SECTIONS
    if text:
        normalized, _ = parse_sections(text, 'editing' if headings == EDITING_SECTIONS else 'generation')
        sections = dict(part.split('\n', 1) for part in normalized.split('\n\n'))
    else:
        sections = {h: '' for h in headings}
    return json.dumps({'prompt': sections, 'issues': [], 'conflicts': conflicts or []})


def chat(content=None, finish='stop'):
    return {'choices': [{'message': {'content': envelope() if content is None else content, 'reasoning_content': 'PRIVATE'},
                         'finish_reason': finish}], 'usage': {'total_tokens': 23}}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.server.requests.append((self.path, dict(self.headers), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
        status, data = self.server.replies.pop(0)
        self.send_response(status)
        if status == 302:
            self.send_header('Location', self.server.base + '/must-not-follow')
        self.end_headers()
        self.wfile.write(data if isinstance(data, bytes) else json.dumps(data).encode())

    def log_message(self, *args):
        pass


def configuration(base='http://127.0.0.1:8000/v1', preset='generation', **settings):
    service = SamuelEnhancerService().configure(base_url=base, model='vision-model')[0]
    template = SamuelEnhancerTemplate().configure(preset, load_preset(preset))[0]
    return SamuelEnhancerConfig().configure(service, template, **settings)[0]


class NodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.base = f'http://127.0.0.1:{cls.server.server_port}/v1'
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.server.requests = []
        self.server.replies = [(200, chat())]
        self.env = patch.dict(os.environ, {'SAMUEL_ENHANCER_API_KEY': '', 'OPENAI_API_KEY': 'official-secret',
                                          'NO_PROXY': '127.0.0.1,localhost'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = configuration(self.server.base)

    def test_only_new_task_nodes_registered_and_text_is_external(self):
        self.assertNotIn('SamuelEnhancerExpand', package.NODE_CLASS_MAPPINGS)
        self.assertEqual(len(package.NODE_CLASS_MAPPINGS), 9)
        for name in ('SamuelEnhancerGeneration', 'SamuelEnhancerReverse', 'SamuelEnhancerEdit'):
            node = package.NODE_CLASS_MAPPINGS[name]
            self.assertTrue(package.NODE_DISPLAY_NAME_MAPPINGS[name].startswith('Samuel-Enhancer · '))
            schema = node.INPUT_TYPES()
            inputs = {**schema['required'], **schema['optional']}
            self.assertTrue(inputs['user_text'][1]['forceInput'])
            self.assertTrue(inputs['must_keep'][1]['forceInput'])
            self.assertFalse(any('negative' in key for key in inputs))
            self.assertEqual(node.RETURN_NAMES, ('prompt', 'info'))
        for name, node in package.NODE_CLASS_MAPPINGS.items():
            self.assertTrue(name.startswith('SamuelEnhancer'))
            self.assertTrue(package.NODE_DISPLAY_NAME_MAPPINGS[name].startswith('Samuel-Enhancer · '))
            self.assertTrue(node.CATEGORY.startswith('Samuel-Enhancer/'))

    def test_text_roundtrip_no_key_leak_or_negative_or_legacy_rules(self):
        result, info = SamuelEnhancerGeneration().execute(self.config, '雨夜中的两个人')
        path, headers, payload = self.server.requests[0]
        self.assertEqual(path, '/v1/chat/completions')
        self.assertNotIn('Authorization', headers)
        self.assertNotIn('temperature', payload)
        self.assertEqual(result, body())
        self.assertEqual(json.loads(info)['request_count'], 1)
        self.assertEqual(payload['response_format']['type'], 'json_schema')
        self.assertTrue(payload['response_format']['json_schema']['strict'])
        self.assertEqual(set(payload['response_format']['json_schema']['schema']['properties']), {'prompt', 'issues', 'conflicts'})
        self.assertNotIn('PRIVATE', result + info)
        system = payload['messages'][0]['content']
        self.assertIn('Selected task: creative_expand', system)
        self.assertIn('working ceiling of 680 English words', system)
        self.assertNotIn('1500—2500', system)
        self.assertNotIn('长版母例', system)
        self.assertNotIn('seed', payload)

    def test_faithful_refinement_is_explicit(self):
        SamuelEnhancerGeneration().execute(self.config, '人物站在白墙前。', task_mode='忠实润色')
        self.assertIn('Selected task: faithful_refine', self.server.requests[0][2]['messages'][0]['content'])

    def test_reference_without_text_sends_pixels_and_preserves_tensor(self):
        image = np.zeros((1, 40, 80, 3), dtype=np.float32)
        original = image.copy()
        SamuelEnhancerReverse().execute(self.config, image)
        payload = self.server.requests[0][2]
        image_part = payload['messages'][1]['content'][1]['image_url']['url']
        pixels = base64.b64decode(image_part.split(',', 1)[1])
        self.assertEqual(Image.open(BytesIO(pixels)).size, (80, 40))
        np.testing.assert_array_equal(image, original)

    def test_reference_creation_has_explicit_override(self):
        SamuelEnhancerReverse().execute(self.config, np.zeros((1, 10, 10, 3)), task_mode='参考图创作', user_text='改为雨夜街道')
        system = self.server.requests[0][2]['messages'][0]['content']
        self.assertIn('Selected task: reference_create', system)
        self.assertIn("overrides the preset's automatic", system)

    def test_edit_returns_four_sections_and_keeps_source_distinct(self):
        self.server.replies = [(200, chat(envelope(body(edit=True))))]
        config = configuration(self.server.base, 'editing')
        result, info = SamuelEnhancerEdit().execute(config, np.zeros((1, 8, 8, 3)), '衣服改白色', must_keep='保持人物站位')
        self.assertEqual(result, body(edit=True))
        self.assertEqual(json.loads(info)['task'], 'image_edit')
        self.assertIn('保持人物站位', self.server.requests[0][2]['messages'][1]['content'][0]['text'])

    def test_bad_inputs_stop_before_network(self):
        image = np.zeros((1, 10, 10, 3))
        operations = [lambda: SamuelEnhancerGeneration().execute(self.config, ''),
                      lambda: SamuelEnhancerReverse().execute(self.config, None),
                      lambda: SamuelEnhancerReverse().execute(self.config, image, task_mode='参考图创作'),
                      lambda: SamuelEnhancerEdit().execute(self.config, image, '改色'),
                      lambda: SamuelEnhancerEdit().execute(configuration(self.server.base, 'editing'), image, ''),
                      lambda: SamuelEnhancerReverse().execute(self.config, np.zeros((2, 10, 10, 3)))]
        for operation in operations:
            with self.assertRaises(ExpansionError):
                operation()
        self.assertFalse(self.server.requests)

    def test_responses_roundtrip_and_no_storage(self):
        self.config['service']['api_type'] = 'responses'
        self.server.replies = [(200, {'status': 'completed', 'output': [
            {'type': 'reasoning', 'summary': [{'text': 'PRIVATE'}]},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': envelope()}]}]})]
        result, _ = SamuelEnhancerReverse().execute(self.config, np.zeros((1, 10, 10, 3)))
        self.assertEqual(result, body())
        payload = self.server.requests[0][2]
        self.assertFalse(payload['store'])
        self.assertEqual(payload['input'][0]['content'][1]['type'], 'input_image')

    def test_http_failure_redirection_truncation_and_no_retry(self):
        for reply in ((401, b'private-key'), (302, b''), (200, b'<html>'), (200, chat(finish='length'))):
            self.server.requests = []
            self.server.replies = [reply]
            with self.assertRaises(ExpansionError) as error:
                SamuelEnhancerGeneration().execute(self.config, '人物')
            self.assertNotIn('private-key', str(error.exception))
            self.assertEqual(len(self.server.requests), 1)

    def test_conflict_envelope_never_returns_a_prompt(self):
        self.server.replies = [(200, chat(envelope('', ['同一衣服同时必须纯蓝和纯白'])))]
        with self.assertRaisesRegex(ExpansionError, '硬约束冲突'):
            SamuelEnhancerGeneration().execute(self.config, '人物')

    def test_language_and_dimension_settings(self):
        self.server.replies = [(200, chat(envelope(body(content='人物站在窗边。'))))]
        config = configuration(self.server.base, target_width=1024, target_height=1536)
        _, info = SamuelEnhancerGeneration().execute(config, '用中文输出，人物站在窗边。', length='简单')
        settings = json.loads(info)['output_settings']
        self.assertEqual((settings['language'], settings['maximum']), ('zh', 750))
        self.assertEqual(settings['working_maximum'], 637)
        self.assertEqual((settings['width'], settings['height']), (1024, 1536))
        self.assertEqual(output_language('en', 'prefer_input', '招牌写“中文输出”'), 'en')
        self.assertEqual(output_language('en', 'node_controls', '用中文输出'), 'en')

    def test_templates_identical_to_approved_baselines(self):
        for preset, baseline in [('generation', 'generation-production-v1.md'), ('editing', 'editing-production-v1.md')]:
            self.assertEqual((ROOT / 'templates/presets' / (preset + '.md')).read_bytes(),
                             (ROOT / 'docs/presets' / baseline).read_bytes())


class ConfigurationAndEditorTests(unittest.TestCase):
    def test_config_does_not_resolve_or_serialize_credentials(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            service = SamuelEnhancerService().configure(provider='openai', model='model')[0]
            self.assertNotIn('key', service)
            config = configuration(refresh_id=42)
            self.assertEqual(config['refresh_id'], 42)
        with self.assertRaises(ExpansionError):
            SamuelEnhancerService().configure(model='x', api_key_env='sk-actual-key')

    def test_parameter_and_dimension_validation(self):
        for values in ({'target_width': 1024}, {'refresh_id': True}, {'target_width': -1, 'target_height': -1}):
            with self.assertRaises(ExpansionError):
                configuration(**values)
        for values in ({'temperature': float('nan')}, {'max_output_tokens': True}, {'advanced_json': '{"messages":[]}'}):
            with self.assertRaises(ExpansionError):
                SamuelEnhancerService().configure(model='x', **values)

    def test_editor_modes_are_deterministic_and_exact(self):
        editor = SamuelEnhancerPromptEditor()
        self.assertEqual(editor.edit('原稿')['result'], ('原稿',))
        self.assertEqual(editor.edit('新版原稿', '完整编辑', '  手动版本\n')['result'], ('  手动版本\n',))
        self.assertEqual(editor.edit('原稿', '追加补充', addition='补充')['result'], ('原稿\n\n补充',))
        with self.assertRaises(ExpansionError):
            editor.edit('原稿', '完整编辑', '')

    def test_limits_are_upper_bounds_not_minimums(self):
        settings = {'language': 'en', 'maximum': 400}
        self.assertEqual(validate_final(body(), 'generation', settings)[0], body())
        with self.assertRaisesRegex(ExpansionError, '超过上限'):
            validate_final(body(content='word ' * 100), 'generation', settings)
        with self.assertRaises(ExpansionError):
            validate_final('Composition\nOnly one section.', 'generation', settings)

    def test_client_security_and_reasoning_contracts(self):
        for url in ('file:///x', 'http://user:pass@host/v1', 'http://host/v1?api_key=x',
                    'http://host/v1#x', 'http://host/v1/chat/completions', 'http://host:bad/v1'):
            with self.assertRaises(ExpansionError):
                resolve_connection('local', 'auto', url, '')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'official-secret'}):
            self.assertEqual(resolve_connection('openai', 'auto', 'http://untrusted', '')[1], 'https://api.openai.com/v1/responses')
        self.assertEqual(clean_text('<think>private</think>\n正文'), '正文')
        for text in ('<think>unfinished', 'text<think>mixed</think>'):
            with self.assertRaises(ExpansionError):
                clean_text(text)
        for data in ({'status': 'incomplete', 'output': []}, {'status': 'completed', 'output': []}):
            with self.assertRaises(ExpansionError):
                parse_response('responses', data)
        self.assertIn('max_completion_tokens', build_payload('chat_completions', 'openai', 'm', '', '', None, 1000))

    def test_image_resize_and_invalid_pixels(self):
        _, info = encode_image(np.zeros((1, 400, 1000, 3)), 512)
        self.assertEqual(info['sent_size'], [512, 205])
        with self.assertRaises(ExpansionError):
            encode_image(np.full((1, 10, 10, 3), np.nan))


if __name__ == '__main__':
    unittest.main()
