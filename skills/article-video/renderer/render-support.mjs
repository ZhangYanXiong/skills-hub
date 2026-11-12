import {createHash} from 'node:crypto';
import {lstat, mkdtemp, open, readdir, readFile, realpath, rename, rm, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {tsImport} from 'tsx/esm/api';

const rendererDir = path.dirname(fileURLToPath(import.meta.url));
const outputNames = ['video.mp4', 'cover.png', 'index.html'];
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');

function checkScale(scale) {
  if (!Number.isFinite(scale) || scale <= 0 || scale > 1 ||
    !Number.isInteger(1080 * scale) || !Number.isInteger(1920 * scale) ||
    (1080 * scale) % 2 || (1920 * scale) % 2) {
    throw new Error('--scale must be > 0 and <= 1 and produce integral even H264 dimensions (for example 0.25 or 0.5)');
  }
}

export function parseArgs(args) {
  const values = {};
  for (let i = 0; i < args.length; i += 2) {
    const key = args[i];
    if (!['--project', '--scale'].includes(key) || key in values || !args[i + 1] || args[i + 1].startsWith('--')) {
      throw new Error('Usage: node render.mjs --project ABS_BUILD_DIR [--scale 0.25]');
    }
    values[key] = args[i + 1];
  }
  if (!values['--project'] || !path.isAbsolute(values['--project'])) throw new Error('--project must be an absolute build directory');
  const scale = values['--scale'] === undefined ? 1 : Number(values['--scale']);
  checkScale(scale);
  return {project: values['--project'], scale};
}

export function rendererOptions(env = process.env) {
  const options = {};
  if (env.REMOTION_BROWSER_EXECUTABLE) options.browserExecutable = env.REMOTION_BROWSER_EXECUTABLE;
  if (env.REMOTION_LICENSE_KEY) options.licenseKey = env.REMOTION_LICENSE_KEY;
  return options;
}

/**
 * 为交付校验提供稳定 SHA-256，绑定排序后的 POSIX 路径与文件字节摘要。
 * 包含 src/**、根目录 render*.mjs、package.json、package-lock.json、tsconfig.json。
 * 不包含测试、node_modules、缓存、打包产物、视频或平台字体。
 */
export async function codeFingerprint(root = rendererDir) {
  const names = [];
  async function walk(directory, prefix) {
    for (const entry of await readdir(directory, {withFileTypes: true})) {
      if (['node_modules', '.cache', '.remotion', '__pycache__', '.git', '.DS_Store'].includes(entry.name)) continue;
      const name = prefix + entry.name;
      if (entry.isSymbolicLink()) throw new Error(`Renderer code symlink is not allowed: ${name}`);
      if (entry.isDirectory()) await walk(path.join(directory, entry.name), `${name}/`);
      else if (entry.isFile()) names.push(name);
    }
  }
  await walk(path.join(root, 'src'), 'src/');
  for (const entry of await readdir(root, {withFileTypes: true})) {
    if (/^render.*\.mjs$/.test(entry.name) || ['package.json', 'package-lock.json', 'tsconfig.json'].includes(entry.name)) {
      if (!entry.isFile()) throw new Error(`Renderer fingerprint input must be a regular file: ${entry.name}`);
      names.push(entry.name);
    }
  }
  for (const required of ['render.mjs', 'render-support.mjs', 'package.json', 'package-lock.json', 'tsconfig.json']) {
    if (!names.includes(required)) throw new Error(`Missing renderer fingerprint input: ${required}`);
  }
  const manifest = [];
  for (const name of names.sort()) manifest.push([name, sha256(await readFile(path.join(root, name)))]);
  return sha256(JSON.stringify(manifest));
}

const escapeHtml = (text) => String(text).replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));

