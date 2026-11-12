import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, mkdir, readFile, writeFile, rm, symlink, access} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {parseArgs, rendererOptions, codeFingerprint, createPlayerHtml, renderProject} from '../render-support.mjs';

const digest = (data: string | Buffer) => createHash('sha256').update(data).digest('hex');
async function fixture() {
  const project = await mkdtemp(path.join(tmpdir(), 'article-video-test-'));
  await mkdir(path.join(project, 'audio'));
  const audio = Buffer.from('RIFF test audio fixture');
  await writeFile(path.join(project, 'audio', 'a.wav'), audio);
  const timeline = {version: 1, title: '本地测试', width: 1080, height: 1920, fps: 30, durationInFrames: 42,
    plan_sha256: 'a'.repeat(64), mode: 'demo-local', scenes: [{id: 'one', kind: 'hook', title: '问题', body: ['方法'], from: 0, durationInFrames: 42,
      captions: [{text: '一句话。', from: 0, durationInFrames: 30, audio: 'audio/a.wav', audioSha256: digest(audio)}]}]};
  await writeFile(path.join(project, 'timeline.json'), JSON.stringify(timeline));
  return {project, timeline};
}
// Only the expensive encoder/browser boundary is replaced. Real validation, files, receipt and cleanup run.
const backend = {
  bundle: async (_options: unknown) => '/test/bundle',
  selectComposition: async () => ({id: 'ArticleVideo', width: 1080, height: 1920, fps: 30, durationInFrames: 42, props: {}, defaultProps: {}}),
  renderMedia: async ({outputLocation}: {outputLocation: string}) => {await writeFile(outputLocation, 'new mp4');},
  renderStill: async ({output}: {output: string}) => {await writeFile(output, 'new png');},
};

test('CLI requires absolute project, rejects unknown args, and scales only to even H264 dimensions', () => {
  assert.deepEqual(parseArgs(['--project', '/tmp/build']), {project: '/tmp/build', scale: 1});
  assert.deepEqual(parseArgs(['--project', '/tmp/build', '--scale', '0.25']), {project: '/tmp/build', scale: 0.25});
  for (const args of [[], ['--project'], ['--project', 'relative'], ['--project', '/tmp/a', '--bad'],
    ['--project', '/tmp/a', '--scale', 'NaN'], ['--project', '/tmp/a', '--scale', '0'],
    ['--project', '/tmp/a', '--scale', '2'], ['--project', '/tmp/a', '--scale', '0.333'],
    ['--project', '/tmp/a', '--project', '/tmp/b']]) assert.throws(() => parseArgs(args));
});

test('only explicit environment forwards license key; default does not assert eligibility', () => {
  assert.deepEqual(rendererOptions({}), {});
  assert.deepEqual(rendererOptions({REMOTION_BROWSER_EXECUTABLE: '/local/chrome'}), {browserExecutable: '/local/chrome'});
  assert.deepEqual(rendererOptions({REMOTION_LICENSE_KEY: 'explicit-key'}), {licenseKey: 'explicit-key'});
  assert.deepEqual(rendererOptions({REMOTION_LICENSE_KEY: ''}), {});
});

test('HTML escapes untrusted title and diagnoses playback errors with only local assets', () => {
  const html = createPlayerHtml({title: '<img src=x onerror=alert(1)> & "标题"', mode: 'demo-local', fps: 30, durationInFrames: 3600}, 0.25);
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt; &amp; &quot;标题&quot;'));
  assert.ok(!html.includes('<img src=x'));
  assert.match(html, /src="video\.mp4"/);
  assert.match(html, /120\.00/);
  assert.match(html, /demo-local/);
  assert.match(html, /在线音色|Azure/);
  assert.match(html, /error|错误/);
  assert.ok(!/https?:\/\/|cdn\./.test(html));
});

