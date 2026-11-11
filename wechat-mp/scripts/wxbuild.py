"""标准库构建清单、产物校验及完整交付快照。"""
import hashlib
import json
import os
import re
import shutil
import struct
import tempfile
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

import wxmeta

SCHEMA = 2
COVERS = ('cover.png', 'cover-square.png', 'cover-thumb.png')

# 本项目的三档封面交付规格；不代替微信后台当前规则。
COVER_SPECS = (
    ('cover.png', 900, 383, '头条封面 2.35:1'),
    ('cover-square.png', 1080, 1080, '方形分享卡 1:1'),
    ('cover-thumb.png', 200, 200, '次条封面 1:1'),
)
SOURCE_COPY = '.snapshot-source.md'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    with open(path, 'rb') as fh:
        return digest(fh.read())


def safe_path(root, name):
    """只允许根目录内的相对文件，拒绝目录逃逸与外向符号链接。"""
    if not isinstance(name, str) or not name or '\\' in name or os.path.isabs(name):
        raise ValueError('不是安全的相对文件路径: %r' % name)
    if '..' in name.split('/') or name in ('.', 'build.json', SOURCE_COPY) or name.split('/')[0] == '.builds':
        raise ValueError('禁止的产物路径: %s' % name)
    base = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root, name))
    if os.path.commonpath([base, target]) != base or target == base:
        raise ValueError('文件路径超出输出目录: %s' % name)
    return os.path.join(os.path.abspath(root), name)


class ImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            self.sources.extend(v for k, v in attrs if k == 'src' and v)


def collect_assets(fragment, out_dir, sheet=True):
    parser = ImageParser()
    parser.feed(fragment)
    names = []
    for src in parser.sources:
        parsed = urlsplit(src)
        if parsed.scheme in ('http', 'https', 'data') or parsed.netloc:
            continue
        if parsed.scheme:
            raise ValueError('本地图片请使用输出目录内的相对路径: %s' % src)
        name = unquote(parsed.path)
        safe_path(out_dir, name)
        names.append(name)
    if sheet:
        names.extend(n for n in COVERS if os.path.isfile(os.path.join(out_dir, n)))
    return {n: file_digest(safe_path(out_dir, n)) if os.path.isfile(safe_path(out_dir, n)) else None
            for n in sorted(set(names))}


def context(raw, theme, render, out_dir, fragment=None):
    if fragment is None:
        import md2wx
        _, body = wxmeta.parse_frontmatter(raw)
        fragment, _ = md2wx.parse(body, md2wx.Renderer(theme))
        fragment = md2wx.tag('section', theme.get('styles', {}).get('body', {}), fragment)
    assets = collect_assets(fragment, out_dir, render.get('sheet', False))
    return wxmeta.fingerprint(raw, theme, options=render, asset_hashes=assets), assets


def same_file(a, b):
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def preflight(out_dir, outputs, assets, source, snapshot=False, fp=None):
    targets = [safe_path(out_dir, name) for name in outputs.values()]
    targets.append(os.path.join(os.path.abspath(out_dir), 'build.json'))
    protected = [safe_path(out_dir, name) for name in assets]
    if source != 'stdin':
        protected.append(source)
    for i, path in enumerate(targets):
        if os.path.islink(path):
            raise ValueError('输出文件不能是符号链接: %s' % path)
        if any(same_file(path, other) for other in targets[i + 1:] + protected):
            raise ValueError('输出与源稿/资产/其他输出指向同一文件: %s' % path)
    for path in targets + [os.path.join(out_dir, 'build.json')]:
        if os.path.islink(path) or (os.path.exists(path) and not os.path.isfile(path)):
            raise ValueError('输出目标不是安全的普通文件: %s' % path)
        parent = os.path.dirname(os.path.abspath(path))
        while not os.path.exists(parent):
            parent = os.path.dirname(parent)
        if not os.path.isdir(parent):
            raise ValueError('输出父路径不是目录: %s' % path)
    if snapshot:
        if any(sha is None for sha in assets.values()):
            raise ValueError('本地图片缺失，不能保存完整快照')
        root = os.path.join(out_dir, '.builds')
        if os.path.islink(root) or (os.path.exists(root) and not os.path.isdir(root)):
            raise ValueError('快照目录不是安全目录')
        if fp and os.path.exists(os.path.join(root, fp)):
            _snapshot_payload(os.path.join(root, fp), fp)


