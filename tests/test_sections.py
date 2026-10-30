"""Formatting variations must not drop valid bodies or weaken section checks."""
import json
import unittest
from test_nodes import body, ROOT
from samuel_enhancer_test.pipeline import parse_result, result_schema
from samuel_enhancer_test.client import ExpansionError
from samuel_enhancer_test.prompts import GENERATION_SECTIONS, EDITING_SECTIONS, parse_sections, validate_final


class SectionTests(unittest.TestCase):
    def test_actual_llama_response_regression(self):
        response = (ROOT / 'tests/fixtures/llama-inline-generation.json').read_text(encoding='utf-8')
        data = parse_result(response)
        self.assertTrue(data['prompt'].startswith('Composition: '))
        normalized, counts = validate_final(data['prompt'], 'generation', {'language': 'en', 'maximum': 400})
        self.assertTrue(normalized.startswith('Composition\nWide medium shot'))
        self.assertIn('Two swordsmen stand still, three paces apart', normalized)
        self.assertGreater(counts['english_words'], 100)

    def test_inline_colon_headings_preserve_every_body(self):
        for preset, headings in [('generation', GENERATION_SECTIONS), ('editing', EDITING_SECTIONS)]:
            source = '\n\n'.join(f'{h}: Unique content {i}.' for i, h in enumerate(headings))
            expected = '\n\n'.join(f'{h}\nUnique content {i}.' for i, h in enumerate(headings))
            self.assertEqual(parse_sections(source, preset)[0], expected)

    def test_markdown_numbering_and_colon_variants(self):
        formats = ['**{h}:** {text}', '**{h}**: {text}', '### {h}\n{text}',
                   '{i}. {h}：{text}', '## {i}) **{h}:**\n{text}', '__{h}__: {text}']
        for fmt in formats:
            with self.subTest(fmt=fmt):
                source = '\n\n'.join(fmt.format(h=h, i=i + 1, text='A clear visual scene.')
                                     for i, h in enumerate(GENERATION_SECTIONS))
                self.assertEqual(parse_sections(source, 'generation')[0], body())

    def test_body_lines_starting_with_heading_words_are_not_headings(self):
        text = body(content='Style of the clothing stays simple. Background details remain soft.')
        self.assertEqual(parse_sections(text, 'generation')[0], text)

    def test_missing_repeated_empty_or_reordered_sections_still_fail(self):
        examples = [body().replace('Lighting\nA clear visual scene.\n\n', ''),
                    body() + '\n\nSubject: Duplicate.',
                    body().replace('Lighting\nA clear visual scene.', 'Lighting'),
                    body().replace('Composition', 'Subject', 1),
                    'Introduction\n' + body(),
                    body() + '\n\nNegative Prompt: bad anatomy']
        for text in examples:
            with self.subTest(text=text[:60]), self.assertRaises(ExpansionError):
                parse_sections(text, 'generation')

    def test_inline_format_does_not_bypass_length_cap(self):
        text = '\n'.join(h + ': ' + 'word ' * 100 for h in GENERATION_SECTIONS)
        with self.assertRaisesRegex(ExpansionError, '超过上限'):
            validate_final(text, 'generation', {'language': 'en', 'maximum': 400})

    def test_structured_bodies_are_rendered_in_fixed_order_for_both_presets(self):
        for preset, headings in [('generation', GENERATION_SECTIONS), ('editing', EDITING_SECTIONS)]:
            sections = {h: f'第{i}节正文。' for i, h in reversed(list(enumerate(headings)))}
            data = parse_result(json.dumps({'prompt': sections, 'issues': [], 'conflicts': []}), preset)
            expected = '\n\n'.join(h + f'\n第{i}节正文。' for i, h in enumerate(headings))
            self.assertEqual(validate_final(data['prompt'], preset, {'language': 'zh', 'maximum': 1500})[0], expected)
            self.assertEqual(result_schema(preset)['properties']['prompt']['required'], list(headings))

    def test_invalid_structured_sections_do_not_reach_downstream(self):
        base = {h: '正文。' for h in GENERATION_SECTIONS}
        examples = [{k: v for k, v in base.items() if k != 'Style'},
                    {**base, '风格': '额外内容'}, {**base, 'Style': ''},
                    {**base, 'Style': ['正文']}, {**base, 'Style': 'Negative Prompt: bad anatomy'}]
        for sections in examples:
            with self.subTest(sections=sections), self.assertRaises(ExpansionError):
                data = parse_result(json.dumps({'prompt': sections, 'issues': [], 'conflicts': []}))
                validate_final(data['prompt'], 'generation', {'language': 'zh', 'maximum': 1500})

    def test_structured_bodies_still_obey_hard_limit(self):
        sections = {h: '人' * 259 for h in GENERATION_SECTIONS}
        data = parse_result(json.dumps({'prompt': sections, 'issues': [], 'conflicts': []}))
        with self.assertRaisesRegex(ExpansionError, '1554.*1500'):
            validate_final(data['prompt'], 'generation', {'language': 'zh', 'maximum': 1500})

    def test_legacy_unsectioned_string_is_not_guessed_or_passed_through(self):
        data = parse_result(json.dumps({'prompt': '没有标题的正文。', 'issues': [], 'conflicts': []}))
        with self.assertRaisesRegex(ExpansionError, '已识别：无'):
            validate_final(data['prompt'], 'generation', {'language': 'zh', 'maximum': 1500})


if __name__ == '__main__':
    unittest.main()