test('fingerprint binds allowed code paths, names and bytes but ignores tests, dependencies and caches', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'article-video-fingerprint-'));
  try {
    await mkdir(path.join(root, 'src')); await mkdir(path.join(root, 'node_modules')); await mkdir(path.join(root, '.cache'));
    for (const [file, content] of [['src/index.ts', 'source'], ['render.mjs', 'renderer'], ['render-support.mjs', 'support'], ['package.json', '{}'], ['package-lock.json', '{}'], ['tsconfig.json', '{}']]) {
      await writeFile(path.join(root, file), content);
    }
    const first = await codeFingerprint(root);
    assert.match(first, /^[a-f0-9]{64}$/);
    await writeFile(path.join(root, 'node_modules', 'data'), 'changed'); await writeFile(path.join(root, '.cache', 'x'), 'changed');
    await writeFile(path.join(root, 'tests.test.ts'), 'test only');
    assert.equal(await codeFingerprint(root), first);
    await writeFile(path.join(root, 'src', 'index.ts'), 'different');
    assert.notEqual(await codeFingerprint(root), first);
    const second = await codeFingerprint(root);
    await writeFile(path.join(root, 'src', '.hidden.ts'), 'hidden source is still code');
    assert.notEqual(await codeFingerprint(root), second);
    await rm(path.join(root, 'src', '.hidden.ts'));
    await writeFile(path.join(root, 'render-helper.mjs'), 'new helper');
    assert.notEqual(await codeFingerprint(root), second);
    const third = await codeFingerprint(root);
    await writeFile(path.join(root, 'package-lock.json'), '{"changed":true}');
    assert.notEqual(await codeFingerprint(root), third);
  } finally {await rm(root, {recursive: true, force: true});}
});

test('successful render receipt binds exact inputs, code, output hashes and test-scale dimensions', async () => {
  const {project} = await fixture();
  try {
    await renderProject(project, 0.25, backend, {});
    const receipt = JSON.parse(await readFile(path.join(project, 'render-receipt.json'), 'utf8'));
    assert.equal(receipt.timelineSha256, digest(await readFile(path.join(project, 'timeline.json'))));
    assert.equal(receipt.rendererSha256, await codeFingerprint());
    assert.deepEqual([receipt.scale, receipt.width, receipt.height, receipt.fps], [0.25, 270, 480, 30]);
    assert.deepEqual(Object.keys(receipt.outputs).sort(), ['cover.png', 'index.html', 'video.mp4']);
    for (const output of Object.keys(receipt.outputs)) assert.equal(receipt.outputs[output], digest(await readFile(path.join(project, output))));
    await assert.rejects(access(path.join(project, '.render-lock')));
  } finally {await rm(project, {recursive: true, force: true});}
});

for (const failure of ['encode', 'cover', 'timeline', 'audio', 'changed-timeline', 'changed-audio']) {
  test(`failed ${failure} leaves no stale delivery or receipt`, async () => {
    const {project, timeline} = await fixture();
    try {
      for (const file of ['video.mp4', 'cover.png', 'index.html', 'render-receipt.json']) await writeFile(path.join(project, file), 'old delivery');
      const broken = {...backend};
      if (failure === 'encode') broken.renderMedia = async () => {throw new Error('encoder failed');};
      if (failure === 'cover') broken.renderStill = async () => {throw new Error('cover failed');};
      if (failure === 'timeline') await writeFile(path.join(project, 'timeline.json'), '{}');
      if (failure === 'audio') await writeFile(path.join(project, 'audio', 'a.wav'), 'corrupt');
      if (failure === 'changed-timeline') broken.renderStill = async ({output}) => {await writeFile(output, 'png'); await writeFile(path.join(project, 'timeline.json'), JSON.stringify({...timeline, title: '改稿'}));};
      if (failure === 'changed-audio') broken.renderStill = async ({output}) => {await writeFile(output, 'png'); await writeFile(path.join(project, 'audio', 'a.wav'), 'changed');};
      await assert.rejects(renderProject(project, 1, broken, {}));
      for (const file of ['video.mp4', 'cover.png', 'index.html', 'render-receipt.json', '.render-lock']) await assert.rejects(access(path.join(project, file)));
    } finally {await rm(project, {recursive: true, force: true});}
  });
}

test('rejects audio and public-directory symlinks rather than serving outside project files', async () => {
  const {project} = await fixture();
  try {
    await rm(path.join(project, 'audio', 'a.wav'));
    await symlink('/etc/hosts', path.join(project, 'audio', 'a.wav'));
    await assert.rejects(renderProject(project, 1, backend, {}), /symlink/i);
    await rm(path.join(project, 'audio', 'a.wav'));
    await writeFile(path.join(project, 'audio', 'a.wav'), 'RIFF test audio fixture');
    await symlink('/etc', path.join(project, 'other'));
    await assert.rejects(renderProject(project, 1, backend, {}), /symlink/i);
  } finally {await rm(project, {recursive: true, force: true});}
});

test('held render lock does not destroy an active renderer delivery', async () => {
  const {project} = await fixture();
  try {
    await writeFile(path.join(project, '.render-lock'), 'active');
    await writeFile(path.join(project, 'video.mp4'), 'active output');
    await assert.rejects(renderProject(project, 1, backend, {}), /already|lock/i);
    assert.equal(await readFile(path.join(project, 'video.mp4'), 'utf8'), 'active output');
  } finally {await rm(project, {recursive: true, force: true});}
});
