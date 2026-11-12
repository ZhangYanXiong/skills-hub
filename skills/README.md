# 技能目录

每个目录是一项独立skill，先看它的README，再按需读SKILL和代码。

| 技能 | 使用说明 | 执行规则 | 示例输入 |
| --- | --- | --- | --- |
| article-video · 文章转视频 | [README](article-video/README.md) | [SKILL](article-video/SKILL.md) | [文章](article-video/examples/article.md)、[方案](article-video/examples/plan.json) |
| wechat-mp · 公众号制作 | [README](wechat-mp/README.md) | [SKILL](wechat-mp/SKILL.md) | [示例文章](wechat-mp/examples/sample-article.md) |

## 统一职责

- README.md：给人看的使用说明和运行命令。
- SKILL.md：Agent任务路由、执行规则和交付边界。
- scripts/、renderer/：实现及所属运行依赖。
- references/：按需加载的方法或接口说明。
- examples/：可复用输入与模板，不放生成成品。
- tests/：代码回归；evals/：技能行为场景，适用时增加。

成品去[outputs](../outputs/README.md)，开发记录去[docs](../docs/README.md)。无需为没有的能力创建空文件夹；不要把依赖、临时产物或另一个skill的源码复制进来。
