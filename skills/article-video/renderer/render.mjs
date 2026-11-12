#!/usr/bin/env node
import {parseArgs, renderProject} from './render-support.mjs';

try {
  const {project, scale} = parseArgs(process.argv.slice(2));
  const receipt = await renderProject(project, scale);
  console.log(`Rendered ${receipt.width}x${receipt.height} ${receipt.fps}fps${scale === 1 ? '' : ' (TEST SCALE ONLY)'}`);
  console.log('video.mp4 / cover.png / index.html / render-receipt.json');
} catch (error) {
  // 不输出环境变量、许可密钥或文章正文。
  const key = process.env.REMOTION_LICENSE_KEY;
  let message = error instanceof Error ? error.message : String(error);
  if (key) message = message.split(key).join('[REDACTED LICENSE KEY]');
  console.error(`Render failed: ${message}`);
  process.exitCode = 1;
}
