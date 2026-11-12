#!/usr/bin/env python3
"""文章转视频 CLI：准备、授权、配音、构建及真实成片验收。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

# -I 阻止加载当前目录模块；只添加受信任的 skill 脚本目录。
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from video_core import (build_timeline, digest, ingest, object_digest, read_json,
                        safe_audio_path, srt, validate_plan, write_json)
from voice import approval_payload, prepare_audio, wav_seconds

RENDERER = SCRIPTS.parent / 'renderer'


def pipeline_fingerprint() -> str:
    return object_digest({p.name: digest(p) for p in sorted(SCRIPTS.glob('*.py'))})


def load_inputs(project: Path) -> tuple[dict, dict]:
    source = read_json(project / 'source.json')
    if ingest(project / 'original.md') != source:
        raise ValueError('source.json 与保存的原文内容不一致，请重新摄入')
    plan = read_json(project / 'plan.json')
    validate_plan(plan, source)
    return source, plan


def derive_timeline(project: Path) -> tuple[dict, dict, dict, dict]:
    source, plan = load_inputs(project)
    voice = read_json(project / 'voice.json')
    if voice.get('plan_sha256') != object_digest(plan) or voice.get('mode') not in {'azure', 'demo-local'}:
        raise ValueError('配音与当前方案不一致；请重新执行 audio，未改句子可复用完整缓存')
    clips = {}
    expected = {(scene['id'], i) for scene in plan['scenes'] for i in range(len(scene['narration']))}
    for clip in voice.get('clips', []):
        ident = (clip.get('scene_id'), clip.get('index'))
        if ident in clips or ident not in expected:
            raise ValueError('配音清单包含重复或不属于当前方案的分句')
        path = safe_audio_path(project, clip['audio'])
        if not path.exists() or digest(path) != clip.get('sha256'):
            raise ValueError('配音文件缺失或摘要不一致，禁止复用损坏声音')
        seconds = wav_seconds(path.read_bytes())
        if clip.get('seconds') != seconds:
            raise ValueError('配音清单声称的时长与 WAV 实际时长不一致')
        clips[ident] = clip
    if clips.keys() != expected:
        raise ValueError('配音清单不完整')
    timeline = build_timeline(plan, clips, voice['mode'])
    return source, plan, voice, timeline


def build_project(project: Path) -> dict:
    project = Path(project).resolve()
    source, plan, voice, timeline = derive_timeline(project)
    write_json(project / 'timeline.json', timeline)
    (project / 'subtitles.srt').write_text(srt(timeline), encoding='utf-8')
    narration = f'# {plan["title"]}\n\n' + '\n\n'.join(
        f'## {scene["title"]}\n\n' + '\n'.join(scene['narration']) for scene in plan['scenes']) + '\n'
    (project / 'narration.md').write_text(narration, encoding='utf-8')
    board = f'# {plan["title"]} · 分镜\n\n' + '\n'.join('- ' + n for n in plan['adaptation_notes']) + '\n\n'
    for scene, timed in zip(plan['scenes'], timeline['scenes']):
        board += (f'## {scene["id"]} · {scene["title"]}\n\n'
                  f'版式：{scene["kind"]}；起点：{timed["from"] / 30:.2f}s；'
                  f'时长：{timed["durationInFrames"] / 30:.2f}s；来源：{", ".join(scene["source_refs"])}\n\n')
        board += '\n'.join('- ' + line for line in scene['body']) + '\n\n'
    (project / 'storyboard.md').write_text(board, encoding='utf-8')
    names = ['original.md', 'source.json', 'plan.json', 'voice.json', 'timeline.json',
             'subtitles.srt', 'narration.md', 'storyboard.md']
    manifest = {'version': 1, 'source_sha256': source['sha256'], 'plan_sha256': object_digest(plan),
                'pipeline_sha256': pipeline_fingerprint(), 'mode': voice['mode'], 'voice': voice['voice'],
                'files': {name: digest(project / name) for name in names},
                'audio': {clip['audio']: clip['sha256'] for clip in voice['clips']},
                'duration_seconds': timeline['durationInFrames'] / 30,
                'limits': ['来源对应不是独立事实核查', '字幕为实测分句边界，不是逐字识别',
                           'demo-local 不是在线配音验收', '尚未自动检查所有平台界面遮挡']}
    write_json(project / 'build.json', manifest)
    return manifest


def renderer_fingerprint() -> str:
    helper = RENDERER / 'render-support.mjs'
    if not helper.exists() or not shutil.which('node'):
        raise ValueError('渲染器未安装或缺少 Node.js')
    script = f'import {{codeFingerprint}} from {json.dumps(helper.as_uri())}; console.log(await codeFingerprint());'
    return subprocess.run(['node', '--input-type=module', '-e', script], check=True,
                          capture_output=True, text=True, timeout=30).stdout.strip()


def probe(path: Path) -> dict:
    return json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
                                     '-of', 'json', str(path)], check=True, capture_output=True,
                                    text=True, timeout=60).stdout)


def verify_delivery(project: Path, allow_short: bool = False) -> dict:
    project = Path(project).resolve()
    source, plan, voice, expected = derive_timeline(project)
    manifest = read_json(project / 'build.json')
    if manifest.get('pipeline_sha256') != pipeline_fingerprint() or manifest.get('plan_sha256') != object_digest(plan):
        raise ValueError('构建程序或方案已经改变，需要重新 build/render')
    mandatory = {'original.md', 'source.json', 'plan.json', 'voice.json', 'timeline.json',
                 'subtitles.srt', 'narration.md', 'storyboard.md'}
    if set(manifest.get('files', {})) != mandatory:
        raise ValueError('构建清单缺少必须交付的源文件或中间产物')
    for name, sha in manifest['files'].items():
        path = project / name
        if not path.is_file() or digest(path) != sha:
            raise ValueError(f'{name} 与现行构建指纹不一致')
    if read_json(project / 'timeline.json') != expected or (project / 'subtitles.srt').read_text(encoding='utf-8') != srt(expected):
        raise ValueError('时间轴或字幕与实际配音不一致')
    expected_audio = {clip['audio']: clip['sha256'] for clip in voice['clips']}
    if manifest.get('audio') != expected_audio:
        raise ValueError('构建清单声音版本不一致')
    receipt_path = project / 'render-receipt.json'
    if not receipt_path.is_file():
        raise ValueError('没有实际渲染回执；不能把制作包当作 MP4 成片')
    receipt = read_json(receipt_path)
    if receipt.get('timelineSha256') != digest(project / 'timeline.json'):
        raise ValueError('渲染回执使用了旧时间轴')
    if receipt.get('rendererSha256') != renderer_fingerprint():
        raise ValueError('渲染代码已改变；需要重新渲染后才能交付')
    if receipt.get('scale') != 1 or (receipt.get('width'), receipt.get('height'), receipt.get('fps')) != (1080, 1920, 30):
        raise ValueError('缩小分辨率的测试视频不属于正式规格')
    if set(receipt.get('outputs', {})) != {'video.mp4', 'cover.png', 'index.html'}:
        raise ValueError('渲染回执缺少必需产物')
    for name, sha in receipt['outputs'].items():
        if not (project / name).is_file() or digest(project / name) != sha:
            raise ValueError(f'{name} 与实际渲染回执不一致')
    try:
        cover_streams = probe(project / 'cover.png')['streams']
        if len(cover_streams) != 1 or (cover_streams[0].get('codec_name'), cover_streams[0].get('width'),
                                      cover_streams[0].get('height')) != ('png', 1080, 1920):
            raise ValueError('封面必须是完整1080×1920 PNG')
        subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-nostdin', '-i', str(project / 'cover.png'),
                        '-frames:v', '1', '-f', 'null', '-'], check=True, capture_output=True, timeout=60)
    except (subprocess.SubprocessError, KeyError) as error:
        raise ValueError('封面不是完整可解码 PNG') from error
    duration = expected['durationInFrames'] / 30
    if not allow_short and not 120 <= duration <= 180:
        raise ValueError(f'成片预计 {duration:.2f}s，不在120–180秒内；调整文案重新配音，不能加速硬塞')
    media = probe(project / 'video.mp4')
    video_streams = [s for s in media['streams'] if s['codec_type'] == 'video']
    audio_streams = [s for s in media['streams'] if s['codec_type'] == 'audio']
    if len(video_streams) != 1 or len(audio_streams) != 1:
        raise ValueError('MP4 需有且仅有一条视频和一条声音流')
    v, a = video_streams[0], audio_streams[0]
    if (v.get('codec_name'), v.get('width'), v.get('height'), v.get('pix_fmt')) != ('h264', 1080, 1920, 'yuv420p'):
        raise ValueError('视频编码、分辨率或像素格式不符合交付规格')
    if Fraction(v['avg_frame_rate']) != 30 or a.get('codec_name') != 'aac':
        raise ValueError('视频必须30fps，声音必须AAC')
    if abs(float(media['format']['duration']) - duration) > 0.15:
        raise ValueError('实际 MP4 时长与时间轴不一致')
    if 'nb_frames' in v and int(v['nb_frames']) != expected['durationInFrames']:
        raise ValueError('实际视频帧数与时间轴不一致')
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-nostdin', '-i', str(project / 'video.mp4'),
                    '-f', 'null', '-'], check=True, capture_output=True, timeout=600)
    volume_log = subprocess.run(['ffmpeg', '-v', 'info', '-nostdin', '-i', str(project / 'video.mp4'),
                                '-vn', '-af', 'volumedetect', '-f', 'null', '-'], check=True,
                               capture_output=True, text=True, timeout=600).stderr
    match = re.search(r'max_volume:\s*(-?[\d.]+) dB', volume_log)
    if not match or float(match.group(1)) < -60:
        raise ValueError('成片没有可检测的有效声音或声音极低')
    report = {'ok': True, 'mode': voice['mode'], 'voice': voice['voice'],
              'duration_seconds': duration, 'width': 1080, 'height': 1920, 'fps': 30,
              'video_codec': v['codec_name'], 'audio_codec': a['codec_name'],
              'max_volume_db': float(match.group(1)), 'full_decode': True,
              'video_sha256': digest(project / 'video.mp4'),
              'checked_at': datetime.now(timezone.utc).isoformat(),
              'limits': manifest['limits'] + ['视觉语义、朗读自然度与音画对应仍需实际播放抽查']}
    write_json(project / 'verification.json', report)
    return report


def doctor() -> dict:
    tools = {name: shutil.which(name) for name in ('node', 'npm', 'ffmpeg', 'ffprobe', 'say')}
    tools['renderer_installed'] = (RENDERER / 'node_modules' / '@remotion' / 'renderer').is_dir()
    tools['azure_key_present'] = bool(os.getenv('AZURE_SPEECH_KEY'))
    tools['azure_region_present'] = bool(os.getenv('AZURE_SPEECH_REGION'))
    tools['python'] = sys.version.split()[0]
    return tools


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='检查工具和配置，不发送网络请求')
    for name in ('ingest', 'validate', 'approve', 'audio', 'build', 'verify'):
        command = sub.add_parser(name)
        command.add_argument('--project', type=Path, required=True, help='独立的视频构建目录')
        if name == 'ingest':
            command.add_argument('article', type=Path)
        elif name == 'approve':
            command.add_argument('--region', default=os.getenv('AZURE_SPEECH_REGION', ''))
            command.add_argument('--voice', default='zh-CN-XiaoxiaoNeural')
            command.add_argument('--unit-price', type=float, required=True, help='用户核实的每百万计费单位价格')
            command.add_argument('--currency', default='USD')
            command.add_argument('--max-cost', type=float, required=True)
            command.add_argument('--confirmed', action='store_true', help='用户已明确批准本批次外发和费用')
        elif name == 'audio':
            command.add_argument('--provider', choices=['azure', 'demo-local'], default='azure')
            command.add_argument('--voice', default=None, help='本地演示音色；在线音色由授权记录决定')
        elif name == 'verify':
            command.add_argument('--allow-short', action='store_true', help='只用于明确要求的非标准时长测试')
    args = parser.parse_args(argv)
    try:
        if args.command == 'doctor':
            result = doctor()
        else:
            project = args.project.resolve()
            if args.command == 'ingest':
                source = ingest(args.article)
                project.mkdir(parents=True, exist_ok=True)
                if args.article.resolve() != project / 'original.md':
                    shutil.copyfile(args.article, project / 'original.md')
                write_json(project / 'source.json', source)
                result = {'paragraphs': len(source['paragraphs']), 'source_sha256': source['sha256'],
                          'next': 'Agent 根据原文编写 plan.json，再执行 validate'}
            elif args.command == 'validate':
                _, plan = load_inputs(project)
                chars = sum(len(text) for scene in plan['scenes'] for text in scene['narration'])
                result = {'ok': True, 'scenes': len(plan['scenes']), 'narration_characters': chars,
                          'notice': '正式时长以实际配音为准；来源编号检查不等于事实核查'}
            elif args.command == 'approve':
                if not args.confirmed:
                    raise ValueError('必须先取得用户对正文外发及费用范围的明确授权，再传 --confirmed')
                _, plan = load_inputs(project)
                settings = {'provider': 'azure', 'region': args.region, 'voice': args.voice,
                            'unit_price': args.unit_price, 'currency': args.currency, 'max_cost': args.max_cost}
                payload = approval_payload(plan, settings)
                write_json(project / 'approval.json', {'confirmed': True, 'payload': payload,
                           'confirmed_at': datetime.now(timezone.utc).isoformat()})
                result = payload
            elif args.command == 'audio':
                _, plan = load_inputs(project)
                if args.provider == 'azure':
                    path = project / 'approval.json'
                    if not path.exists():
                        raise ValueError('缺少当前方案的外发/费用授权 approval.json')
                    record = read_json(path)
                    if record.get('confirmed') is not True:
                        raise ValueError('授权记录未确认')
                    settings = record['payload']['settings']
                    if args.voice and args.voice != settings['voice']:
                        raise ValueError('更改在线音色需要重新批准外发与费用')
                    configured_region = os.getenv('AZURE_SPEECH_REGION')
                    if configured_region and configured_region != settings['region']:
                        raise ValueError('当前地区配置与授权地区不一致，需要重新授权')
                    result = prepare_audio(plan, project, settings, record['payload'], os.getenv('AZURE_SPEECH_KEY', ''))
                else:
                    result = prepare_audio(plan, project, {'provider': 'demo-local', 'voice': args.voice or 'Tingting'})
                result = {'mode': result['mode'], 'voice': result['voice'], 'clips': len(result['clips'])}
            elif args.command == 'build':
                result = build_project(project)
            else:
                result = verify_delivery(project, args.allow_short)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(f'失败：{error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
