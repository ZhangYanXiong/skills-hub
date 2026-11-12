import React, {useEffect, useMemo, useState} from 'react';
import {AbsoluteFill, Audio, cancelRender, continueRender, delayRender, Sequence, staticFile, useCurrentFrame} from 'remotion';
import {validateTimeline, type Scene, type Timeline} from './contracts';
import {captionAt, fitText, layoutFor, revealFrames, type TextBox} from './layout';
import {theme} from './theme';

export type ArticleVideoProps = {timeline?: Timeline};
const labels = {hook: '从问题出发', points: '关键要点', steps: '行动步骤', compare: '两面看清', summary: '带走这些'};
const easeIn = (frame: number, start = 0) => {
  const t = Math.min(1, Math.max(0, (frame - start) / 16));
  return 1 - (1 - t) ** 3;
};

function TextBlock({box, fontFamily, weight = 500, color = theme.ink, name}: {
  box: TextBox; fontFamily: string; weight?: number; color?: string; name: string;
}) {
  const fitted = useMemo(() => {
    const canvas = typeof document !== 'undefined' ? document.createElement('canvas') : null;
    const context = canvas?.getContext('2d');
    return fitText(box.text, box, (text, size) => {
      if (!context) return Array.from(text).length * size; // 仅供 SSR 保守估算；MP4 使用浏览器真实字宽。
      context.font = `${weight} ${size}px ${fontFamily}`;
      return context.measureText(text).width;
    });
  }, [box.text, box.width, box.fontSize, box.minFontSize, box.maxLines, box.lineHeight, fontFamily, weight]);
  if (fitted.height > box.height) throw new Error(`Text block ${name} exceeds its reserved height`);
  return <div data-text-block={name} style={{position: 'absolute', left: box.x, top: box.y, width: box.width,
    height: box.height, fontFamily, fontWeight: weight, fontSize: fitted.fontSize, lineHeight: box.lineHeight, color}}>
    {fitted.lines.map((line, index) => <span data-text-line="true" key={index} style={{display: 'block', whiteSpace: 'pre'}}>{line}</span>)}
  </div>;
}

/** 由帧驱动画面，同时用于 DOM 测试；内容只作为 React 转义后的纯文本。 */
export function SceneView({scene, articleTitle, frame}: {scene: Scene; articleTitle: string; frame: number}) {
  const layout = layoutFor(scene);
  const caption = captionAt(scene, frame);
  const reveals = revealFrames(scene);
  const enter = easeIn(frame);
  const isSummary = scene.kind === 'summary';
  return <div data-layout={scene.kind} style={{position: 'absolute', inset: 0, background: theme.paper, color: theme.ink}}>
    <TextBlock box={{x: 72, y: 200, width: 828, height: 34, text: articleTitle, fontSize: 24, minFontSize: 20, maxLines: 1, lineHeight: 1.3}}
      fontFamily={theme.bodyFont} name="article-title" color={theme.orange}/>
    <div style={{position: 'absolute', left: 72, top: 254, width: 64, height: 4, background: theme.orange}}/>
    <div style={{opacity: enter, transform: `translateY(${16 * (1 - enter)}px)`}}>
      <TextBlock box={layout.title} fontFamily={theme.headingFont} weight={700} name="title"/>
    </div>
    <div style={{position: 'absolute', left: 72, top: 508, fontFamily: theme.bodyFont, fontSize: 24, letterSpacing: 2, color: theme.orange}}>{labels[scene.kind]}</div>
    {layout.items.map((box, index) => {
      const reveal = easeIn(frame, reveals[index]);
      const visible = frame >= reveals[index];
      const isCompare = scene.kind === 'compare';
      const mark = isCompare ? (index === 0 ? 'A' : 'B') : scene.kind === 'summary' ? '→' : `${index + 1}`.padStart(2, '0');
      return <div key={index} data-visible={String(visible)} data-item={index} style={{opacity: visible ? reveal : 0,
        transform: `translateY(${16 * (1 - reveal)}px)`}}>
        <div style={{position: 'absolute', left: 72, top: box.y - 16, width: 828, height: box.height + 30, boxSizing: 'border-box',
          borderRadius: isCompare ? 4 : 14, background: isSummary || (isCompare && index === 1) ? theme.paleOrange : '#FFFDF8',
          borderLeft: isCompare || scene.kind === 'steps' ? `4px solid ${theme.orange}` : `1px solid ${theme.rule}`,
          borderTop: `1px solid ${theme.rule}`, borderBottom: `1px solid ${theme.rule}`, borderRight: `1px solid ${theme.rule}`}}/>
        <div style={{position: 'absolute', left: 88, top: box.y + 6, width: 44, fontFamily: theme.bodyFont,
          fontSize: 25, fontWeight: 600, color: theme.orange}}>{mark}</div>
        <TextBlock box={box} fontFamily={theme.bodyFont} name={`body-${index}`} weight={500}/>
      </div>;
    })}
    {caption && <div data-subtitle="true">
      <div style={{position: 'absolute', left: 72, top: 1256, width: 828, height: 184, boxSizing: 'border-box', borderTop: `2px solid ${theme.rule}`}}/>
      <TextBlock box={{...layout.caption, text: caption.text}} fontFamily={theme.bodyFont} weight={600} name="caption"/>
    </div>}
  </div>;
}

function ArticleScene({scene, title}: {scene: Scene; title: string}) {
  const frame = useCurrentFrame(); // Sequence 上下文使帧位置相对于 scene.from。
  return <>
    <SceneView scene={scene} articleTitle={title} frame={frame}/>
    {scene.captions.map((caption, index) => <Sequence key={index} from={caption.from} durationInFrames={caption.durationInFrames} layout="none">
      <Audio src={staticFile(caption.audio)}/>
    </Sequence>)}
  </>;
}

export function ArticleVideo({timeline: input}: ArticleVideoProps) {
  const timeline = useMemo(() => validateTimeline(input), [input]);
  const [fontHandle] = useState(() => delayRender('Waiting for local Chinese font metrics'));
  const [fontsReady, setFontsReady] = useState(false);
  useEffect(() => {
    let active = true;
    Promise.all([
      document.fonts.load(`700 74px ${theme.headingFont}`, '中文标题'),
      document.fonts.load(`500 42px ${theme.bodyFont}`, '中文正文'),
      document.fonts.ready,
    ]).then(() => {if (active) setFontsReady(true);}).catch(cancelRender);
    return () => {active = false;};
  }, []);
  useEffect(() => {if (fontsReady) continueRender(fontHandle);}, [fontsReady, fontHandle]);
  if (!fontsReady) return null;
  return <AbsoluteFill style={{background: theme.paper}}>
    {timeline.scenes.map((scene) => <Sequence key={scene.id} from={scene.from} durationInFrames={scene.durationInFrames}>
      <ArticleScene scene={scene} title={timeline.title}/>
    </Sequence>)}
  </AbsoluteFill>;
}
