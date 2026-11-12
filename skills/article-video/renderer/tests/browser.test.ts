import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {openBrowser} from '@remotion/renderer';
import {SceneView} from '../src/ArticleVideo';
import {fitText, layoutFor} from '../src/layout';
import {theme} from '../src/theme';
import type {Scene} from '../src/contracts';
import {createPlayerHtml} from '../render-support.mjs';

// Opt-in local browser only. Never download a browser or request remote fonts during tests.
const executable = process.env.REMOTION_BROWSER_EXECUTABLE;

test('播放器提示响应真实 DOM 的播放、暂停、恢复和结束事件', {skip: !executable}, async () => {
  const browser = await openBrowser('chrome', {browserExecutable: executable, logLevel: 'error'});
  try {
    const page = await browser.newPage({context: () => null, logLevel: 'error', indent: false, pageIndex: 0, onBrowserLog: null, onLog: () => {}});
    // 此测试只验证生产事件处理器；媒体加载与解码另有真实编码和预览验收。
    const html = createPlayerHtml({title: '暂停回归', mode: 'demo-local', fps: 30, durationInFrames: 3600}, 1)
      .replace('poster="cover.png" src="video.mp4"', '');
    await page.goto({url: 'data:text/html;charset=utf-8,' + encodeURIComponent(html), timeout: 30000});
    const statuses = await page.evaluate(() => {
      const video = document.querySelector('video')!;
      const status = document.getElementById('status')!;
      return ['playing', 'pause', 'playing', 'ended'].map((name) => {
        video.dispatchEvent(new Event(name));
        return status.textContent;
      });
    });
    assert.deepEqual(statuses, ['正在播放。', '已暂停，点击播放继续。', '正在播放。', '播放结束。']);
  } finally {await browser.close({silent: true});}
});

test('local Chromium measures max-length Chinese/Latin text and checks rendered DOM overflow and safe zones', {skip: !executable}, async () => {
  const browser = await openBrowser('chrome', {browserExecutable: executable, logLevel: 'error'});
  try {
    const page = await browser.newPage({context: () => null, logLevel: 'error', indent: false, pageIndex: 0, onBrowserLog: null, onLog: () => {}});
    await page.setViewport({width: 1080, height: 1920, deviceScaleFactor: 1});
    await page._client().send('Network.enable');
    // Chromium supports this command; Remotion's intentionally narrow CDP declaration omits it.
    const client = page._client();
    await (client.send as unknown as (method: string, params: unknown) => Promise<unknown>)('Network.setBlockedURLs', {urls: ['http://*', 'https://*']});
    for (const kind of ['hook', 'points', 'steps', 'compare', 'summary'] as const) {
      const scene: Scene = {id: 'test', kind, title: '文'.repeat(24), body: ['文'.repeat(46), 'W'.repeat(46), '混合 English ' + '文'.repeat(25)].slice(0, kind === 'compare' ? 2 : 3), from: 0, durationInFrames: 102,
        captions: [{text: '文'.repeat(42), from: 0, durationInFrames: 90, audio: 'audio/a.wav', audioSha256: 'a'.repeat(64)}]};
      const layout = layoutFor(scene);
      const markup = renderToStaticMarkup(React.createElement(SceneView, {scene, articleTitle: '文'.repeat(32), frame: 80}));
      const html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"></head><body style="margin:0"><div id="frame" style="position:relative;width:1080px;height:1920px">' + markup + '</div></body></html>';
      await page.goto({url: 'data:text/html;charset=utf-8,' + encodeURIComponent(html), timeout: 30000});
      const result = await page.evaluate(async (serialized) => {
        const data = JSON.parse(serialized);
        await document.fonts.ready;
        // This is our pure already-transpiled fit function, not input article code.
        const realFit = (0, eval)('(' + data.fit + ')');
        const context = document.createElement('canvas').getContext('2d')!;
        const fits = data.boxes.map((box: {text: string; maxLines: number; height: number; width: number}, index: number) => {
          const family = index === 0 ? data.headingFont : data.bodyFont;
          const weight = index === 0 ? 700 : 500;
          const fitted = realFit(box.text, box, (text: string, size: number) => {context.font = `${weight} ${size}px ${family}`; return context.measureText(text).width;});
          return {lines: fitted.lines.length, height: fitted.height, maxLines: box.maxLines, maxHeight: box.height, width: box.width,
            sameText: fitted.lines.join('') === box.text,
            widths: fitted.lines.map((text: string) => {context.font = `${weight} ${fitted.fontSize}px ${family}`; return context.measureText(text).width;})};
        });
        const blocks = Array.from(document.querySelectorAll<HTMLElement>('[data-text-block]')).map((element) => {
          const rect = element.getBoundingClientRect();
          return {name: element.dataset.textBlock, left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
            overflow: element.scrollWidth > element.clientWidth || element.scrollHeight > element.clientHeight,
            fontFamily: getComputedStyle(element).fontFamily};
        });
        const decorations = Array.from(document.querySelectorAll<HTMLElement>('[data-item] > div:first-child, [data-subtitle] > div:first-child')).map((element) => {
          const r = element.getBoundingClientRect(); return {left: r.left, right: r.right, top: r.top, bottom: r.bottom};
        });
        return {fits, blocks, decorations};
      }, JSON.stringify({fit: fitText.toString(), boxes: [layout.title, ...layout.items, {...layout.caption, text: '文'.repeat(42)}], headingFont: theme.headingFont, bodyFont: theme.bodyFont}));
      for (const fitted of result.fits) {
        assert.ok(fitted.sameText);
        assert.ok(fitted.lines <= fitted.maxLines && fitted.height <= fitted.maxHeight, kind);
        assert.ok(fitted.widths.every((width: number) => width <= fitted.width), kind);
      }
      for (const block of result.blocks) {
        assert.ok(!block.overflow, `${kind}: ${block.name} actual browser overflow`);
        assert.ok(block.left >= 72 && block.right <= 900 && block.top >= 200 && block.bottom <= 1440, `${kind}: ${block.name} safe bounds`);
        if (block.name?.startsWith('body')) assert.ok(block.bottom < 1240, `${kind}: subtitle/body separation`);
        if (block.name === 'title') assert.match(block.fontFamily, /Songti SC|Noto Serif CJK SC/);
      }
      for (const rect of result.decorations) assert.ok(rect.left >= 72 && rect.right <= 900 && rect.bottom <= 1440, `${kind}: card border overflows safe area (${JSON.stringify(rect)})`);
    }
  } finally {await browser.close({silent: true});}
});
