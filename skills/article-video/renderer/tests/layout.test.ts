import assert from 'node:assert/strict';
import test from 'node:test';
import {fitText, layoutFor, revealFrames, captionAt} from '../src/layout.ts';
import {theme} from '../src/theme.ts';
import type {Scene, SceneKind} from '../src/contracts.ts';

const measure = (text: string, size: number) => Array.from(text).reduce((sum, ch) => sum + (/[\x00-\x7f]/.test(ch) ? 0.65 : 1) * size, 0);
const scene = (kind: SceneKind): Scene => ({id: 'test', kind, title: '文'.repeat(24), body: ['文'.repeat(46), '文'.repeat(46), '文'.repeat(46)].slice(0, kind === 'compare' ? 2 : 3), from: 0, durationInFrames: 200, captions: [
  {text: '字'.repeat(42), from: 0, durationInFrames: 90, audio: 'audio/a.wav', audioSha256: 'a'.repeat(64)},
  {text: '第二句', from: 94, durationInFrames: 94, audio: 'audio/b.wav', audioSha256: 'b'.repeat(64)},
]});

test('long Chinese and Latin text wrap by measured width without clipping or losing characters', () => {
  for (const text of ['文'.repeat(46), 'W'.repeat(46), '中文 English 边界标点：正确表达与清晰阅读。']) {
    const fitted = fitText(text, {width: 650, fontSize: 44, minFontSize: 32, maxLines: 3, lineHeight: 1.4}, measure);
    assert.ok(fitted.lines.length <= 3);
    assert.equal(fitted.lines.join(''), text);
    for (const line of fitted.lines) assert.ok(measure(line, fitted.fontSize) <= 650);
    assert.ok(fitted.height <= 185);
  }
  assert.throws(() => fitText('中文', {width: 1, fontSize: 44, minFontSize: 32, maxLines: 3, lineHeight: 1.4}, measure), /fit|width/i);
});

test('five layouts fit max-length text inside safe zones and above the subtitle band', () => {
  for (const kind of ['hook', 'points', 'steps', 'compare', 'summary'] as const) {
    const layout = layoutFor(scene(kind));
    const boxes = [layout.title, ...layout.items];
    for (const box of boxes) {
      assert.ok(box.x >= 72 && box.x + box.width <= 900, `${kind}: right reserve`);
      assert.ok(box.y >= 200 && box.y + box.height < layout.caption.y - 40, `${kind}: caption separation`);
      const fitted = fitText(box.text, box, measure);
      assert.ok(fitted.height <= box.height, `${kind}: text block height`);
      assert.ok(fitted.lines.length <= box.maxLines);
    }
    assert.ok(layout.caption.x >= 72 && layout.caption.x + layout.caption.width <= 900);
    assert.equal(layout.caption.y, 1280);
    assert.ok(layout.caption.y + layout.caption.height <= 1440);
    const fitted = fitText('文'.repeat(42), layout.caption, measure);
    assert.ok(fitted.height <= layout.caption.height);
  }
});

test('steps unfold deterministically from frames, not clock time, and captions honor gaps and tail', () => {
  const s = scene('steps');
  const frames = revealFrames(s);
  assert.equal(frames.length, 3);
  assert.ok(frames[0] < frames[1] && frames[1] < frames[2] && frames[2] < 188);
  assert.deepEqual(revealFrames(s), frames);
  assert.equal(captionAt(s, 0)?.text, '字'.repeat(42));
  assert.equal(captionAt(s, 89)?.text, '字'.repeat(42));
  assert.equal(captionAt(s, 90), undefined);
  assert.equal(captionAt(s, 93), undefined);
  assert.equal(captionAt(s, 94)?.text, '第二句');
  assert.equal(captionAt(s, 188), undefined);
  assert.equal(captionAt(s, 199), undefined);
});

test('local Chinese serif headings and sans body stacks need no font network', () => {
  assert.match(theme.headingFont, /Songti SC|Noto Serif CJK SC/);
  assert.match(theme.headingFont, /serif/);
  assert.match(theme.bodyFont, /PingFang SC|Noto Sans CJK SC/);
  assert.match(theme.bodyFont, /sans-serif/);
});
