import assert from 'node:assert/strict';
import test from 'node:test';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdtemp, mkdir, readFile, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {renderProject} from '../render-support.mjs';

const run = promisify(execFile);

test('真实编码输出 limited-range yuv420p 和 BT.709，而非 JPEG full-range',
  {skip: !process.env.REMOTION_BROWSER_EXECUTABLE, timeout: 120_000}, async () => {
  const project = await mkdtemp(path.join(tmpdir(), 'article-video-color-'));
  try {
    await mkdir(path.join(project, 'audio'));
    const wav = path.join(project, 'audio', 'tone.wav');
    await run('ffmpeg', ['-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=24000',
      '-t', '1', '-ac', '1', '-c:a', 'pcm_s16le', wav]);
    const audioSha256 = createHash('sha256').update(await readFile(wav)).digest('hex');
    const timeline = {version: 1, title: '色彩空间检查', width: 1080, height: 1920, fps: 30, durationInFrames: 42,
      plan_sha256: 'a'.repeat(64), mode: 'demo-local', scenes: [{id: 'color', kind: 'hook', title: '颜色应正确编码',
        body: ['真实媒体校验'], from: 0, durationInFrames: 42,
        captions: [{text: '这是一条测试字幕。', from: 0, durationInFrames: 30, audio: 'audio/tone.wav', audioSha256}]}]};
    await writeFile(path.join(project, 'timeline.json'), JSON.stringify(timeline));
    await renderProject(project, 1);
    const {stdout} = await run('ffprobe', ['-v', 'error', '-show_streams', '-of', 'json', path.join(project, 'video.mp4')]);
    const video = JSON.parse(stdout).streams.find((stream: {codec_type: string}) => stream.codec_type === 'video');
    assert.equal(video.pix_fmt, 'yuv420p');
    assert.equal(video.color_space, 'bt709');
    assert.equal(video.color_range, 'tv');
  } finally {
    await rm(project, {recursive: true, force: true});
  }
});