def make_manifest(raw, theme, render, out_dir, outputs, built_at, words, fragment, contents=None):
    fp, assets = context(raw, theme, render, out_dir, fragment)
    for name in outputs.values():
        safe_path(out_dir, name)
    return {
        'schema': SCHEMA, 'fingerprint': fp, 'generator': wxmeta.GENERATOR_VERSION,
        'generated_at': built_at, 'source': render['source'], 'theme': render['theme'],
        'word_count': words, 'render': render, 'outputs': outputs,
        'artifact_sha256': {role: (digest(contents[name]) if contents is not None else file_digest(safe_path(out_dir, name))) for role, name in outputs.items()},
        'inputs': {'text_sha256': digest(raw.encode('utf-8')),
                   'theme_sha256': digest(json.dumps(theme, ensure_ascii=False, sort_keys=True).encode('utf-8')),
                   'images': list(assets)},
        'assets': assets,
    }


def load_manifest(path):
    if os.path.islink(path):
        raise ValueError('构建清单不能是符号链接')
    try:
        with open(path, encoding='utf-8') as fh:
            info = json.load(fh)
    except (ValueError, OSError) as exc:
        raise ValueError('无法读取构建清单: %s' % exc)
    if not isinstance(info, dict):
        raise ValueError('构建清单必须是 JSON 对象')
    for key in ('outputs', 'inputs', 'artifact_sha256', 'render', 'assets'):
        if key in info and not isinstance(info[key], dict):
            raise ValueError('构建清单 %s 必须是对象' % key)
    return info


def validate_manifest(info, root):
    if info.get('schema') != SCHEMA:
        raise ValueError('旧构建清单无法完整验证，请重新渲染')
    if not re.fullmatch(r'[0-9a-f]{12,40}', str(info.get('fingerprint', ''))):
        raise ValueError('构建清单缺少有效指纹')
    outs = info.get('outputs')
    if not isinstance(outs, dict) or 'html' not in outs or set(outs) - {'html', 'body', 'sheet'}:
        raise ValueError('构建清单 outputs 缺少 HTML 或包含未知产物')
    if len(set(outs.values())) != len(outs):
        raise ValueError('产物路径相互覆盖')
    for name in outs.values():
        safe_path(root, name)
    render = info.get('render')
    if not isinstance(render, dict) or not isinstance(render.get('theme'), str) or not isinstance(render.get('title'), str):
        raise ValueError('缺少实际渲染参数')
    if not isinstance(render.get('source'), str) or not render['source']:
        raise ValueError('缺少源稿路径')
    if info.get('source') != render['source']:
        raise ValueError('源稿路径记录不一致')
    if render.get('html') != outs['html'] or bool(render.get('body')) != ('body' in outs) or bool(render.get('sheet')) != ('sheet' in outs):
        raise ValueError('渲染参数与声明产物不一致')
    for key in ('inputs', 'artifact_sha256', 'assets'):
        if not isinstance(info.get(key), dict):
            raise ValueError('构建清单缺少 %s' % key)
    for role in outs:
        if not re.fullmatch(r'[0-9a-f]{64}', str(info['artifact_sha256'].get(role, ''))):
            raise ValueError('产物 %s 缺少完整摘要' % role)
    for key in ('text_sha256', 'theme_sha256'):
        if not re.fullmatch(r'[0-9a-f]{64}', str(info['inputs'].get(key, ''))):
            raise ValueError('输入 %s 缺少完整摘要' % key)
    for name, sha in info['assets'].items():
        safe_path(root, name)
        if sha is not None and not re.fullmatch(r'[0-9a-f]{64}', str(sha)):
            raise ValueError('资产摘要无效: %s' % name)
    images = info['inputs'].get('images')
    if not isinstance(images, list) or any(not isinstance(n, str) for n in images) or set(images) != set(info['assets']):
        raise ValueError('资产清单与已记录图片索引不一致')
    paths = [safe_path(root, name) for name in outs.values()]
    for i, path in enumerate(paths):
        if os.path.islink(path) or any(same_file(path, other) for other in paths[i + 1:]):
            raise ValueError('产物路径存在符号链接或文件别名冲突')
        if any(same_file(path, safe_path(root, name)) for name in info['assets']):
            raise ValueError('资产与产物指向同一文件')
    return info


