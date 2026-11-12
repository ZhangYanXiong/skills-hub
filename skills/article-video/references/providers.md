# 在线配音与凭据

## 首版：Azure Speech REST

- 预设普通话音色默认 `zh-CN-XiaoxiaoNeural`，也可选择账号地区实际支持的 `zh-CN-YunxiNeural` 等中文预设音色；不支持声音克隆或自定义模型。
- `AZURE_SPEECH_KEY` 保存在进程环境；不要把它复制到文章、项目JSON、截图、聊天或 git。程序 doctor 只显示是否已配置。
- `AZURE_SPEECH_REGION` 为公共Azure地区标识；请求只拼接 `https://<region>.tts.speech.microsoft.com/cognitiveservices/v1`。首版没有中国区/政府云端点适配。
- 每个旁白分句独立请求，使用XML库转义为SSML、24kHz/16bit/mono PCM WAV。音色自然度和分句停顿需实际听取，REST不返回逐字时间戳。

## 批次授权

用户确认分镜不等于确认外发或费用。制作前展示服务商、地区、音色、完整旁白、估算单位数、账号单价和费用范围。按用户确认的每百万计费单位价格计算；代码将SSML标记也计入字符作保守估算，但这是估算，不承诺与账单完全相同。服务商额度/预算需要在账号配置，程序不能给出账单硬上限。

`approve` 写当前方案和设置的指纹，`audio` 在网络前核对。方案任一内容改变，需要重新授权。`--confirmed` 表达已经取得用户批准，不是允许Agent自己批准收费的快捷方式。

网络失败、401、429、坏WAV不会静默降级或自动重试。请求前记录 `requested` 状态；状态未完整完成时，下次停止，避免重复收费。先核对账号账单，再由用户决定是否清理对应缓存重新生成。不要为了“测试修复”自动重发实际文章。

## 显式本地演示

`audio --provider demo-local --voice Tingting` 使用 macOS `say`，无需在线凭据。用途是验证时间轴、字幕和渲染，产物全程标记 demo-local。其他平台没有say时明确失败；正常请求没有API密钥时不默认走这个分支。

## 官方参考

- [Azure REST API](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech)
- [语言与音色支持](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts)
- [Speech价格](https://azure.microsoft.com/pricing/details/cognitive-services/speech-services/)

2026-11-12查阅接口文档。账号价格、地区可用性和实际在线质量仍需在首次正式制作时验证。
