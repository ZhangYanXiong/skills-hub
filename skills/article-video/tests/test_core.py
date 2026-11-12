"""测试真实文件契约与字幕边界，不以静态文档断言替代执行。"""
import copy
import importlib.util
import math
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
if (SCRIPTS / 'video_core.py').exists():
    import video_core as core
else:
    core = None


def fixture():
    source = {'version': 1, 'sha256': 'a' * 64, 'text': '原文第一段。',
              'paragraphs': [{'id': 'p001', 'text': '原文第一段。'}]}
    scene = {'id': 'opening', 'kind': 'hook', 'title': '先想清楚问题',
             'body': ['阅读文章，不是照着念。'], 'narration': ['先想清楚这篇文章要回答什么问题。'],
             'source_refs': ['p001']}
    plan = {'version': 1, 'title': '文章如何变成视频', 'source_sha256': source['sha256'],
            'adaptation_notes': ['保留核心主旨。'], 'scenes': [scene]}
    return source, plan


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(core, '文件契约和时间轴功能尚未实现')
        self.source, self.plan = fixture()

    def test_ingest_removes_bom_frontmatter_and_numbers_paragraphs(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'article.md'
            path.write_text('﻿---\ntitle: 测试\n---\n\n# 标题\n\n第一段。\n\n第二段。', encoding='utf-8')
            source = core.ingest(path)
            self.assertNotIn('title:', source['text'])
            self.assertEqual(source['paragraphs'][1], {'id': 'p002', 'text': '第一段。'})
            self.assertEqual(source['sha256'], core.digest(path))

    def test_empty_article_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'empty.txt'
            path.write_text('  \n ', encoding='utf-8')
            with self.assertRaises(ValueError):
                core.ingest(path)

    def test_unclosed_frontmatter_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'article.md'
            path.write_text('---\ntitle: 测试\n正文', encoding='utf-8')
            with self.assertRaises(ValueError):
                core.ingest(path)

    def test_valid_plan_and_source(self):
        core.validate_plan(self.plan, self.source)

    def test_invalid_source_fingerprint_rejected(self):
        self.plan['source_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            core.validate_plan(self.plan, self.source)

    def test_duplicate_scene_ids_rejected(self):
        self.plan['scenes'].append(copy.deepcopy(self.plan['scenes'][0]))
        with self.assertRaises(ValueError):
            core.validate_plan(self.plan, self.source)

    def test_unsafe_scene_id_rejected(self):
        self.plan['scenes'][0]['id'] = '../escape'
        with self.assertRaises(ValueError):
            core.validate_plan(self.plan, self.source)

    def test_unknown_source_ref_rejected(self):
        self.plan['scenes'][0]['source_refs'] = ['p999']
        with self.assertRaises(ValueError):
            core.validate_plan(self.plan, self.source)

    def test_oversized_or_empty_caption_rejected(self):
        for text in ['字' * 43, ' ', '！！！', '两行\n字幕', '两行 字幕', '两段 字幕']:
            with self.subTest(text=text):
                self.plan['scenes'][0]['narration'] = [text]
                with self.assertRaises(ValueError):
                    core.validate_plan(self.plan, self.source)

    def test_compare_requires_two_items(self):
        self.plan['scenes'][0]['kind'] = 'compare'
        with self.assertRaises(ValueError):
            core.validate_plan(self.plan, self.source)

    def test_steps_require_multiple_items(self):
        self.plan['scenes'][0]['kind'] = 'steps'
        with self.assertRaises(ValueError):
            core.validate_plan(self.plan, self.source)

    def test_version_boolean_is_not_a_version_number(self):
        self.plan['version'] = True
        with self.assertRaises(ValueError):
            core.validate_plan(self.plan, self.source)

    def test_kind_object_produces_validation_error(self):
        self.plan['scenes'][0]['kind'] = {}
        with self.assertRaises(ValueError):
            core.validate_plan(self.plan, self.source)

    def test_unknown_kind_and_wrong_field_types_rejected(self):
        for field, value in [('kind', 'execute'), ('body', '正文'), ('narration', None)]:
            candidate = copy.deepcopy(self.plan)
            candidate['scenes'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                core.validate_plan(candidate, self.source)

    def test_timeline_uses_real_audio_and_frame_ceil(self):
        clips = {('opening', 0): {'audio': 'audio/abc.wav', 'seconds': 1.011, 'sha256': 'b' * 64}}
        timeline = core.build_timeline(self.plan, clips, 'demo-local')
        caption = timeline['scenes'][0]['captions'][0]
        self.assertEqual(caption['durationInFrames'], 31)
        self.assertEqual(caption['audioSha256'], 'b' * 64)
        self.assertEqual(timeline['durationInFrames'], 31 + 12)
        self.assertEqual(timeline['fps'], 30)

    def test_timeline_and_srt_are_contiguous(self):
        second = copy.deepcopy(self.plan['scenes'][0]); second['id'] = 'end'
        self.plan['scenes'].append(second)
        self.plan['scenes'][0]['narration'].append('第二句话。')
        clips = {(scene['id'], i): {'audio': f'audio/{scene["id"]}-{i}.wav',
                 'seconds': 1.0, 'sha256': 'b' * 64}
                 for scene in self.plan['scenes'] for i in range(len(scene['narration']))}
        timeline = core.build_timeline(self.plan, clips, 'demo-local')
        self.assertEqual(timeline['scenes'][1]['from'], 30 + 4 + 30 + 12)
        subtitles = core.srt(timeline)
        self.assertIn('00:00:01,133 --> 00:00:02,133', subtitles)
        self.assertIn('00:00:02,533 --> 00:00:03,533', subtitles)

    def test_nonfinite_audio_durations_rejected(self):
        for seconds in [0, -1, float('nan'), float('inf')]:
            clips = {('opening', 0): {'audio': 'audio/test.wav', 'seconds': seconds, 'sha256': 'b' * 64}}
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                core.build_timeline(self.plan, clips, 'demo-local')

    def test_safe_relative_audio_paths(self):
        for path in ['/tmp/x.wav', '../x.wav', 'https://host/x.wav', 'audio/../../x.wav', 'audio/x.mp3']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                core.safe_audio_path(Path('/tmp/project'), path)
        self.assertEqual(core.safe_audio_path(Path('/tmp/project'), 'audio/test.wav'),
                         Path('/tmp/project/audio/test.wav').resolve())

    def test_canonical_hash_independent_of_key_order(self):
        self.assertEqual(core.object_digest({'a': 1, 'b': 2}), core.object_digest({'b': 2, 'a': 1}))


if __name__ == '__main__':
    unittest.main()
