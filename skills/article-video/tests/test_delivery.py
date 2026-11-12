"""交付闸门须能拒绝旧方案、旧声音、篡改时间轴和损坏媒体。"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_core import SCRIPTS, fixture
from test_voice import wav_data
import video_core as core
import voice
if (SCRIPTS / 'video.py').exists():
    import video
else:
    video = None


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(video, '制作与交付闸门尚未实现')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'original.md').write_text('原文第一段。', encoding='utf-8')
        self.source = core.ingest(self.root / 'original.md')
        _, self.plan = fixture(); self.plan['source_sha256'] = self.source['sha256']
        core.write_json(self.root / 'source.json', self.source)
        core.write_json(self.root / 'plan.json', self.plan)
        settings = {'provider': 'azure', 'voice': 'zh-CN-XiaoxiaoNeural', 'region': 'eastasia',
                    'unit_price': 15.0, 'currency': 'USD', 'max_cost': 0.1}
        self.voice = voice.prepare_audio(self.plan, self.root, settings, voice.approval_payload(self.plan, settings),
                                         key='test-only-key', transport=lambda request: wav_data())

    def test_build_writes_actual_timeline_srt_and_traceable_package(self):
        manifest = video.build_project(self.root)
        timeline = core.read_json(self.root / 'timeline.json')
        self.assertEqual(timeline['durationInFrames'], 42)
        self.assertIn('00:00:00,000 --> 00:00:01,000', (self.root / 'subtitles.srt').read_text())
        self.assertEqual(manifest['files']['timeline.json'], core.digest(self.root / 'timeline.json'))
        self.assertTrue((self.root / 'narration.md').exists())
        self.assertTrue((self.root / 'storyboard.md').exists())

    def test_changed_plan_cannot_reuse_old_voice_receipt(self):
        self.plan['scenes'][0]['narration'] = ['换一句新的旁白。']
        core.write_json(self.root / 'plan.json', self.plan)
        with self.assertRaises(ValueError):
            video.build_project(self.root)

    def test_tampered_source_paragraphs_rejected(self):
        self.source['paragraphs'][0]['text'] = '篡改原文。'
        core.write_json(self.root / 'source.json', self.source)
        with self.assertRaises(ValueError):
            video.build_project(self.root)

    def test_modified_audio_rejected_before_timeline_build(self):
        (self.root / self.voice['clips'][0]['audio']).write_bytes(wav_data(2))
        with self.assertRaises(ValueError):
            video.build_project(self.root)

    def test_modified_voice_caption_index_rejected(self):
        self.voice['clips'][0]['index'] = 2
        core.write_json(self.root / 'voice.json', self.voice)
        with self.assertRaises(ValueError):
            video.build_project(self.root)

    def test_modified_subtitles_rejected_before_render_checks(self):
        video.build_project(self.root)
        (self.root / 'subtitles.srt').write_text('不是现行字幕', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'subtitles.srt'):
            video.verify_delivery(self.root, allow_short=True)

    def test_old_render_timeline_rejected(self):
        video.build_project(self.root)
        core.write_json(self.root / 'render-receipt.json', {'timelineSha256': '0' * 64})
        with self.assertRaisesRegex(ValueError, '旧时间轴'):
            video.verify_delivery(self.root, allow_short=True)

    def test_build_manifest_missing_required_files_rejected(self):
        manifest = video.build_project(self.root)
        del manifest['files']['narration.md']
        core.write_json(self.root / 'build.json', manifest)
        with self.assertRaisesRegex(ValueError, '清单缺少'):
            video.verify_delivery(self.root, allow_short=True)

    def test_missing_render_never_claims_delivery_success(self):
        video.build_project(self.root)
        with self.assertRaises(ValueError):
            video.verify_delivery(self.root, allow_short=True)

    def test_cli_ingest_and_validate_real_files(self):
        project = self.root / 'cli-project'
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPTS / 'video.py'), 'ingest',
                                 str(self.root / 'original.md'), '--project', str(project)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        core.write_json(project / 'plan.json', self.plan)
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPTS / 'video.py'), 'validate',
                                 '--project', str(project)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.plan['scenes'][0]['kind'] = 'unknown'
        core.write_json(project / 'plan.json', self.plan)
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPTS / 'video.py'), 'validate',
                                 '--project', str(project)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Traceback', result.stderr)

    def test_approve_requires_explicit_confirmation(self):
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPTS / 'video.py'), 'approve',
                                 '--project', str(self.root), '--region', 'eastasia', '--unit-price', '15',
                                 '--max-cost', '.1'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'approval.json').exists())

    def test_online_audio_missing_approval_stops_before_network(self):
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPTS / 'video.py'), 'audio',
                                 '--project', str(self.root), '--provider', 'azure'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('授权', result.stderr)


if __name__ == '__main__':
    unittest.main()
