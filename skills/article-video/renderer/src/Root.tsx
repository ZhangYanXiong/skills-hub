import React from 'react';
import {Composition} from 'remotion';
import {ArticleVideo, type ArticleVideoProps} from './ArticleVideo';
import {validateTimeline} from './contracts';

export const Root = () => <Composition
  id="ArticleVideo"
  component={ArticleVideo}
  width={1080}
  height={1920}
  fps={30}
  durationInFrames={1}
  defaultProps={{} as ArticleVideoProps}
  calculateMetadata={({props}) => {
    const timeline = validateTimeline(props.timeline);
    return {width: timeline.width, height: timeline.height, fps: timeline.fps, durationInFrames: timeline.durationInFrames};
  }}
/>;
