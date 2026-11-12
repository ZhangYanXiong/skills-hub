import type {Scene} from './contracts';

export type TextBox = {
  x: number; y: number; width: number; height: number; text: string;
  fontSize: number; minFontSize: number; maxLines: number; lineHeight: number;
};
export type FitOptions = Pick<TextBox, 'width' | 'fontSize' | 'minFontSize' | 'maxLines' | 'lineHeight'>;
export type MeasureText = (text: string, fontSize: number) => number;

/** 按整条候选文本测量字宽并逐字换行，包含字距和实际回退字体的影响。 */
export function fitText(text: string, options: FitOptions, measure: MeasureText) {
  const {width, minFontSize, maxLines, lineHeight} = options;
  if (!(width > 0 && minFontSize > 0 && options.fontSize >= minFontSize && maxLines > 0 && lineHeight > 0)) {
    throw new Error('Invalid text fit dimensions');
  }
  // 预留 2px 容纳字形伸出，不裁切或静默截断文本。
  for (let fontSize = options.fontSize; fontSize >= minFontSize; fontSize--) {
    const lines: string[] = [];
    let current = '';
    let fits = true;
    for (const glyph of Array.from(text)) {
      if (measure(glyph, fontSize) > width - 2) {fits = false; break;}
      if (current && measure(current + glyph, fontSize) > width - 2) {lines.push(current); current = '';}
      current += glyph;
    }
    if (current) lines.push(current);
    if (fits && lines.length <= maxLines) return {fontSize, lines, height: lines.length * fontSize * lineHeight};
  }
  throw new Error(`Text cannot fit width ${width} in ${maxLines} lines at minimum font size ${minFontSize}`);
}

export function layoutFor(scene: Scene) {
  const title: TextBox = {x: 72, y: 284, width: 828, height: 204, text: scene.title,
    fontSize: scene.kind === 'hook' ? 86 : 74, minFontSize: 58, maxLines: 2, lineHeight: 1.15};
  const starts = {hook: 578, points: 556, steps: 556, compare: 600, summary: 590};
  const gaps = {hook: 206, points: 216, steps: 216, compare: 282, summary: 206};
  const items: TextBox[] = scene.body.map((text, index) => ({
    x: 148, y: starts[scene.kind] + index * gaps[scene.kind], width: 728, height: 174,
    text, fontSize: 42, minFontSize: 36, maxLines: 3, lineHeight: 1.32,
  }));
  const caption: TextBox = {x: 96, y: 1280, width: 780, height: 150, text: '',
    fontSize: 38, minFontSize: 30, maxLines: 3, lineHeight: 1.3};
  return {title, items, caption};
}

export function revealFrames(scene: Scene) {
  // 按口播帧数分配出现时机；短场景也要在尾部留白前显示全部内容。
  const spoken = scene.durationInFrames - 12;
  return scene.body.map((_, index) => Math.floor((spoken - 1) * index / scene.body.length));
}

export function captionAt(scene: Scene, frame: number) {
  return scene.captions.find((caption) => frame >= caption.from && frame < caption.from + caption.durationInFrames);
}
