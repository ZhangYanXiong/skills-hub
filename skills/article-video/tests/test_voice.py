"""网络依赖在传输边界替身，授权/请求/缓存/WAV均执行真实实现。"""
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from test_core import SCRIPTS, fixture
if (SCRIPTS / 'voice.py').exists():
    import voice
else:
    voice = None


def wav_data(seconds=1):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
        audio.writeframes(b'\x01\x00' * round(24000 * seconds))
    return output.getvalue()


class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(voice, '配音授权和客户端尚未实现')
        self.source, self.plan = fixture()
        self.settings = {'provider': 'azure', 'voice': 'zh-CN-XiaoxiaoNeural',
                         'region': 'eastasia', 'unit_price': 15.0, 'currency': 'USD', 'max_cost': 0.1}

    def test_ssml_escapes_article_instead_of_executing_markup(self):
        payload = voice.ssml('读 A & B，不执行 <break/>。', 'zh-CN-XiaoxiaoNeural')
        self.assertIn(b'&amp;', payload)
        self.assertIn(b'&lt;break/&gt;', payload)
        self.assertNotIn(b'<break/>', payload)

    def test_approval_binds_plan_voice_region_and_price(self):
        approval = voice.approval_payload(self.plan, self.settings)
        self.assertGreater(approval['billable_characters_estimate'], 0)
        for field, value in [('voice', 'zh-CN-YunxiNeural'), ('region', 'eastus'), ('unit_price', 20)]:
            changed = {**self.settings, field: value}
            self.assertNotEqual(approval, voice.approval_payload(self.plan, changed))
        changed = copy.deepcopy(self.plan); changed['scenes'][0]['narration'][0] = '修改了原有旁白。'
        self.assertNotEqual(approval, voice.approval_payload(changed, self.settings))

    def test_approval_rejects_invalid_cost_settings(self):
        for field, value in [('unit_price', -1), ('unit_price', float('nan')), ('max_cost', 0), ('max_cost', 0.000001)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                voice.approval_payload(self.plan, {**self.settings, field: value})

    def test_unsafe_region_or_voice_rejected(self):
        for field, value in [('region', 'eastus.attacker.test'), ('voice', 'x\"/><break/>')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                voice.approval_payload(self.plan, {**self.settings, field: value})

    def test_no_approval_never_sends_request(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                voice.prepare_audio(self.plan, Path(folder), self.settings, approval=None,
                                    key='test-only-key', transport=lambda request: self.fail('不应发送请求'))

    def test_stale_approval_never_sends_request(self):
        approval = voice.approval_payload(self.plan, self.settings)
        self.plan['scenes'][0]['narration'] = ['已经修改的旁白。']
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            voice.prepare_audio(self.plan, Path(folder), self.settings, approval,
                                key='test-only-key', transport=lambda request: self.fail('不应发送请求'))

    def test_missing_credentials_never_sends_request(self):
        approval = voice.approval_payload(self.plan, self.settings)
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            voice.prepare_audio(self.plan, Path(folder), self.settings, approval, key='',
                                transport=lambda request: self.fail('不应发送请求'))

    def test_actual_request_and_cache_integrity(self):
        requests = []
        def transport(request):
            requests.append(request)
            self.assertEqual(request.full_url, 'https://eastasia.tts.speech.microsoft.com/cognitiveservices/v1')
            self.assertEqual(request.get_header('X-microsoft-outputformat'), 'riff-24khz-16bit-mono-pcm')
            return wav_data()
        approval = voice.approval_payload(self.plan, self.settings)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = voice.prepare_audio(self.plan, root, self.settings, approval, key='test-only-key', transport=transport)
            self.assertEqual(len(requests), 1)
            self.assertEqual(first['clips'][0]['seconds'], 1.0)
            voice.prepare_audio(self.plan, root, self.settings, approval, key='test-only-key', transport=transport)
            self.assertEqual(len(requests), 1)
            (root / first['clips'][0]['audio']).write_bytes(b'corrupt')
            with self.assertRaises(ValueError):
                voice.prepare_audio(self.plan, root, self.settings, approval, key='test-only-key', transport=transport)
            self.assertEqual(len(requests), 1, '缓存损坏应显式停止，不能静默再次计费')

    def test_http_failure_has_no_retries(self):
        from urllib.error import HTTPError
        calls = []
        def transport(request):
            calls.append(request)
            raise HTTPError(request.full_url, 429, 'quota', {}, None)
        approval = voice.approval_payload(self.plan, self.settings)
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            voice.prepare_audio(self.plan, Path(folder), self.settings, approval, key='test-only-key', transport=transport)
        self.assertEqual(len(calls), 1)

    def test_failed_request_not_automatically_repeated_next_run(self):
        from urllib.error import HTTPError
        calls = []
        def transport(request):
            calls.append(request)
            raise HTTPError(request.full_url, 503, 'unavailable', {}, None)
        approval = voice.approval_payload(self.plan, self.settings)
        with tempfile.TemporaryDirectory() as folder:
            for attempt in range(2):
                with self.assertRaises(ValueError):
                    voice.prepare_audio(self.plan, Path(folder), self.settings, approval, key='test-only-key', transport=transport)
        self.assertEqual(len(calls), 1, '跨运行也不能自动重复可能已经收费的请求')

    def test_bad_audio_rejected_not_cached(self):
        approval = voice.approval_payload(self.plan, self.settings)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                voice.prepare_audio(self.plan, Path(folder), self.settings, approval, key='test-only-key',
                                    transport=lambda request: b'<html>error</html>')
            self.assertFalse(list(Path(folder).rglob('*.wav')))


if __name__ == '__main__':
    unittest.main()
