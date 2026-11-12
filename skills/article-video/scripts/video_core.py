"""文章摄入、分镜契约、实际音频驱动的帧时间轴。"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import unicodedata

FPS = 30
KINDS = {'hook', 'points', 'steps', 'compare', 'summary'}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def object_digest(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def read_json(path: Path) -> dict:
    with Path(path).open(encoding='utf-8-sig') as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError(f'{path.name} 应是 JSON 对象')
    return data


def write_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    tmp.replace(path)


def ingest(path: Path) -> dict:
    path = Path(path)
    if path.suffix.lower() not in {'.md', '.txt', '.markdown'}:
        raise ValueError('首版只接受 Markdown/纯文本文件；其他格式先提取完整正文')
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('文章超过2 MiB，请先精简正文')
    text = path.read_text(encoding='utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')
    if lines and lines[0].strip() == '---':
        closing = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
        if closing is None:
            raise ValueError('Markdown frontmatter 未闭合')
        text = '\n'.join(lines[closing + 1:])
    text = text.strip()
    if not text or not any(c.isalnum() for c in text):
        raise ValueError('没有可改编的文章正文')
    if '\x00' in text:
        raise ValueError('正文包含空字节，可能不是文本文件')
    paragraphs = [{'id': f'p{i:03d}', 'text': p.strip()}
                  for i, p in enumerate(re.split(r'\n\s*\n', text), 1) if p.strip()]
    return {'version': 1, 'sha256': digest(path), 'text': text, 'paragraphs': paragraphs}


def require_text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{name} 需为1–{limit}字的非空文本')
    if any(unicodedata.category(c).startswith('C') or unicodedata.category(c) in {'Zl', 'Zp'} for c in value):
        raise ValueError(f'{name} 不能包含换行或控制字符')
    return value


def validate_plan(plan: dict, source: dict) -> None:
    if type(plan.get('version')) is not int or type(source.get('version')) is not int or plan.get('version') != 1 or source.get('version') != 1:
        raise ValueError('只支持 version=1')
    if not re.fullmatch(r'[a-f0-9]{64}', str(source.get('sha256', ''))):
        raise ValueError('来源缺少合法 SHA-256')
    if plan.get('source_sha256') != source['sha256']:
        raise ValueError('方案与当前原文摘要不一致，请重新摄入并确认改编')
    require_text(plan.get('title'), '视频标题', 32)
    notes = plan.get('adaptation_notes')
    if not isinstance(notes, list) or not notes:
        raise ValueError('必须记录 adaptation_notes 内容取舍')
    for note in notes:
        require_text(note, '改编说明', 500)
    scenes = plan.get('scenes')
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 24:
        raise ValueError('scenes 必须包含1–24个场景；默认建议8–14个')
    paragraphs = source.get('paragraphs')
    if not isinstance(paragraphs, list) or not paragraphs:
        raise ValueError('来源没有有效段落')
    refs = {p['id'] for p in paragraphs if isinstance(p, dict) and isinstance(p.get('id'), str)}
    ids = set()
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError('场景需为对象')
        sid = scene.get('id')
        if not isinstance(sid, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', sid) or sid in ids:
            raise ValueError('场景 ID 必须唯一，仅使用小写字母、数字和短横线')
        ids.add(sid)
        if not isinstance(scene.get('kind'), str) or scene['kind'] not in KINDS:
            raise ValueError(f'{sid}: 不支持的画面类型')
        require_text(scene.get('title'), f'{sid} 标题', 24)
        body = scene.get('body')
        if not isinstance(body, list) or not 1 <= len(body) <= 3:
            raise ValueError(f'{sid}: body 需包含1–3条')
        for item in body:
            require_text(item, f'{sid} 画面正文', 46)
        if scene['kind'] == 'compare' and len(body) != 2:
            raise ValueError('compare 必须恰好两条对比内容')
        if scene['kind'] == 'steps' and len(body) < 2:
            raise ValueError('steps 至少两步')
        narration = scene.get('narration')
        if not isinstance(narration, list) or not 1 <= len(narration) <= 30:
            raise ValueError(f'{sid}: narration 需包含1–30句')
        for text in narration:
            require_text(text, f'{sid} 旁白分句', 42)
            if not any(c.isalnum() for c in text):
                raise ValueError('旁白不能只有标点')
        scene_refs = scene.get('source_refs')
        if not isinstance(scene_refs, list) or not scene_refs or any(not isinstance(r, str) or r not in refs for r in scene_refs):
            raise ValueError(f'{sid}: source_refs 必须对应实际原文段落')


def safe_audio_path(project: Path, relative: str) -> Path:
    if not isinstance(relative, str) or '\\' in relative:
        raise ValueError('音频路径非法')
    parts = PurePosixPath(relative)
    if (parts.is_absolute() or len(parts.parts) != 2 or parts.parts[0] != 'audio'
            or '..' in parts.parts or not re.fullmatch(r'[a-zA-Z0-9_-]+\.wav', parts.name)):
        raise ValueError('音频必须是构建目录内 audio/ 下的 WAV，不接受 URL 或目录逃逸')
    root = Path(project).resolve()
    result = (root / relative).resolve()
    if not result.is_relative_to(root):
        raise ValueError('音频符号链接逃逸构建目录')
    return result


def build_timeline(plan: dict, clips: dict, mode: str) -> dict:
    cursor = 0
    scenes = []
    for scene in plan['scenes']:
        local = 0
        captions = []
        for i, text in enumerate(scene['narration']):
            clip = clips[(scene['id'], i)]
            seconds = clip['seconds']
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
                raise ValueError('配音实际时长必须是有限正数')
            safe_audio_path(Path('/tmp/article-video-contract'), clip['audio'])
            duration = math.ceil(seconds * FPS)
            captions.append({'text': text, 'from': local, 'durationInFrames': duration,
                             'audio': clip['audio'], 'audioSha256': clip['sha256']})
            local += duration + (4 if i < len(scene['narration']) - 1 else 0)
        duration = local + 12
        scenes.append({key: scene[key] for key in ('id', 'kind', 'title', 'body')} |
                      {'from': cursor, 'durationInFrames': duration, 'captions': captions})
        cursor += duration
    return {'version': 1, 'title': plan['title'], 'width': 1080, 'height': 1920, 'fps': FPS,
            'durationInFrames': cursor, 'plan_sha256': object_digest(plan), 'mode': mode, 'scenes': scenes}


def srt(timeline: dict) -> str:
    def timestamp(frame: int) -> str:
        total_ms = round(frame * 1000 / timeline['fps'])
        seconds, ms = divmod(total_ms, 1000)
        minutes, sec = divmod(seconds, 60)
        hours, minute = divmod(minutes, 60)
        return f'{hours:02d}:{minute:02d}:{sec:02d},{ms:03d}'
    blocks = []
    for scene in timeline['scenes']:
        for caption in scene['captions']:
            start = scene['from'] + caption['from']
            end = start + caption['durationInFrames']
            blocks.append(f'{len(blocks) + 1}\n{timestamp(start)} --> {timestamp(end)}\n{caption["text"]}\n')
    return '\n'.join(blocks)
