export type SceneKind = 'hook' | 'points' | 'steps' | 'compare' | 'summary';
export type Caption = {text: string; from: number; durationInFrames: number; audio: string; audioSha256: string};
export type Scene = {id: string; kind: SceneKind; title: string; body: string[]; from: number; durationInFrames: number; captions: Caption[]};
export type Timeline = {version: 1; title: string; width: 1080; height: 1920; fps: 30; durationInFrames: number; plan_sha256: string; mode: 'demo-local' | 'azure'; scenes: Scene[]};

function requireValue(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`Invalid timeline: ${message}`);
}
function record(value: unknown, label: string): asserts value is Record<string, unknown> {
  requireValue(value !== null && typeof value === 'object' && !Array.isArray(value), `${label} must be an object`);
}
function integer(value: unknown, label: string, minimum = 1): asserts value is number {
  requireValue(typeof value === 'number' && Number.isSafeInteger(value) && value >= minimum, `${label} must be a safe integer >= ${minimum}`);
}
function text(value: unknown, label: string, maximum: number, meaningful = false): asserts value is string {
  requireValue(typeof value === 'string' && value.trim().length > 0, `${label} must be non-empty text`);
  requireValue(Array.from(value).length <= maximum, `${label} exceeds ${maximum} characters`);
  requireValue(!/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u.test(value), `${label} must be a single line without control characters`);
  if (meaningful) requireValue(/[\p{L}\p{N}]/u.test(value), `${label} must contain letters or numbers, not only punctuation`);
}
function hash(value: unknown, label: string) {
  requireValue(typeof value === 'string' && /^[a-f0-9]{64}$/.test(value), `${label} must be lowercase SHA-256`);
}

export function validateAudioPath(value: unknown): asserts value is string {
  requireValue(typeof value === 'string' && /^audio\/[a-zA-Z0-9_-]+\.wav$/.test(value), 'audio path must be a relative WAV inside audio/ (no URLs, escapes or absolute paths)');
}

/** 返回已校验对象，不进行类型强制转换；场景 from 为全局帧，字幕 from 为相对帧。 */
export function validateTimeline(value: unknown): Timeline {
  record(value, 'timeline');
  requireValue(value.version === 1, 'version must be 1');
  text(value.title, 'title', 32);
  requireValue(value.width === 1080 && value.height === 1920 && value.fps === 30, 'canvas must be width 1080, height 1920, fps 30');
  integer(value.durationInFrames, 'durationInFrames');
  hash(value.plan_sha256, 'plan_sha256');
  requireValue(value.mode === 'demo-local' || value.mode === 'azure', 'mode must be demo-local or azure');
  requireValue(Array.isArray(value.scenes) && value.scenes.length > 0, 'scenes must be non-empty');
  const ids = new Set<string>();
  let cursor = 0;
  for (const [index, scene] of value.scenes.entries()) {
    const label = `scenes[${index}]`;
    record(scene, label);
    requireValue(typeof scene.id === 'string' && /^[a-z0-9][a-z0-9-]{0,47}$/.test(scene.id), `${label}.id must be lowercase letters/numbers/hyphens`);
    requireValue(!ids.has(scene.id), `${label}.id must be unique (duplicate id)`); ids.add(scene.id);
    requireValue(['hook', 'points', 'steps', 'compare', 'summary'].includes(scene.kind as string), `${label}.kind is not an internal layout`);
    text(scene.title, `${label}.title`, 24);
    requireValue(Array.isArray(scene.body) && scene.body.length >= 1 && scene.body.length <= 3, `${label}.body needs 1–3 items`);
    requireValue(scene.kind !== 'compare' || scene.body.length === 2, `${label}.compare needs 2 body items`);
    requireValue(scene.kind !== 'steps' || scene.body.length >= 2, `${label}.steps needs at least 2 body items`);
    scene.body.forEach((item, bodyIndex) => text(item, `${label}.body[${bodyIndex}]`, 46));
    integer(scene.from, `${label}.from`, 0); integer(scene.durationInFrames, `${label}.durationInFrames`);
    requireValue(scene.from === cursor, `${label}.from must be continuous (expected ${cursor})`);
    requireValue(Array.isArray(scene.captions) && scene.captions.length > 0, `${label}.captions must be non-empty`);
    let captionCursor = 0;
    scene.captions.forEach((caption, captionIndex) => {
      const cl = `${label}.captions[${captionIndex}]`;
      record(caption, cl); text(caption.text, `${cl}.text`, 42, true);
      integer(caption.from, `${cl}.from`, 0); integer(caption.durationInFrames, `${cl}.durationInFrames`);
      requireValue(caption.from === captionCursor, `${cl}.from must start at 0 then have exactly 4-frame gaps`);
      validateAudioPath(caption.audio); hash(caption.audioSha256, `${cl}.audioSha256`);
      captionCursor += caption.durationInFrames + 4;
      requireValue(Number.isSafeInteger(captionCursor), `${cl}.durationInFrames sum must be a safe integer`);
    });
    requireValue(scene.durationInFrames === captionCursor - 4 + 12, `${label}.durationInFrames must end with exactly 12 tail frames`);
    cursor += scene.durationInFrames;
    requireValue(Number.isSafeInteger(cursor), 'global duration sum must be a safe integer');
  }
  requireValue(value.durationInFrames === cursor, 'durationInFrames must equal scene durations');
  return value as Timeline;
}
