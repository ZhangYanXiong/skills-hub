"""新版产物完整性与真实快照/回退回归。"""
import hashlib
import json
from pathlib import Path

from support import WorkspaceTest

ARTICLE = "---\ntitle: 构建演示\ntitle_short: 演示\nsummary: 验证交付流程。\ntheme: tech\n---\n\n# 演示\n\n旧版正文。\n"


class BuildIntegrityTests(WorkspaceTest):
    def setUp(self):
        super().setUp()
        self.article = self.write('source/article.md', ARTICLE)
        self.out = self.root / 'delivery'
        self.target = self.out / 'article.html'

    def render(self, *args):
        p = self.run_script('md2wx.py', self.article, '-o', self.target, *args)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def manifest(self):
        return json.loads((self.out / 'build.json').read_text())

    def check(self):
        p = self.run_script('lint.py', self.article, '--out', self.out, '--strict', '--json')
        self.assertNotIn('Traceback', p.stderr)
        return p, json.loads(p.stdout)

    def test_fresh_theme_override_passes(self):
        self.render('--sheet', '-t', 'growth')
        p, r = self.check()
        self.assertEqual(p.returncode, 0, r)
        self.assertEqual(r['counts']['high'], 0)

    def test_declared_missing_outputs_block(self):
        for name in ('article.html', 'article.body.html', 'sheet.html'):
            with self.subTest(name=name):
                self.render('--sheet')
                (self.out / name).unlink()
                p, r = self.check()
                self.assertEqual(p.returncode, 1, r)
                self.assertTrue(any(name in f['matched'] for f in r['findings']))

    def test_every_artifact_content_is_checked(self):
        for name in ('article.html', 'article.body.html', 'sheet.html'):
            with self.subTest(name=name):
                self.render('--sheet')
                path = self.out / name
                path.write_text(path.read_text().replace('旧版正文', '伪造正文'))
                p, r = self.check()
                self.assertEqual(p.returncode, 1, r)

    def test_invalid_manifest_shapes_are_json_findings(self):
        for data in ([1], {'outputs': ['article.html']}, {'outputs': {'html': '../escape.html'}}):
            with self.subTest(data=data):
                self.render('--sheet')
                (self.out / 'build.json').write_text(json.dumps(data))
                p, r = self.check()
                self.assertEqual(p.returncode, 1, r)
                self.assertGreater(r['counts']['high'], 0)

    def test_missing_digest_does_not_silently_pass(self):
        self.render('--sheet')
        info = self.manifest()
        info.pop('artifact_sha256')
        (self.out / 'build.json').write_text(json.dumps(info))
        p, r = self.check()
        self.assertGreater(r['counts']['high'] + r['counts']['medium'], 0)

    def test_no_body_only_validates_requested_files(self):
        self.render('--no-body')
        p, r = self.check()
        self.assertEqual(p.returncode, 0, r)
        self.assertFalse((self.out / 'article.body.html').exists())
        self.assertFalse((self.out / 'sheet.html').exists())

    def test_nested_output_names_remain_valid(self):
        self.target = self.out / 'nested' / 'custom.html'
        self.render('--sheet')
        self.out = self.target.parent
        p, r = self.check()
        self.assertEqual(p.returncode, 0, r)

    def test_title_overrides_have_distinct_immutable_snapshots(self):
        self.render('--sheet', '--snapshot', '--title', '页面A')
        a = self.manifest()['fingerprint']
        self.render('--sheet', '--snapshot', '--title', '页面B')
        b = self.manifest()['fingerprint']
        self.assertNotEqual(a, b)
        p = self.run_script('md2wx.py', '--rollback', a, '--out-dir', self.out)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('<title>页面A</title>', self.target.read_text())
        p, r = self.check()
        self.assertEqual(p.returncode, 0, r)

    def test_asset_bytes_participate_in_fingerprint(self):
        self.render()
        image = self.out / 'figure.png'
        image.write_bytes(b'asset version one')
        self.article.write_text(ARTICLE + '\n![示意图](figure.png)\n')
        self.render('--sheet')
        old = self.manifest()['fingerprint']
        image.write_bytes(b'asset version two')
        p, r = self.check()
        self.assertEqual(p.returncode, 1, r)
        self.render('--sheet')
        self.assertNotEqual(old, self.manifest()['fingerprint'])

    def test_complete_rollback_restores_source_images_and_covers(self):
        self.render()
        image = self.out / 'assets' / 'figure.png'
        image.parent.mkdir()
        image.write_bytes(b'old image')
        cover = self.out / 'cover.png'
        old_cover = (Path(__file__).resolve().parents[3] / 'outputs/wechat-mp/2026-11-11-周报复盘/cover.png').read_bytes()
        cover.write_bytes(old_cover)
        self.article.write_text(ARTICLE + '\n![图片](assets/figure.png)\n')
        source = self.article.read_bytes()
        self.render('--sheet', '--snapshot')
        fp = self.manifest()['fingerprint']
        self.article.write_text(self.article.read_text().replace('旧版', '新版'))
        image.write_bytes(b'new image')
        cover.write_bytes(old_cover + b'new version')
        self.render('--sheet', '--snapshot')
        p = self.run_script('md2wx.py', '--rollback', fp, '--out-dir', self.out)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.article.read_bytes(), source)
        self.assertEqual(image.read_bytes(), b'old image')
        self.assertEqual(cover.read_bytes(), old_cover)
        self.assertIn('旧版正文', self.target.read_text())
        p, r = self.check()
        self.assertEqual(p.returncode, 0, r)

    def test_rollback_clears_previous_declared_unrequested_sheet(self):
        self.render('--snapshot')
        fp = self.manifest()['fingerprint']
        self.article.write_text(ARTICLE.replace('旧版', '新版'))
        self.render('--sheet', '--snapshot')
        self.assertTrue((self.out / 'sheet.html').exists())
        p = self.run_script('md2wx.py', '--rollback', fp, '--out-dir', self.out)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertFalse((self.out / 'sheet.html').exists())
        p, r = self.check()
        self.assertEqual(p.returncode, 0, r)

    def test_repeated_snapshot_does_not_mutate_history(self):
        self.render('--sheet', '--snapshot')
        fp = self.manifest()['fingerprint']
        snap = self.out / '.builds' / fp
        before = {str(p.relative_to(snap)): p.read_bytes() for p in snap.rglob('*') if p.is_file()}
        self.render('--sheet', '--snapshot')
        after = {str(p.relative_to(snap)): p.read_bytes() for p in snap.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_rollback_rejects_bad_identifier_before_writing(self):
        self.render('--sheet', '--snapshot')
        old = self.target.read_bytes()
        p = self.run_script('md2wx.py', '--rollback', '../..', '--out-dir', self.out)
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn('Traceback', p.stderr)
        self.assertEqual(self.target.read_bytes(), old)

    def test_corrupt_snapshot_is_rejected_before_partial_restore(self):
        self.render('--sheet', '--snapshot')
        fp = self.manifest()['fingerprint']
        snap = self.out / '.builds' / fp
        info = json.loads((snap / 'build.json').read_text())
        saved = snap / info['outputs']['html']
        saved.write_bytes(b'corrupted')
        self.article.write_text(ARTICLE.replace('旧版', '新版'))
        self.render('--sheet')
        old = self.target.read_bytes()
        source = self.article.read_bytes()
        p = self.run_script('md2wx.py', '--rollback', fp, '--out-dir', self.out)
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn('Traceback', p.stderr)
        self.assertEqual(self.target.read_bytes(), old)
        self.assertEqual(self.article.read_bytes(), source)

    def test_snapshot_with_missing_image_fails_cleanly(self):
        self.article.write_text(ARTICLE + '\n![图](missing.png)\n')
        p = self.run_script('md2wx.py', self.article, '--sheet', '--snapshot', '-o', self.target)
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn('Traceback', p.stderr)

    def test_manifest_symlink_cannot_overwrite_external_file(self):
        self.render('--sheet')
        outside = self.write('outside.json', 'keep me')
        manifest = self.out / 'build.json'
        manifest.unlink()
        manifest.symlink_to(outside)
        p = self.run_script('md2wx.py', self.article, '--sheet', '-o', self.target)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(outside.read_text(), 'keep me')
        self.assertNotIn('Traceback', p.stderr)

    def test_snapshot_source_must_match_rendered_source(self):
        self.render('--sheet', '--snapshot')
        fp = self.manifest()['fingerprint']
        snap = self.out / '.builds' / fp
        info = json.loads((snap / 'build.json').read_text())
        backup = snap / info['snapshot']['source_file']
        backup.write_text('different source')
        info['snapshot']['source_sha256'] = hashlib.sha256(backup.read_bytes()).hexdigest()
        (snap / 'build.json').write_text(json.dumps(info))
        old = self.target.read_bytes()
        p = self.run_script('md2wx.py', '--rollback', fp, '--out-dir', self.out)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.target.read_bytes(), old)
        self.assertEqual(self.article.read_text(), ARTICLE)

    def test_snapshot_source_symlink_is_not_followed(self):
        self.render('--sheet', '--snapshot')
        fp = self.manifest()['fingerprint']
        snap = self.out / '.builds' / fp
        info = json.loads((snap / 'build.json').read_text())
        backup = snap / info['snapshot']['source_file']
        backup.unlink()
        backup.symlink_to(self.article)
        p = self.run_script('md2wx.py', '--rollback', fp, '--out-dir', self.out)
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn('Traceback', p.stderr)

    def test_output_aliases_cannot_overwrite_source_or_assets(self):
        self.render('--sheet')
        original = self.article.read_bytes()
        p = self.run_script('md2wx.py', self.article, '-o', self.article, '--snapshot')
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.article.read_bytes(), original)
        self.target.unlink()
        self.target.symlink_to(self.out / 'sheet.html')
        old = (self.out / 'sheet.html').read_bytes()
        p = self.run_script('md2wx.py', self.article, '-o', self.target, '--sheet')
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual((self.out / 'sheet.html').read_bytes(), old)

    def test_asset_alias_to_output_is_rejected_before_write(self):
        self.render()
        image = self.out / 'image.png'
        image.symlink_to(self.target)
        self.article.write_text(ARTICLE + '\n![图](image.png)\n')
        before = self.target.read_bytes()
        p = self.run_script('md2wx.py', self.article, '-o', self.target, '--sheet')
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.target.read_bytes(), before)

    def test_hardlinked_output_cannot_overwrite_source(self):
        import os
        self.out.mkdir()
        os.link(self.article, self.target)
        original = self.article.read_bytes()
        p = self.run_script('md2wx.py', self.article, '-o', self.target)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.article.read_bytes(), original)

    def test_omitting_asset_manifest_is_not_allowed(self):
        self.render()
        image = self.out / 'image.png'
        image.write_bytes(b'old image')
        self.article.write_text(ARTICLE + '\n![图](image.png)\n')
        self.render('--sheet', '--snapshot')
        fp = self.manifest()['fingerprint']
        for root in (self.out, self.out / '.builds' / fp):
            info = json.loads((root / 'build.json').read_text())
            info['assets'] = {}
            (root / 'build.json').write_text(json.dumps(info))
        p, r = self.check()
        self.assertEqual(p.returncode, 1, r)
        old = self.article.read_bytes()
        p = self.run_script('md2wx.py', '--rollback', fp, '--out-dir', self.out)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(image.read_bytes(), b'old image')
        self.assertEqual(self.article.read_bytes(), old)

    def test_omitting_both_asset_indexes_still_fails(self):
        self.render()
        (self.out / 'image.png').write_bytes(b'image')
        self.article.write_text(ARTICLE + '\n![图](image.png)\n')
        self.render('--sheet', '--snapshot')
        fp = self.manifest()['fingerprint']
        snap = self.out / '.builds' / fp
        info = json.loads((snap / 'build.json').read_text())
        info['assets'] = {}
        info['inputs']['images'] = []
        (snap / 'build.json').write_text(json.dumps(info))
        p = self.run_script('md2wx.py', '--rollback', fp, '--out-dir', self.out)
        self.assertNotEqual(p.returncode, 0)

    def test_preflight_directory_target_preserves_previous_files(self):
        self.render('--sheet')
        original = self.target.read_bytes()
        body = self.out / 'article.body.html'
        body.unlink()
        body.mkdir()
        self.article.write_text(ARTICLE.replace('旧版', '新版'))
        p = self.run_script('md2wx.py', self.article, '-o', self.target, '--sheet')
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn('Traceback', p.stderr)
        self.assertEqual(self.target.read_bytes(), original)

    def test_preflight_snapshot_symlink_preserves_previous_files(self):
        self.render('--sheet')
        original = self.target.read_bytes()
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        (self.out / '.builds').symlink_to(elsewhere, target_is_directory=True)
        self.article.write_text(ARTICLE.replace('旧版', '新版'))
        p = self.run_script('md2wx.py', self.article, '-o', self.target, '--sheet', '--snapshot')
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.target.read_bytes(), original)

    def test_switching_options_removes_old_managed_artifacts(self):
        self.render('--sheet')
        self.article.write_text(ARTICLE.replace('旧版', '新版'))
        self.render('--no-body')
        self.assertFalse((self.out / 'sheet.html').exists())
        self.assertFalse((self.out / 'article.body.html').exists())
        p, r = self.check()
        self.assertEqual(p.returncode, 0, r)

    def test_renderer_and_checkers_agree_on_nested_fences(self):
        self.article.write_text(ARTICLE + '\n````markdown\n```\n保证包过 30% [F9]\n````\n')
        cards = self.write('cards.md', '| 编号 | 类型 | 内容 | 出处 | 备注 |\n| --- | --- | --- | --- | --- |\n| F1 | 事实 | 缓存有效 | L1 | |\n')
        self.render('--sheet')
        body = (self.out / 'article.body.html').read_text()
        self.assertIn('<code', body)
        code_start = body.index('<code')
        code_end = body.index('</code>', code_start)
        self.assertIn('保证包过', body[code_start:code_end])
        p = self.run_script('lint.py', self.article, '--cards', cards, '--out', self.out, '--strict', '--json')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        p = self.run_script('check.py', self.article, '--html', self.out / 'article.body.html', '--strict', '--json')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_fence_with_extra_info_interrupts_a_paragraph(self):
        self.article.write_text(ARTICLE + '段落结尾。\n````markdown linenos\n```\n保证包过 30% [F9]\n````\n')
        self.render('--sheet')
        body = (self.out / 'article.body.html').read_text()
        self.assertIn('<code', body)
        start = body.index('<code')
        end = body.index('</code>', start)
        self.assertIn('保证包过', body[start:end])
        self.assertIn('```', body[start:end])
        self.assertNotIn('markdown linenos', body[:start])

    def test_chinese_adverb_is_not_an_unsupported_quantity(self):
        self.article.write_text(ARTICLE + '\n千万不要修改原稿。\n')
        cards = self.write('cards.md', '| 编号 | 类型 | 内容 | 出处 | 备注 |\n| --- | --- | --- | --- | --- |\n| F1 | 事实 | 缓存有效 | L1 | |\n')
        p = self.run_script('lint.py', self.article, '--cards', cards, '--strict', '--json')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_rollback_cleanup_does_not_delete_restored_source_alias(self):
        self.render('--snapshot', '--no-body')
        fp = self.manifest()['fingerprint']
        original = self.article.read_bytes()
        html = self.target.read_bytes()
        self.article.write_text(ARTICLE.replace('旧版', '新版'))
        p = self.run_script('md2wx.py', self.article, '-o', self.out / 'article.md', '--no-body')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.article.parent.rename(self.root / 'source-backup')
        self.article.parent.symlink_to(self.out, target_is_directory=True)
        p = self.run_script('md2wx.py', '--rollback', fp, '--out-dir', self.out)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(self.article.exists())
        self.assertEqual(self.article.read_bytes(), original)
        self.assertEqual(self.target.read_bytes(), html)

    def test_rollback_rejects_source_and_output_parent_alias_collision(self):
        self.article = self.write('source/article.html', ARTICLE)
        self.render('--snapshot', '--no-body')
        fp = self.manifest()['fingerprint']
        self.article.parent.rename(self.root / 'source-backup')
        self.article.parent.symlink_to(self.out, target_is_directory=True)
        before = self.target.read_bytes()
        p = self.run_script('md2wx.py', '--rollback', fp, '--out-dir', self.out)
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn('Traceback', p.stderr)
        self.assertEqual(self.target.read_bytes(), before)

    def test_output_case_change_does_not_remove_new_artifact(self):
        self.render('--no-body')
        self.target = self.out / 'article.HTML'
        self.render('--no-body')
        self.assertTrue(self.target.exists())
        p, report = self.check()
        self.assertEqual(p.returncode, 0, report)

    def test_fixed_manifest_output_cannot_overwrite_source(self):
        self.article = self.write('delivery/build.json', ARTICLE)
        original = self.article.read_bytes()
        p = self.run_script('md2wx.py', self.article, '-o', self.target)
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn('Traceback', p.stderr)
        self.assertEqual(self.article.read_bytes(), original)

    def test_author_overrides_have_distinct_immutable_snapshots(self):
        self.render('--sheet', '--snapshot', '--author', '甲')
        first = self.manifest()['fingerprint']
        self.render('--sheet', '--snapshot', '--author', '乙')
        second = self.manifest()['fingerprint']
        self.assertNotEqual(first, second)
        p = self.run_script('md2wx.py', '--rollback', first, '--out-dir', self.out)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('甲', (self.out / 'sheet.html').read_text())
        p, report = self.check()
        self.assertEqual(p.returncode, 0, report)

    def test_publish_without_output_directory_is_rejected(self):
        p = self.run_script('lint.py', self.article, '--publish', '--strict', '--json')
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn('Traceback', p.stderr)
        self.assertIn('--out', p.stderr)

    def test_list_builds_reports_invalid_json_shape_without_traceback(self):
        self.render('--snapshot')
        valid = self.manifest()['fingerprint']
        self.write('delivery/.builds/aaaaaaaaaaaa/build.json', '[]')
        p = self.run_script('md2wx.py', '--list-builds', '--out-dir', self.out)
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn('Traceback', p.stderr)
        self.assertIn('清单', p.stderr)
        self.assertIn(valid, p.stdout)

    def test_manifest_uses_full_content_digests(self):
        self.render('--sheet')
        info = self.manifest()
        self.assertEqual(info.get('schema'), 2)
        for role, name in info['outputs'].items():
            self.assertEqual(info['artifact_sha256'][role], hashlib.sha256((self.out / name).read_bytes()).hexdigest())
