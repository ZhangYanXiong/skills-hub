#!/usr/bin/env python3
"""临时目录真实 CLI 验收；不安装依赖、不修改演示稿、不访问微信。"""
import ast
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'wechat-mp/scripts'
FIXTURES = ROOT / 'demo-output/weekly-report'


def main():
    steps = []

    def run(name, *args, expected=0, stdin=None):
        proc = subprocess.run(
            [sys.executable, '-I', '-B', str(SCRIPTS / name), *map(str, args)],
            input=stdin, text=True, capture_output=True, cwd=ROOT, timeout=30)
        if proc.returncode != expected or 'Traceback' in proc.stderr:
            raise AssertionError((name, args, proc.returncode, proc.stdout, proc.stderr))
        steps.append({'script': name, 'exit': proc.returncode})
        return json.loads(proc.stdout) if '--json' in args else proc.stdout

    with tempfile.TemporaryDirectory(prefix='wechat-mp-acceptance-') as tmp:
        directory = Path(tmp)
        out, source = directory / 'out', directory / 'article.md'
        source.write_text(
            '---\ntitle: 缓存验收演示\ntitle_short: 缓存演示\n'
            'summary: 验证构建、检查与回退的一致性。\ntheme: tech\n---\n\n'
            '# 缓存验收演示\n\n缓存命中耗时为 30ms [F1]。\n\n![链路](figure.png)\n',
            encoding='utf-8')
        cards, outline = directory / 'cards.md', directory / 'outline.md'
        cards.write_text(
            '| 编号 | 类型 | 内容 | 出处 | 备注 |\n| --- | --- | --- | --- | --- |\n'
            '| F1 | 事实 | 命中耗时 30ms | L1：验收模拟材料 | |\n'
            '| F2 | 事实 | 命中耗时 31ms | L2：验收模拟材料 | |\n', encoding='utf-8')
        outline.write_text(
            '## 主论点\n\n缓存缩短耗时。\n\n## 论点树\n\n支撑一：命中耗时 [F1]\n\n'
            '## 缺口\n\nP0：无\nP1：模拟材料仅用于验收\nP2：无\n', encoding='utf-8')
        out.mkdir()
        for name in ('cover.png', 'cover-square.png', 'cover-thumb.png'):
            shutil.copyfile(FIXTURES / name, out / name)
        pictures = [p for p in sorted(FIXTURES.glob('*.png'))
                    if not p.name.startswith(('cover', 'preview'))]
        if not pictures:
            raise AssertionError('缺少已有验收配图')
        shutil.copyfile(pictures[0], out / 'figure.png')
        run('md2wx.py', source, '-t', 'growth', '--sheet', '--snapshot', '-o', out / 'article.html')
        initial_lint = run('lint.py', source, '--cards', cards, '--outline', outline,
                           '--out', out, '--publish', '--strict', '--json')
        initial_check = run('check.py', source, '--html', out / 'article.body.html', '--strict', '--json')
        assert initial_lint['counts']['high'] == initial_check['counts']['high'] == 0
        fp = json.loads((out / 'build.json').read_text())['fingerprint']
        saved = {p: p.read_bytes() for p in (source, out / 'figure.png', out / 'cover.png')}
        assert '云光迷途' in (out / 'sheet.html').read_text()
        source.write_text(source.read_text().replace('30ms [F1]', '31ms [F2]'), encoding='utf-8')
        for path in (out / 'figure.png', out / 'cover.png'):
            path.write_bytes(path.read_bytes() + b'changed')
        changed = run('lint.py', source, '--cards', cards, '--out', out,
                      '--publish', '--strict', '--json', expected=1)
        assert changed['counts']['high'] > 0
        run('md2wx.py', source, '-t', 'growth', '--sheet', '--snapshot', '-o', out / 'article.html')
        second = json.loads((out / 'build.json').read_text())['fingerprint']
        assert fp != second
        listing = run('md2wx.py', '--list-builds', '--out-dir', out)
        assert fp in listing and second in listing
        run('md2wx.py', '--rollback', fp, '--out-dir', out)
        for path, data in saved.items():
            assert path.read_bytes() == data, str(path)
        restored_lint = run('lint.py', source, '--cards', cards, '--outline', outline,
                            '--out', out, '--publish', '--strict', '--json')
        run('check.py', source, '--html', out / 'article.body.html', '--strict', '--json')
        assert restored_lint['counts']['high'] == 0
        (out / 'article.body.html').unlink()
        missing = run('lint.py', source, '--out', out, '--strict', '--json', expected=1)
        assert missing['counts']['high'] > 0
        source.write_text(source.read_text().replace('title: 缓存验收演示', 'title: 保证包过'), encoding='utf-8')
        risk = run('check.py', source, '--strict', '--json', expected=1)
        assert risk['counts']['high'] > 0
        # 局部排版不要求封面、素材卡、大纲、工作台或快照。
        local = directory / 'local'
        source.write_bytes(saved[source])
        source.write_text(source.read_text().replace('\n![链路](figure.png)\n', '\n'), encoding='utf-8')
        run('md2wx.py', source, '--no-body', '--title', '局部页面', '-o', local / 'custom.htm')
        partial_lint = run('lint.py', source, '--out', local, '--strict', '--json')
        assert partial_lint['counts']['high'] == 0
        assert not (local / 'sheet.html').exists() and not (local / 'custom.body.html').exists()
        run('check.py', source, '--title', '局部页面', '--html', local / 'custom.htm', '--strict', '--json')
        run('md2wx.py', '-', '--sheet', '--snapshot', '-o', directory / 'stdin/article.html', stdin=source.read_text())
        stdin_fp = json.loads((directory / 'stdin/build.json').read_text())['fingerprint']
        run('md2wx.py', '--rollback', stdin_fp, '--out-dir', directory / 'stdin')
        assert (directory / 'stdin/article.md').read_text() == source.read_text()

    files = sorted(SCRIPTS.glob('*.py')) + sorted((ROOT / 'wechat-mp/tests').glob('*.py'))
    for path in files:
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path), feature_version=(3, 9))
    print(json.dumps({
        'status': 'passed', 'cli_steps': len(steps), 'steps': steps,
        'initial_lint': initial_lint['counts'], 'initial_check': initial_check['counts'],
        'rollback_lint': restored_lint['counts'], 'partial_lint': partial_lint['counts'],
        'python': sys.version.split()[0], 'python39_syntax_files': len(files),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
