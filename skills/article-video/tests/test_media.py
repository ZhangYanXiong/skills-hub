"""真实FFmpeg生成控制媒体，测试交付器的编码/时长/坏产物边界。

此控制视频不是Remotion视觉验收，不能用它声称动画或音画语义正确。
"""
from pathlib import Path
import shutil
import subprocess
import unittest

import test_delivery
import video_core as core
import video


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe') and shutil.which('node'), '需FFmpeg/ffprobe/Node')
class MediaTests(unittest.TestCase):
    setUp = test_delivery.DeliveryTests.setUp

    def render_fixture(self, dimensions='1080x1920'):
        video.build_project(self.root)
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
                        f'color=c=white:s={dimensions}:r=30', '-f', 'lavfi', '-i',
                        'sine=frequency=880:sample_rate=24000', '-t', '1.4',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-y', str(self.root / 'video.mp4')],
                       check=True, capture_output=True, timeout=90)
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(self.root / 'video.mp4'),
                        '-frames:v', '1', '-vf', 'scale=1080:1920', '-y', str(self.root / 'cover.png')],
                       check=True, capture_output=True, timeout=30)
        (self.root / 'index.html').write_text('<p>测试控制视频，不是实际动画</p>', encoding='utf-8')
        receipt = {'timelineSha256': core.digest(self.root / 'timeline.json'),
                   'rendererSha256': video.renderer_fingerprint(), 'scale': 1,
                   'width': 1080, 'height': 1920, 'fps': 30,
                   'outputs': {name: core.digest(self.root / name) for name in ('video.mp4', 'cover.png', 'index.html')}}
        core.write_json(self.root / 'render-receipt.json', receipt)

    def test_real_media_specs_and_full_decode_pass(self):
        self.render_fixture()
        report = video.verify_delivery(self.root, allow_short=True)
        self.assertTrue(report['full_decode'])
        self.assertEqual(report['duration_seconds'], 1.4)
        self.assertEqual(report['video_codec'], 'h264')
        self.assertEqual(report['audio_codec'], 'aac')

    def test_standard_delivery_rejects_short_video(self):
        self.render_fixture()
        with self.assertRaisesRegex(ValueError, '120–180'):
            video.verify_delivery(self.root)

    def test_actual_dimensions_not_trusted_from_receipt(self):
        self.render_fixture('540x960')
        with self.assertRaisesRegex(ValueError, '分辨率'):
            video.verify_delivery(self.root, allow_short=True)

    def test_changed_mp4_hash_rejected(self):
        self.render_fixture()
        (self.root / 'video.mp4').write_bytes(b'bad-video')
        with self.assertRaisesRegex(ValueError, 'video.mp4'):
            video.verify_delivery(self.root, allow_short=True)

    def test_bad_cover_rejected_even_if_receipt_hash_matches(self):
        self.render_fixture()
        (self.root / 'cover.png').write_bytes(b'not-a-png')
        receipt = core.read_json(self.root / 'render-receipt.json')
        receipt['outputs']['cover.png'] = core.digest(self.root / 'cover.png')
        core.write_json(self.root / 'render-receipt.json', receipt)
        with self.assertRaises(ValueError):
            video.verify_delivery(self.root, allow_short=True)

    def test_scaled_receipt_rejected(self):
        self.render_fixture()
        receipt = core.read_json(self.root / 'render-receipt.json')
        receipt['scale'] = 0.5
        core.write_json(self.root / 'render-receipt.json', receipt)
        with self.assertRaisesRegex(ValueError, '缩小分辨率'):
            video.verify_delivery(self.root, allow_short=True)


if __name__ == '__main__':
    unittest.main()
