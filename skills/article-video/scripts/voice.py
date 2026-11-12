"""显式授权的在线预设音色配音，以及明确标记的本地演示模式。"""
from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import wave
import xml.etree.ElementTree as ET

from video_core import digest, object_digest, read_json, safe_audio_path, write_json

CACHE_VERSION = 1


def ssml(text: str, voice: str) -> bytes:
    if not re.fullmatch(r'zh-CN-[A-Za-z0-9]+Neural', voice):
        raise ValueError('首版仅支持 zh-CN 预设 Neural 音色名称')
    root = ET.Element('speak', {'version': '1.0', 'xmlns': 'http://www.w3.org/2001/10/synthesis',
                              'xml:lang': 'zh-CN'})
    ET.SubElement(root, 'voice', {'name': voice}).text = text
    return ET.tostring(root, encoding='utf-8')


def approval_payload(plan: dict, settings: dict) -> dict:
    if settings.get('provider') != 'azure':
        raise ValueError('付费授权仅支持 azure')
    region = settings.get('region', '')
    if not isinstance(region, str) or not re.fullmatch(r'[a-z][a-z0-9]{1,31}', region):
        raise ValueError('AZURE_SPEECH_REGION 应是公共 Azure 地区标识，例如 eastasia')
    for key in ('unit_price', 'max_cost'):
        value = settings.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f'{key} 必须是有限非负数')
    if settings['max_cost'] <= 0:
        raise ValueError('max_cost 必须大于0')
    if not re.fullmatch(r'[A-Z]{3}', str(settings.get('currency', ''))):
        raise ValueError('currency 必须是三位币种标识')
    payloads = [ssml(text, settings['voice']) for scene in plan['scenes'] for text in scene['narration']]
    # 计入所有 XML 标记作保守估算；不是服务商强制账单上限。
    count = sum(len(payload.decode('utf-8')) for payload in payloads)
    estimate = count / 1_000_000 * settings['unit_price']
    if estimate > settings['max_cost']:
        raise ValueError('预计费用超过用户确认的本批次估算上限')
    return {'version': 1, 'plan_sha256': object_digest(plan), 'settings': settings,
            'billable_characters_estimate': count, 'estimated_cost': estimate,
            'outbound_sha256': object_digest([p.decode('utf-8') for p in payloads]),
            'notice': '此为本批次估算；实际计费以账号价格为准，需在服务商设置账单或额度限制。'}


def wav_seconds(data: bytes) -> float:
    try:
        with wave.open(io.BytesIO(data), 'rb') as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 24000):
                raise ValueError('音频必须是24kHz、16bit、单声道 PCM WAV')
            frames = audio.getnframes()
            if not 0 < frames <= 24000 * 120:
                raise ValueError('分句音频实际长度非法或超过120秒')
            if len(audio.readframes(frames)) != frames * 2:
                raise ValueError('WAV 数据截断')
            return frames / 24000
    except (wave.Error, EOFError) as error:
        raise ValueError('配音返回的不是完整 PCM WAV') from error


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('配音服务发生重定向，已停止以避免向其他主机发送正文或密钥')


def network_transport(request: urllib.request.Request) -> bytes:
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(request, timeout=60) as response:
        return response.read(6 * 1024 * 1024 + 1)


def local_demo(text: str, voice: str) -> bytes:
    if not shutil.which('say') or not shutil.which('ffmpeg'):
        raise ValueError('demo-local 需要 macOS say 和 FFmpeg；不能替代正常在线配音')
    with tempfile.TemporaryDirectory(prefix='article-video-voice-') as directory:
        root = Path(directory)
        (root / 'text.txt').write_text(text, encoding='utf-8')
        subprocess.run(['say', '-v', voice, '-r', '220', '-o', str(root / 'clip.aiff'),
                        '-f', str(root / 'text.txt')], check=True, capture_output=True, timeout=120)
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(root / 'clip.aiff'),
                        '-ar', '24000', '-ac', '1', '-c:a', 'pcm_s16le', str(root / 'clip.wav')],
                       check=True, capture_output=True, timeout=120)
        return (root / 'clip.wav').read_bytes()