export function createPlayerHtml(timeline, scale) {
  const title = escapeHtml(timeline.title);
  const mode = escapeHtml(timeline.mode);
  const duration = (timeline.durationInFrames / timeline.fps).toFixed(2);
  const voice = timeline.mode === 'demo-local'
    ? '本地演示配音（macOS say）；仅验收本地流水线，不是 Azure 在线音色成品。'
    : 'Azure 预设音色配音；仅支持已批准的预设音色，不支持声音克隆，未核实配音服务账单。';
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title} · 文章视频</title><style>
:root{color-scheme:light;font-family:"PingFang SC","Microsoft YaHei",sans-serif;color:#173D33;background:#F6F2E9}
*{box-sizing:border-box}body{margin:0}main{max-width:1000px;margin:0 auto;padding:40px 24px;display:grid;grid-template-columns:minmax(0,420px) minmax(0,1fr);gap:40px}
h1{font-family:"Songti SC","Noto Serif CJK SC",serif;font-size:32px;line-height:1.35;overflow-wrap:anywhere}p{line-height:1.7}video{width:100%;height:auto;max-height:82vh;background:#173D33;border-radius:12px;display:block}section{min-width:0}dt{font-weight:600}dd{margin:6px 0 20px}#status{border-left:3px solid #B74A22;padding:8px 12px;overflow-wrap:anywhere}a{color:inherit}:focus-visible{outline:3px solid #B74A22;outline-offset:4px}
@media(max-width:700px){main{grid-template-columns:1fr;gap:24px;padding:24px 20px}video{max-height:72vh}}
</style></head><body><main><section aria-label="视频播放器"><video id="video" controls playsinline preload="metadata" poster="cover.png" src="video.mp4">浏览器无法播放此视频，请使用支持 H.264/AAC 的播放器。</video>
<p id="status" role="status" aria-live="polite">视频在本地加载；点击播放器开始播放。</p><noscript>JavaScript 已禁用，错误诊断不可用；仍可使用原生播放器或下载 MP4。</noscript></section>
<section><p>ARTICLE VIDEO / 本地交付</p><h1>${title}</h1><dl><dt>当前模式</dt><dd>${mode}</dd><dt>时长与规格</dt><dd>${duration} 秒 · ${1080 * scale} × ${1920 * scale} · 30 fps · H.264 / AAC</dd><dt>音色限制</dt><dd>${voice}</dd></dl>
${scale !== 1 ? '<p><strong>缩放测试文件，不是 1080 × 1920 发布成品。</strong></p>' : ''}
<p><a href="video.mp4" download>下载 MP4</a> · <a href="cover.png" download>下载封面</a></p><p>字幕按分句音频边界生成，不是 ASR 或逐字对齐。右侧与底部留白为项目保守布局约定。</p></section></main>
<script>
const video=document.getElementById('video');const status=document.getElementById('status');
const reasons={1:'播放被中止',2:'网络或本地文件读取失败',3:'视频解码失败',4:'文件不存在或浏览器不支持 H.264/AAC'};
video.addEventListener('error',()=>{const code=video.error?.code||0;status.textContent='播放错误 ['+code+']：'+(reasons[code]||'未知错误')+'。请确认 video.mp4 与 index.html 位于同一目录，尝试本地 HTTP 服务或桌面播放器。';console.error('Local video playback error',code,video.error?.message||'');});
video.addEventListener('loadedmetadata',()=>{status.textContent='视频已加载，点击播放。实际时长 '+video.duration.toFixed(2)+' 秒。';});
video.addEventListener('playing',()=>{status.textContent='正在播放。';});
video.addEventListener('pause',()=>{if(!video.ended&&!video.error)status.textContent='已暂停，点击播放继续。';});
video.addEventListener('ended',()=>{status.textContent='播放结束。';});
</script></body></html>\n`;
}

async function checkPublicFiles(directory) {
  for (const entry of await readdir(directory, {withFileTypes: true})) {
    const filename = path.join(directory, entry.name);
    if (entry.isSymbolicLink()) throw new Error(`Public directory symlink is not allowed: ${filename}`);
    if (entry.isDirectory()) await checkPublicFiles(filename);
    else if (!entry.isFile()) throw new Error(`Public asset must be a regular file: ${filename}`);
  }
}

async function checkAudioFiles(project, timeline) {
  for (const scene of timeline.scenes) for (const caption of scene.captions) {
    const filename = path.join(project, caption.audio);
    if (!(await lstat(filename)).isFile()) throw new Error(`audio must be a regular file: ${caption.audio}`);
    if (sha256(await readFile(filename)) !== caption.audioSha256) throw new Error(`audio SHA-256 mismatch: ${caption.audio}`);
  }
}

async function removeDeliveries(project) {
  // 只移除产物文件（包括旧符号链接），不递归删除用户目录。
  for (const file of [...outputNames, 'render-receipt.json']) await rm(path.join(project, file), {force: true});
}

/** backend 替换只用于本地边界测试；默认调用安装的 Remotion 4.0.543 API。 */
export async function renderProject(project, scale = 1, backend, env = process.env) {
  if (!path.isAbsolute(project)) throw new Error('--project must be absolute');
  checkScale(scale);
  project = await realpath(project);
  if (!(await lstat(project)).isDirectory()) throw new Error('--project must be a directory');
  // 防止将源码和依赖打包为公开资源，包括构建目录包含源码目录的情况。
  const relativeSource = path.relative(project, rendererDir);
  if (relativeSource === '' || (!relativeSource.startsWith(`..${path.sep}`) && relativeSource !== '..' && !path.isAbsolute(relativeSource))) {
    throw new Error('Build project must not contain the renderer source directory');
  }
  const lockPath = path.join(project, '.render-lock');
  let lock;
  try {lock = await open(lockPath, 'wx');} catch (error) {
    if (error.code === 'EEXIST') throw new Error('Render already active or stale .render-lock exists; confirm no renderer is running before removing the lock');
    throw error;
  }
  let stage;
  try {
    await lock.writeFile(String(process.pid));
    await removeDeliveries(project); // 即使输入校验失败，也不能把旧视频和回执当作新交付。
    await checkPublicFiles(project);
    const timelineBytes = await readFile(path.join(project, 'timeline.json'));
    const {validateTimeline} = await tsImport('./src/contracts.ts', import.meta.url);
    const timeline = validateTimeline(JSON.parse(timelineBytes.toString('utf8')));
    await checkAudioFiles(project, timeline);
    const timelineSha256 = sha256(timelineBytes);
    const rendererSha256 = await codeFingerprint();
    stage = await mkdtemp(path.join(tmpdir(), 'article-video-render-'));
    if (!backend) backend = {...await import('@remotion/bundler'), ...await import('@remotion/renderer')};
    const serveUrl = await backend.bundle({entryPoint: path.join(rendererDir, 'src/index.ts'), publicDir: project,
      outDir: path.join(stage, 'bundle'), rootDir: rendererDir, enableCaching: false});
    const inputProps = {timeline};
    const options = rendererOptions(env);
    const browser = options.browserExecutable ? {browserExecutable: options.browserExecutable} : {};
    const composition = await backend.selectComposition({serveUrl, id: 'ArticleVideo', inputProps, ...browser});
    if (composition.width !== 1080 || composition.height !== 1920 || composition.fps !== 30 || composition.durationInFrames !== timeline.durationInFrames) {
      throw new Error('Selected composition dimensions/fps/duration do not match timeline');
    }
    await backend.renderMedia({composition, serveUrl, inputProps, codec: 'h264', audioCodec: 'aac', pixelFormat: 'yuv420p',
      colorSpace: 'bt709', enforceAudioTrack: true, outputLocation: path.join(stage, 'video.mp4'), scale, concurrency: 2, ...options});
    const firstScene = timeline.scenes[0];
    const frame = Math.max(0, firstScene.durationInFrames - 13);
    await backend.renderStill({composition, serveUrl, inputProps, imageFormat: 'png', output: path.join(stage, 'cover.png'), frame, scale, ...options});
    await writeFile(path.join(stage, 'index.html'), createPlayerHtml(timeline, scale));
    await checkPublicFiles(project);
    if (sha256(await readFile(path.join(project, 'timeline.json'))) !== timelineSha256 || await codeFingerprint() !== rendererSha256) {
      throw new Error('Timeline or renderer source changed while rendering; delivery invalidated');
    }
    await checkAudioFiles(project, timeline);
    const outputs = {};
    for (const filename of outputNames) {
      const bytes = await readFile(path.join(stage, filename));
      if (bytes.length === 0) throw new Error(`Empty rendered output: ${filename}`);
      outputs[filename] = sha256(bytes);
    }
    const receipt = {timelineSha256, rendererSha256, outputs, scale, width: 1080 * scale, height: 1920 * scale, fps: 30};
    // 回执最后落地；只有部分产物的构建不能视为通过验收的交付。
    await writeFile(path.join(stage, 'render-receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
    for (const filename of [...outputNames, 'render-receipt.json']) {
      // tmpdir 可能跨文件系统；先写项目内临时文件，再原子重命名。
      const temp = path.join(project, `.render-${filename}.tmp`);
      const handle = await open(temp, 'wx');
      try {await handle.writeFile(await readFile(path.join(stage, filename)));} finally {await handle.close();}
      await rename(temp, path.join(project, filename));
    }
    return receipt;
  } catch (error) {
    await removeDeliveries(project);
    throw error;
  } finally {
    if (stage) await rm(stage, {recursive: true, force: true});
    for (const name of [...outputNames, 'render-receipt.json']) await rm(path.join(project, `.render-${name}.tmp`), {force: true});
    await lock.close();
    await rm(lockPath, {force: true});
  }
}
