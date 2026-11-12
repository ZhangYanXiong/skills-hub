import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {SceneView} from '../src/ArticleVideo';
import {layoutFor} from '../src/layout';
import type {Scene, SceneKind} from '../src/contracts';

function fixture(kind: SceneKind): Scene {
  return {id: 'one', kind, title: '中文知识型视频的清晰表达', body: ['第一条：把问题说明白', '第二条：把方法写具体', '第三条：留下行动方向'].slice(0, kind === 'compare' ? 2 : 3), from: 0, durationInFrames: 102,
    captions: [{text: '先从一个问题开始。', from: 0, durationInFrames: 90, audio: 'audio/a.wav', audioSha256: 'a'.repeat(64)}]};
}
function html(scene: Scene, frame: number) {
  return renderToStaticMarkup(React.createElement(SceneView, {scene, articleTitle: '文章标题', frame}));
}

test('each layout renders real text, not HTML, and the subtitles in a dedicated band', () => {
  for (const kind of ['hook', 'points', 'steps', 'compare', 'summary'] as const) {
    const s = fixture(kind);
    const markup = html(s, 80);
    assert.ok(markup.includes('data-layout="' + kind + '"'));
    const textContent = markup.replace(/<[^>]*>/g, '');
    assert.ok(textContent.includes(s.title));
    for (const text of s.body) assert.ok(textContent.includes(text));
    assert.ok(markup.includes('data-subtitle="true"'));
    assert.ok(!/animation:|transition:/.test(markup));
  }
  const s = fixture('hook'); s.body[0] = '<script>alert(1)</script>';
  assert.ok(html(s, 30).replace(/<[^>]*>/g, '').includes('&lt;script&gt;alert(1)&lt;/script&gt;'));
  assert.ok(!html(s, 30).includes('<script>'));
});

test('steps frame changes visibility; empty caption gaps/tails never show stale subtitles', () => {
  const s = fixture('steps');
  assert.notEqual(html(s, 0), html(s, 80));
  assert.equal(html(s, 80), html(s, 80));
  assert.ok(html(s, 0).includes('data-visible="false"'));
  assert.ok(!html(s, 80).includes('data-visible="false"'));
  assert.ok(!html(s, 90).includes('data-subtitle="true"'));
  assert.ok(!html(s, 101).includes('data-subtitle="true"'));
});

test('all content blocks expose bounded lines rather than clipping oversized text', () => {
  for (const kind of ['hook', 'points', 'steps', 'compare', 'summary'] as const) {
    const s = fixture(kind); s.title = '文'.repeat(24); s.body = s.body.map(() => '文'.repeat(46));
    const markup = html(s, 80);
    assert.ok(!/overflow:hidden|text-overflow:ellipsis|line-clamp/.test(markup));
    assert.ok(markup.includes('data-text-block="title"'));
    assert.equal((markup.match(/data-text-block="body/g) ?? []).length, s.body.length);
    const layout = layoutFor(s);
    assert.ok(layout.items.every((item) => item.y + item.height + 16 < 1240));
  }
});