def prepare_audio(plan: dict, project: Path, settings: dict, approval: dict | None = None,
                  key: str = '', transport=None) -> dict:
    provider = settings.get('provider')
    if provider == 'azure':
        expected = approval_payload(plan, settings)
        if approval != expected:
            raise ValueError('没有当前方案、音色、地区和费用范围的明确授权；不能发送配音请求')
        if not key:
            raise ValueError('缺少 AZURE_SPEECH_KEY；停止在线制作，不静默降级')
    elif provider == 'demo-local':
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9 ]{0,63}', settings.get('voice', '')):
            raise ValueError('本地演示音色名称非法')
    else:
        raise ValueError('provider 只支持 azure 或显式 demo-local')
    project = Path(project).resolve()
    (project / 'audio').mkdir(parents=True, exist_ok=True)
    transport = transport or network_transport
    clips = []
    for scene in plan['scenes']:
        for index, text in enumerate(scene['narration']):
            request_settings = {k: settings[k] for k in ('provider', 'voice')}
            if provider == 'azure':
                request_settings['region'] = settings['region']
                payload = ssml(text, settings['voice'])
            else:
                request_settings['rate'] = 220
                payload = text.encode('utf-8')
            cache_key = object_digest({'version': CACHE_VERSION, 'request': request_settings,
                                       'payload': hashlib.sha256(payload).hexdigest()})
            relative = f'audio/{cache_key}.wav'
            path = safe_audio_path(project, relative)
            meta = path.with_suffix('.json')
            if meta.exists() or path.exists():
                if not meta.exists() or not path.exists():
                    raise ValueError(f'{cache_key}: 上次请求未完成或缓存不完整；先检查服务商账单，不自动重发')
                info = read_json(meta)
                if info.get('state') != 'complete' or info.get('cache_key') != cache_key or info.get('sha256') != digest(path):
                    raise ValueError(f'{cache_key}: 缓存损坏，不能静默重做并再次计费')
                seconds = wav_seconds(path.read_bytes())
            else:
                # 请求前持久化状态，超时或进程退出后不自动重复计费。
                write_json(meta, {'cache_key': cache_key, 'state': 'requested', 'provider': provider})
                try:
                    if provider == 'azure':
                        request = urllib.request.Request(
                            f'https://{settings["region"]}.tts.speech.microsoft.com/cognitiveservices/v1',
                            data=payload, headers={'Ocp-Apim-Subscription-Key': key,
                            'Content-Type': 'application/ssml+xml',
                            'X-Microsoft-OutputFormat': 'riff-24khz-16bit-mono-pcm',
                            'User-Agent': 'article-video-skill/1'})
                        data = transport(request)
                    else:
                        data = local_demo(text, settings['voice'])
                    seconds = wav_seconds(data)
                except urllib.error.HTTPError as error:
                    raise ValueError(f'Azure 配音 HTTP {error.code}；没有自动重试，请检查凭据/额度/账单') from None
                except (urllib.error.URLError, TimeoutError) as error:
                    raise ValueError('配音网络请求失败；未自动重试，需核对账单后决定是否重发') from error
                path.write_bytes(data)
                info = {'cache_key': cache_key, 'state': 'complete', 'sha256': digest(path), 'seconds': seconds}
                write_json(meta, info)
            clips.append({'scene_id': scene['id'], 'index': index, 'audio': relative,
                          'seconds': seconds, 'sha256': digest(path)})
    receipt = {'version': 1, 'plan_sha256': object_digest(plan), 'mode': provider,
               'voice': settings['voice'], 'settings': settings, 'clips': clips}
    write_json(project / 'voice.json', receipt)
    return receipt