def finding(severity, matched, message, category='产物版本'):
    return {'severity': severity, 'category': category, 'line': 0,
            'matched': str(matched), 'message': message,
            'suggest': '使用定稿与原渲染参数重新生成；不要交付无法验证的产物'}


def assert_asset_references(info, root):
    referenced = set()
    for name in info['outputs'].values():
        path = safe_path(root, name)
        if os.path.isfile(path):
            referenced.update(collect_assets(open_source(path).decode('utf-8'), root, sheet=False))
    if referenced != set(info['assets']):
        raise ValueError('资产清单与实际交付物引用不一致')


def current_fingerprint(raw, meta, out_dir):
    info = load_manifest(os.path.join(out_dir, 'build.json'))
    validate_manifest(info, out_dir)
    import md2wx
    try:
        theme = md2wx.load_theme(info['render']['theme'])
    except SystemExit as exc:
        raise ValueError(str(exc))
    return context(raw, theme, info['render'], out_dir)[0]


def validate_artifacts(out_dir, raw, meta):
    path = os.path.join(out_dir, 'build.json')
    if not os.path.isfile(path):
        found = any(os.path.isfile(os.path.join(out_dir, n)) for n in ('article.html', 'article.body.html', 'sheet.html'))
        return [finding('medium', '缺 build.json' if found else out_dir,
                        '没有完整构建清单，无法校验产物内容或指纹' if found else '输出目录里没有可校验的产物')]
    try:
        info = load_manifest(path)
        # 旧清单保留可诊断的迁移路径，不允许结构错误或路径逃逸。
        for name in info.get('outputs', {}).values():
            safe_path(out_dir, name)
        if info.get('schema') != SCHEMA:
            issues = [finding('medium', 'build.json', '旧构建清单无法完整验证，请重新生成')]
            for name in info.get('outputs', {}).values():
                if not os.path.isfile(safe_path(out_dir, name)):
                    issues.append(finding('high', name, '清单声明的产物不存在'))
            return issues
        validate_manifest(info, out_dir)
        assert_asset_references(info, out_dir)
        expect = current_fingerprint(raw, meta, out_dir)
    except (ValueError, OSError, TypeError) as exc:
        return [finding('high', 'build.json', str(exc))]
    issues = []
    if expect != info['fingerprint']:
        issues.append(finding('high', 'build.json 指纹', '源稿、主题、资产或渲染代码已改变，当前交付物为旧版本'))
    if digest(raw.encode('utf-8')) != info['inputs']['text_sha256']:
        issues.append(finding('high', 'build.json 源稿摘要', '当前源稿与构建时不一致'))
    for role, name in info['outputs'].items():
        asset = safe_path(out_dir, name)
        if not os.path.isfile(asset):
            issues.append(finding('high', name, '清单声明的产物不存在'))
            continue
        if file_digest(asset) != info['artifact_sha256'][role]:
            issues.append(finding('high', name, '产物内容被修改或替换，与构建清单不符'))
        if role != 'body':
            with open(asset, encoding='utf-8') as fh:
                embedded = wxmeta.extract_fingerprint(fh.read())
            if embedded != info['fingerprint']:
                issues.append(finding('high', name + ' 指纹', '产物内嵌指纹与清单不一致'))
    for name, sha in info['assets'].items():
        asset = safe_path(out_dir, name)
        if sha is None:
            issues.append(finding('medium', name, '构建时本地图片缺失，图片显示尚未验证'))
        elif not os.path.isfile(asset) or file_digest(asset) != sha:
            issues.append(finding('high', name, '本地图片或封面缺失/已改变'))
    return issues


