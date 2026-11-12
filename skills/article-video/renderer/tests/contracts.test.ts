import assert from 'node:assert/strict';
import test from 'node:test';

import {validateTimeline} from '../src/contracts.ts';

export function timeline() {
  return {
    version: 1, title: '把知识讲清楚', width: 1080, height: 1920, fps: 30,
    durationInFrames: 76, plan_sha256: 'a'.repeat(64), mode: 'demo-local',
    scenes: [{id: 'opening', kind: 'hook', title: '先抓住一个问题', body: ['把复杂问题拆成清晰的小步骤'],
      from: 0, durationInFrames: 76, captions: [
        {text: '我们从一个问题开始。', from: 0, durationInFrames: 30, audio: 'audio/first.wav', audioSha256: 'b'.repeat(64)},
        {text: '再找到可执行的方法。', from: 34, durationInFrames: 30, audio: 'audio/second.wav', audioSha256: 'c'.repeat(64)},
      ]}],
  };
}

test('accepts each of the five layouts with valid body counts', () => {
  for (const kind of ['hook', 'points', 'steps', 'compare', 'summary']) {
    const value = timeline(); value.scenes[0].kind = kind;
    value.scenes[0].body = ['第一条内容', '第二条内容'];
    assert.equal(validateTimeline(value), value);
  }
});

test('rejects resources outside audio directory or not local WAV', () => {
  for (const audio of ['../outside.wav', 'audio/../outside.wav', '/audio/first.wav',
    'https://x.invalid/a.wav', '//host/audio/a.wav', 'file:///a.wav', 'audio\\first.wav',
    'audio/%2e%2e/a.wav', 'audio/./first.wav', 'audio/nested/a.wav', 'audio/a.mp3', 'other/a.wav',
    'audio/a.wav?x=1', 'audio/a.wav#x', 'audio//a.wav', 'audio/a\u0000.wav', 'C:/audio/a.wav']) {
    const value = timeline(); value.scenes[0].captions[0].audio = audio;
    assert.throws(() => validateTimeline(value), /audio|path|WAV/i, audio);
  }
});

test('enforces continuous global scene frames and exact total', () => {
  const valid = timeline();
  valid.scenes.push({...structuredClone(valid.scenes[0]), id: 'second', from: 76});
  valid.durationInFrames = 152;
  assert.equal(validateTimeline(valid), valid);
  for (const from of [-1, 1, 77, 75, 76.1]) {
    const invalid = structuredClone(valid); invalid.scenes[1].from = from;
    assert.throws(() => validateTimeline(invalid), /from|continuous|integer/i);
  }
  for (const duration of [0, 153, NaN, Infinity, 152.5]) {
    const invalid = structuredClone(valid); invalid.durationInFrames = duration;
    assert.throws(() => validateTimeline(invalid), /duration|integer/i);
  }
});

test('enforces caption duration, four-frame gaps and twelve-frame tail', () => {
  for (const mutate of [
    (t: ReturnType<typeof timeline>) => {t.scenes[0].captions[0].from = 1;},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].captions[1].from = 29;},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].captions[1].from = 35;},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].captions[0].durationInFrames = 0;},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].captions[0].durationInFrames = 1.5;},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].durationInFrames = 75; t.durationInFrames = 75;},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].captions = [];},
  ]) {const t = timeline(); mutate(t); assert.throws(() => validateTimeline(t));}
});

test('enforces code-point text limits, plain single-line text and meaningful captions', () => {
  const valid = timeline(); valid.title = '文'.repeat(32); valid.scenes[0].title = '文'.repeat(24);
  valid.scenes[0].body = ['文'.repeat(46)]; valid.scenes[0].captions[0].text = '文'.repeat(42);
  assert.equal(validateTimeline(valid), valid);
  for (const mutate of [
    (t: ReturnType<typeof timeline>) => {t.title = '文'.repeat(33);},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].title = '文'.repeat(25);},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].body = ['文'.repeat(47)];},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].captions[0].text = '文'.repeat(43);},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].captions[0].text = '！！……';},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].captions[0].text = '一句\n另一句';},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].title = ' ';},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].body = ['\u202e隐藏'];},
  ]) {const t = timeline(); mutate(t); assert.throws(() => validateTimeline(t));}
});

test('accepts Python-compatible scene ids including consecutive/trailing hyphens', () => {
  const t = timeline(); t.scenes[0].id = 'scene--1-';
  assert.equal(validateTimeline(t), t);
});

test('rejects bad kinds, ids, hashes, modes, canvas settings and body counts', () => {
  for (const mutate of [
    (t: ReturnType<typeof timeline>) => {t.scenes[0].kind = 'chart';},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].id = 'Scene_1';},
    (t: ReturnType<typeof timeline>) => {t.plan_sha256 = 'bad';},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].captions[0].audioSha256 = 'bad';},
    (t: ReturnType<typeof timeline>) => {t.mode = 'unknown';},
    (t: ReturnType<typeof timeline>) => {t.version = 2;},
    (t: ReturnType<typeof timeline>) => {t.width = 720;},
    (t: ReturnType<typeof timeline>) => {t.height = 1080;},
    (t: ReturnType<typeof timeline>) => {t.fps = 25;},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].body = [];},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].body = ['a', 'b', 'c', 'd'];},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].kind = 'compare';},
    (t: ReturnType<typeof timeline>) => {t.scenes[0].kind = 'steps';},
    (t: ReturnType<typeof timeline>) => {t.scenes = [];},
  ]) {const t = timeline(); mutate(t); assert.throws(() => validateTimeline(t));}
  const t = timeline(); t.scenes.push({...t.scenes[0], from: 76}); t.durationInFrames = 152;
  assert.throws(() => validateTimeline(t), /unique|duplicate|id/i);
  for (const t of [null, [], {}, 'timeline']) assert.throws(() => validateTimeline(t));
});
