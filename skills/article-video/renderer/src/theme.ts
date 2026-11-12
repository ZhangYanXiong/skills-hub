// 仅使用本地字体：macOS 使用宋体/苹方；Linux 应安装本地 Noto CJK。
// 用浏览器真实字宽决定换行；更换字体会改变像素结果，但不会取消安全区限制。
export const theme = {
  paper: '#F6F2E9', ink: '#173D33', orange: '#B74A22', paleOrange: '#F0E0D0', rule: '#D5DBD0',
  headingFont: '"Songti SC", "STSong", "Noto Serif CJK SC", "Source Han Serif SC", serif',
  bodyFont: '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif',
} as const;
