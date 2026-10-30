import copy
import json
import unittest
from unittest.mock import patch
import numpy as np
from test_nodes import body, envelope, chat, configuration, ROOT
from samuel_enhancer_test.nodes import SamuelEnhancerReverse, SamuelEnhancerEdit, SamuelEnhancerGeneration
from samuel_enhancer_test.pipeline import PLAN_SHAPE, result_schema, plan_schema, parse_object
from samuel_enhancer_test.client import ExpansionError


def plan(task='reference_describe'):
    data = copy.deepcopy(PLAN_SHAPE)
    data.update(source_facts=['人物位于左下角'], target_description='保留人物姿态和构图。',
                subjects=[{'id': 'A', 'description': '左下人物', 'evidence': 'visible'}], keep_items=['原有站姿'])
    if task == 'image_edit':
        data.update(target_description='将长袍改为白色', change_items=['长袍改白色'], related_changes=['衣料受光颜色'])
    return data


class PipelineTests(unittest.TestCase):
    def execute(self, replies, task='reference_describe', api_type='chat_completions', language='en'):
        config = configuration(preset='editing' if task == 'image_edit' else 'generation', language=language)
        config['service']['api_type'] = api_type
        self.requests = []
        def request(endpoint, key, payload, timeout):
            self.requests.append(payload)
            value = replies[len(self.requests) - 1]
            if isinstance(value, Exception):
                raise value
            if api_type == 'responses':
                return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': value}]}],
                        'usage': {'total_tokens': 30}}
            return chat(value)
        with patch('samuel_enhancer_test.nodes.request_json', side_effect=request):
            if task == 'image_edit':
                return SamuelEnhancerEdit().execute(config, np.zeros((1, 10, 20, 3)), '蓝袍改白袍', quality_mode='精确')
            if task == 'creative_expand':
                return SamuelEnhancerGeneration().execute(config, '人物站立', quality_mode='精确')
            return SamuelEnhancerReverse().execute(config, np.zeros((1, 10, 20, 3)), quality_mode='精确')

    def test_three_calls_actual_image_at_each_stage_and_only_reviewed_output(self):
        result, info = self.execute([json.dumps(plan('image_edit')), body(edit=True, content='错误草稿'), envelope(body(edit=True))], 'image_edit')
        info = json.loads(info)
        self.assertEqual(result, body(edit=True))
        self.assertEqual(info['request_count'], 3)
        self.assertEqual(info['usage']['total_tokens'], 69)
        self.assertEqual([s['stage'] for s in info['stages']], ['observe', 'generate', 'review'])
        images = [p['messages'][1]['content'][1]['image_url']['url'] for p in self.requests]
        self.assertEqual(len(set(images)), 1)
        self.assertIn('错误草稿', self.requests[2]['messages'][1]['content'][0]['text'])
        self.assertNotIn('错误草稿', result)
        self.assertEqual(self.requests[0]['response_format']['json_schema']['schema'], plan_schema('image_edit'))
        self.assertNotIn('response_format', self.requests[1])
        self.assertEqual(self.requests[2]['response_format']['json_schema']['schema'], result_schema('editing'))

    def test_responses_three_stage_protocol(self):
        result, info = self.execute([json.dumps(plan()), body(), envelope()], api_type='responses')
        self.assertEqual(result, body())
        self.assertEqual(json.loads(info)['usage']['total_tokens'], 90)
        self.assertTrue(all(p['input'][0]['content'][1]['type'] == 'input_image' for p in self.requests))
        self.assertEqual(self.requests[0]['text']['format']['schema'], plan_schema('reference_describe'))
        self.assertTrue(self.requests[0]['text']['format']['strict'])
        self.assertNotIn('text', self.requests[1])
        self.assertEqual(self.requests[2]['text']['format']['schema'], result_schema('generation'))
        self.assertTrue(all('response_format' not in p for p in self.requests))

    def test_text_stage_uses_text_evidence_in_schema_and_example(self):
        data = plan()
        data['subjects'][0]['evidence'] = 'user'
        self.execute([json.dumps(data), body(), envelope()], 'creative_expand')
        payload = self.requests[0]
        schema = payload['response_format']['json_schema']['schema']
        self.assertEqual(schema['properties']['subjects']['items']['properties']['evidence']['enum'], ['user', 'design'])
        system = payload['messages'][0]['content']
        protocol = system.split('【Observation protocol】')[1]
        self.assertIn('overrides all preset rules', protocol)
        self.assertIn('"evidence": "user"', protocol)
        self.assertNotIn('"evidence": "visible"', protocol)
        self.assertFalse(schema['additionalProperties'])

    def test_faithful_schema_cannot_design_observed_subjects(self):
        schema = plan_schema('reference_describe')
        self.assertEqual(schema['properties']['subjects']['items']['properties']['evidence']['enum'], ['visible', 'user'])
        self.assertEqual(set(schema['required']), set(PLAN_SHAPE))

    def test_invalid_json_diagnostic_does_not_expose_model_content(self):
        with self.assertRaises(ExpansionError) as raised:
            parse_object('PRIVATE invalid output', '观察/约束阶段')
        message = str(raised.exception)
        self.assertIn('第 1 行、第 1 列', message)
        self.assertNotIn('PRIVATE', message)

    def test_invalid_or_conflicting_plan_stops_after_first_call(self):
        bad = plan()
        bad['conflicts'] = ['必须同时改变并保持同一属性']
        for value in ('bad JSON', '{}', json.dumps(bad)):
            with self.assertRaises(ExpansionError):
                self.execute([value])
            self.assertEqual(len(self.requests), 1)

    def test_unsupported_design_in_faithful_observation_stops(self):
        bad = plan()
        bad['subjects'][0]['evidence'] = 'design'
        with self.assertRaises(ExpansionError):
            self.execute([json.dumps(bad)])

    def test_failed_review_does_not_return_draft_or_retry(self):
        with self.assertRaisesRegex(ExpansionError, 'review'):
            self.execute([json.dumps(plan()), body(), ExpansionError('timeout')])
        self.assertEqual(len(self.requests), 3)

    def test_review_conflicts_and_overlimit_block_downstream(self):
        for final in (envelope('', ['目标仍不明确']), envelope(body(content='word ' * 200))):
            with self.assertRaises(ExpansionError):
                self.execute([json.dumps(plan()), body(), final])
            self.assertEqual(len(self.requests), 3)

    def test_no_image_evidence_in_text_observation(self):
        with self.assertRaisesRegex(ExpansionError, '无图'):
            self.execute([json.dumps(plan())], 'creative_expand')

    def test_review_receives_measured_draft_count_and_working_ceiling(self):
        result, info = self.execute([json.dumps(plan()), body(content='word ' * 200), envelope()])
        review = self.requests[2]['messages'][0]['content']
        self.assertIn('Caller-measured draft body length: 1200 English words', review)
        self.assertIn('Hard maximum: 800; working ceiling: 680', review)
        self.assertEqual(json.loads(info)['draft_counts']['english_words'], 1200)
        self.assertEqual(result, body())
        self.assertEqual(len(self.requests), 3)

    def test_unsectioned_draft_can_be_rebuilt_in_existing_review_call(self):
        result, _ = self.execute([json.dumps(plan()), 'Unsectioned draft body.', envelope()])
        self.assertEqual(result, body())
        self.assertIn('rebuild all required sections', self.requests[2]['messages'][0]['content'])
        self.assertEqual(len(self.requests), 3)

    def test_actual_chinese_heading_draft_and_structured_final_regression(self):
        fixture = json.loads((ROOT / 'tests/fixtures/llama-chinese-draft-and-result.json').read_text(encoding='utf-8'))
        data = plan()
        data['subjects'][0]['evidence'] = 'user'
        result, info = self.execute([json.dumps(data), fixture['draft'], json.dumps(fixture['result'])],
                                    task='creative_expand', language='zh')
        info = json.loads(info)
        self.assertTrue(fixture['draft'].startswith('构图'))
        self.assertTrue(result.startswith('Composition\n'))
        self.assertIn('\n\nLighting\n', result)
        self.assertIn('rebuild all required sections', self.requests[2]['messages'][0]['content'])
        self.assertGreater(info['chinese_characters'], 100)
        self.assertLessEqual(info['chinese_characters'], 1500)
        self.assertEqual(info['request_count'], 3)


if __name__ == '__main__':
    unittest.main()