def png_size(path):
    """只读 PNG 头拿宽高，不依赖 Pillow。"""
    with open(path, 'rb') as fh:
        head = fh.read(24)
    if len(head) < 24 or head[:8] != b'\x89PNG\r\n\x1a\n' or head[12:16] != b'IHDR':
        raise ValueError('不是有效的 PNG 文件')
    return struct.unpack('>II', head[16:24])


def validate_covers(out_dir, require=False):
    """按项目规格检查文件存在及 PNG 头尺寸，不完整解码图像。

    require=False 时缺失只作提示（仅排版/仅体检等局部任务）；
    require=True（--publish）时缺失直接判 high。
    这不是平台要求或实际上传结果的验证。
    """
    issues = []
    for name, width, height, label in COVER_SPECS:
        path = os.path.join(out_dir, name)
        if not os.path.isfile(path):
            issues.append(finding(
                'high' if require else 'low', name,
                '发布就绪交付缺少%s，请补齐本项目约定封面' % label if require
                else '未生成%s；按本项目发布就绪规格验收时加 --publish 检查' % label,
                category='封面'))
            continue
        try:
            actual = png_size(path)
        except (ValueError, OSError) as exc:
            issues.append(finding('high', name, '封面无法解析: %s' % exc, category='封面'))
            continue
        if actual != (width, height):
            issues.append(finding(
                'high', name,
                '%s按本项目规格应为 %dx%d，实际 %dx%d'
                % (label, width, height, actual[0], actual[1]),
                category='封面'))
    return issues


def _atomic_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.wx-write-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def apply_files(writes, remove=()):
    paths = list(writes)
    for i, path in enumerate(paths):
        if any(same_file(path, other) for other in paths[i + 1:]):
            raise ValueError('写入目标存在文件身份冲突: %s' % path)
    # 清理按实际身份排除新写入文件，兼容父目录别名和大小写不敏感卷。
    remove = {p for p in remove if not any(same_file(p, target) for target in paths)}
    backups = {}
    for path in set(writes) | remove:
        if os.path.islink(path) or (os.path.exists(path) and not os.path.isfile(path)):
            raise ValueError('写入/清理目标不是安全普通文件: %s' % path)
        parent = os.path.dirname(os.path.abspath(path))
        while not os.path.exists(parent):
            parent = os.path.dirname(parent)
        if not os.path.isdir(parent):
            raise ValueError('写入/清理目标父路径不是目录: %s' % path)
        backups[path] = open_source(path) if os.path.isfile(path) else None
    try:
        for path, data in writes.items():
            _atomic_write(path, data)
        for path in remove:
            if os.path.isfile(path):
                os.unlink(path)
    except OSError:
        for path, data in backups.items():
            if data is None:
                if os.path.isfile(path):
                    os.unlink(path)
            else:
                _atomic_write(path, data)
        raise


def commit_build(out_dir, info, contents):
    validate_manifest(info, out_dir)
    remove = []
    current = os.path.join(out_dir, 'build.json')
    if os.path.isfile(current):
        try:
            old = validate_manifest(load_manifest(current), out_dir)
        except (ValueError, OSError, TypeError):
            old = None  # 不根据损坏清单删除文件；重建仍可修复清单。
        if old:
            for name in old['outputs'].values():
                path = safe_path(out_dir, name)
                if name not in contents:
                    protected = [info['source']] + [safe_path(out_dir, n) for n in info['assets']]
                    if any(same_file(path, p) for p in protected):
                        raise ValueError('旧产物清理会影响当前源稿/资产')
                    remove.append(path)
    writes = {safe_path(out_dir, name): data for name, data in contents.items()}
    writes[os.path.join(os.path.abspath(out_dir), 'build.json')] = json.dumps(info, ensure_ascii=False, indent=2).encode('utf-8')
    apply_files(writes, remove)


def save_snapshot(out_dir, info, raw):
    validate_manifest(info, out_dir)
    if any(v is None for v in info['assets'].values()):
        raise ValueError('本地图片缺失，不能保存完整快照')
    root = os.path.join(out_dir, '.builds')
    if os.path.islink(root):
        raise ValueError('快照目录不能是符号链接')
    os.makedirs(root, exist_ok=True)
    snap = os.path.join(root, info['fingerprint'])
    if os.path.exists(snap):
        _snapshot_payload(snap, info['fingerprint'])
        return snap
    stage = tempfile.mkdtemp(prefix='.pending-', dir=root)
    try:
        for name in list(info['outputs'].values()) + list(info['assets']):
            target = safe_path(stage, name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(safe_path(out_dir, name), target)
        source = info['source']
        data = raw.encode('utf-8') if source == 'stdin' else open_source(source)
        _atomic_write(os.path.join(stage, SOURCE_COPY), data)
        stored = dict(info)
        stored['snapshot'] = {'source_file': SOURCE_COPY, 'source_sha256': digest(data)}
        _atomic_write(os.path.join(stage, 'build.json'), json.dumps(stored, ensure_ascii=False, indent=2).encode('utf-8'))
        _snapshot_payload(stage, info['fingerprint'])
        os.rename(stage, snap)
    finally:
        if os.path.isdir(stage):
            shutil.rmtree(stage)
    return snap


def open_source(path):
    with open(path, 'rb') as fh:
        return fh.read()


def _snapshot_payload(snap, fp):
    if os.path.islink(snap):
        raise ValueError('快照不能是符号链接')
    info = validate_manifest(load_manifest(os.path.join(snap, 'build.json')), snap)
    if info['fingerprint'] != fp:
        raise ValueError('快照指纹与目录不一致')
    payload = {}
    for role, name in info['outputs'].items():
        data = open_source(safe_path(snap, name))
        if digest(data) != info['artifact_sha256'][role]:
            raise ValueError('快照产物损坏: %s' % name)
        payload[name] = data
    for name, sha in info['assets'].items():
        data = open_source(safe_path(snap, name))
        if digest(data) != sha:
            raise ValueError('快照资产损坏: %s' % name)
        payload[name] = data
    assert_asset_references(info, snap)
    saved = info.get('snapshot')
    if not isinstance(saved, dict) or saved.get('source_file') != SOURCE_COPY:
        raise ValueError('快照缺少源稿备份')
    source_copy = os.path.join(snap, SOURCE_COPY)
    if os.path.islink(source_copy):
        raise ValueError('快照源稿不能是符号链接')
    source = open_source(source_copy)
    if digest(source) != saved.get('source_sha256'):
        raise ValueError('快照源稿损坏')
    text = source.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
    if digest(text.encode('utf-8')) != info['inputs']['text_sha256']:
        raise ValueError('快照源稿与生成产物时的源稿不一致')
    return info, payload, source


def rollback(out_dir, fp):
    if not re.fullmatch(r'[0-9a-f]{12,40}', fp):
        raise ValueError('无效快照指纹，请先运行 --list-builds')
    root = os.path.join(out_dir, '.builds')
    if os.path.islink(root):
        raise ValueError('快照目录不能是符号链接')
    snap = os.path.join(root, fp)
    info, payload, source = _snapshot_payload(snap, fp)
    source_path = info['source'] if info['source'] != 'stdin' else os.path.join(os.path.abspath(out_dir), 'article.md')
    if not os.path.isabs(source_path) or os.path.islink(source_path):
        raise ValueError('源稿恢复路径无效或为符号链接')
    preflight(out_dir, info['outputs'], info['assets'], source_path)
    writes = {safe_path(out_dir, name): data for name, data in payload.items()}
    if any(same_file(source_path, path) for path in writes):
        raise ValueError('源稿恢复路径与产物/资产冲突')
    writes[source_path] = source
    writes[os.path.join(os.path.abspath(out_dir), 'build.json')] = json.dumps(info, ensure_ascii=False, indent=2).encode('utf-8')
    remove = set()
    current = os.path.join(out_dir, 'build.json')
    if os.path.isfile(current):
        old = validate_manifest(load_manifest(current), out_dir)
        for name in list(old['outputs'].values()) + list(old['assets']):
            target = safe_path(out_dir, name)
            if not any(same_file(target, path) for path in writes):
                remove.add(target)
    # 完整验证快照后，生成与回退共用目标检查、别名排除和异常恢复。
    apply_files(writes, remove)
    return info, sorted(payload)
