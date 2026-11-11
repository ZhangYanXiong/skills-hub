# 公众号 API 接入说明（L3 扩展位）

> 状态：**文档就绪，代码未实现**。当前 skill 交付模式是 L1（粘贴级）+ L2（成稿级），
> 本文档定义 L3（直发草稿箱）的接口契约，等账号具备条件后按此实现 `scripts/wx_api.py`。

---

## 0. 前置条件（缺一不可）

| 条件 | 说明 | 怎么确认 |
| --- | --- | --- |
| 已认证公众号 | 服务号或订阅号均可，但必须是**已认证**状态 | 后台「设置与开发 → 基本配置」能看到 AppID/AppSecret |
| AppID + AppSecret | 账号级凭证，泄露等于账号被接管 | 同上；AppSecret 只显示一次，注意保存 |
| IP 白名单 | 调用机器的公网出口 IP 必须加入白名单，否则报 `40164` | 后台「基本配置 → IP 白名单」 |
| 接口权限 | 草稿箱 / 素材接口需对应权限；未认证账号报 `48001` | 后台「接口权限」列表 |
| 服务器出口 IP 固定 | 家用宽带 IP 会变，白名单会失效 | 用固定公网 IP 的服务部署 |

> **凭证管理**：AppSecret 不要写进代码、不要提交仓库。约定放在 `wechat-mp/.env.local`
> （该文件不应提交到版本库），由脚本读取，绝不在对话或日志里回显。

---

### 0.1 凭证格式自查（30 秒排除「填错」）

两个值经常被搞混，**格式对不上就直接不用往下走**：

| 凭证 | 格式 | 例子（已脱敏） | 去哪看 |
| --- | --- | --- | --- |
| AppID | `wx` + 16 位 | `wx4a1b…` | 基本配置 → 开发者ID |
| AppSecret | **32 位字母数字** | `a1b2c3d4…` | 基本配置 → 开发者密码(AppSecret) |
| 公众号原始ID | `gh_` + 12 位 | `gh_9f2e…` | 是**账号标识，不是密钥**，接口用不了 |

最常见的错误是把**公众号原始ID（`gh_` 开头）当成 AppSecret** 填进去，报 `40001`。
原始ID 只是账号的展示用标识，不参与鉴权。

**如果后台「基本配置」页里根本没有「开发者密码(AppSecret)」这一项**，说明账号未认证、
没有开发者接口权限——L3 走不通，不用再试，停在 L2（手动粘贴）即可。

凭证放本地文件 `wechat-mp/.env.local`：

```
WX_APPID=wx...
WX_SECRET=<32 位 AppSecret>
```

脚本读文件，不读命令行参数——避免密钥进入 shell 历史和对话记录。

## 1. access_token

### 1.1 推荐：stable_token（不失效的稳定版）

```
POST https://api.weixin.qq.com/cgi-bin/stable_token
Content-Type: application/json

{
  "grant_type": "client_credential",
  "appid": "APPID",
  "secret": "APPSECRET",
  "force_refresh": false
}
```

返回：

```json
{ "access_token": "ACCESS_TOKEN", "expires_in": 7200 }
```

`force_refresh: false` 时，在有效期内重复调用会返回同一个 token，不会刷新掉旧 token——**这是它比 `/cgi-bin/token` 更好用的地方**，多进程并发场景不会互相踢掉。

### 1.2 传统接口

```
GET https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid=APPID&secret=APPSECRET
```

`expires_in` 为 7200 秒（2 小时），有每日调用次数上限（具体数值随账号类型变化，**需人工核实**）。

### 1.3 缓存策略（必须做）

- 本地缓存到 `.wx_cache/token.json`，记录 `access_token` 与 `expires_at`
- 提前 **300 秒**判定过期，避免边界失效
- 单实例加文件锁，防止并发刷新
- 遇到 `40001` / `42001`（token 失效）时清缓存重取一次，**只重试一次**，避免抖动

---

## 2. 图片上传（正文图 + 封面图）

正文里的图片必须换成微信域名，否则被防盗链拦截。两种素材接口：

| 接口 | 用途 | 有效期 |
| --- | --- | --- |
| `/cgi-bin/material/add_material` | **永久素材**，正文图和封面都建议用它 | 长期 |
| `/cgi-bin/media/upload` | 临时素材 | 3 天，过期正文图会挂 |

### 2.1 上传永久图片素材

```
POST https://api.weixin.qq.com/cgi-bin/material/add_material?access_token=ACCESS_TOKEN&type=image
Content-Type: multipart/form-data

media=<二进制文件>
```

返回：

```json
{
  "media_id": "MEDIA_ID",
  "url": "http://mmbiz.qpic.cn/mmbiz_jpg/xxxx/0"
}
```

- `url` 就是可以写进正文 `src` 的地址
- `media_id` 用于封面图（`thumb_media_id`）
- 图片限制：≤ 10MB，支持 bmp/png/jpeg/jpg/gif（**具体上限以官方文档为准**）
- 永久素材有总量配额，正文图建议**复用**：同一张图只上传一次

### 2.2 素材映射表（避免重复上传）

维护 `.wx_cache/media_map.json`：

```json
{
  "/abs/path/fig-1.png": {
    "media_id": "MEDIA_ID",
    "url": "http://mmbiz.qpic.cn/...",
    "sha1": "文件内容哈希",
    "uploaded_at": "2026-11-11T12:00:00+08:00"
  }
}
```

上传前先按 `sha1` 查表，命中直接复用。

---

## 3. 新增草稿

```
POST https://api.weixin.qq.com/cgi-bin/draft/add?access_token=ACCESS_TOKEN
Content-Type: application/json
```

请求体：

```json
{
  "articles": [
    {
      "article_type": "news",
      "title": "标题（≤64 字）",
      "author": "作者名",
      "digest": "摘要（≤120 字）",
      "content": "<section style=\"...\">正文 HTML</section>",
      "content_source_url": "阅读原文链接（可空）",
      "thumb_media_id": "封面图的永久素材 media_id",
      "need_open_comment": 1,
      "only_fans_can_comment": 0
    }
  ]
}
```

返回：

```json
{ "media_id": "DRAFT_MEDIA_ID" }
```

要点：

- `content` 就是 `md2wx.py` 产出的 `*.body.html` 片段，**图片 src 必须是已替换的 mmbiz 地址**
- 一次最多 8 篇（对应多图文），第一篇是头条，`thumb_media_id` 与标题规则按头条处理
- `content` 有长度上限，**具体字符数以官方为准（需人工核实）**；超过时拆篇
- `content` 是 JSON 字符串，内部的引号需要由 HTTP 客户端做 JSON 序列化，不要手动拼串

### 3.1 内容替换流程

```
1. md2wx.py  →  article.html + article.body.html
2. 解析 body 里的 <img src>：
   - 本地相对/绝对路径 → 上传 material → 拿 url
   - 已是 http(s) 非 mmbiz   → 下载后重新上传（外域图不可直接用）
   - 已是 mmbiz              → 跳过
3. 替换后得到最终 content
4. 封面图独立上传，取 media_id 作为 thumb_media_id
5. POST draft/add
```

---

## 4. 发布

草稿箱 API 只到「进草稿箱」为止。真正群发有两种路径：

| 路径 | 说明 | 建议 |
| --- | --- | --- |
| 人工发布 | 后台打开草稿，人工检查后点群发 | **默认走这条**，多一道人工闸门 |
| 接口发布 | `/cgi-bin/freepublish/submit` 异步发布 | 谨慎，发布不可撤回 |

### 4.1 接口发布（可选）

```
POST https://api.weixin.qq.com/cgi-bin/freepublish/submit?access_token=ACCESS_TOKEN

{ "media_id": "DRAFT_MEDIA_ID" }
```

返回 `publish_id`，再用 `/cgi-bin/freepublish/get` 轮询结果。发布是异步的，需要轮询。

**建议**：L3 第一版只做到「存草稿」，把群发留给人工。群发次数限制、发布不可撤回、违规责任都在账号主体，自动化收益远小于风险。

---

## 5. 常见错误码

| errcode | 含义 | 处理 |
| --- | --- | --- |
| 40001 | access_token 无效或已失效 | 清缓存重取，重试一次 |
| 40164 | 调用 IP 不在白名单 | 把出口 IP 加进白名单 |
| 48001 | api 功能未授权 | 账号未认证或接口无权限，检查账号资质 |
| 45009 | 接口调用超过限制 | 降频 + 检查是否重复上传；配额次日恢复 |
| 40007 | 无效的 media_id | media_id 不存在或已删除 |
| 44002 | POST 数据为空 | 检查 Content-Type 与请求体 |
| 45002 | content 大小超过限制 | 拆篇或压缩图片 |
| 53404 | 账号受限 | 账号被处罚，停止自动化 |

> 错误码含义随平台版本可能调整，遇到未列出的码**不要猜**，以官方文档为准。

---

## 6. 实现骨架（待补）

计划新增 `scripts/wx_api.py`，只暴露四个函数：

```python
def get_token() -> str:
    """带本地缓存与失效重试。"""

def upload_image(path: str) -> dict:
    """上传图片，返回 {media_id, url}；带 sha1 映射表复用。"""

def replace_images(html: str, base_dir: str) -> str:
    """把正文里的 <img src> 全部换成 mmbiz 地址。"""

def add_draft(title, author, digest, content_html, thumb_media_id) -> str:
    """新增草稿，返回 draft media_id。"""
```

设计原则：

- **只依赖标准库**（`urllib` + `http.client` 构造 multipart），不引入第三方 SDK
- 凭证只从环境变量读，绝不落盘到仓库
- 所有写操作先 `--dry-run` 打印将要发送的内容，确认后加 `--yes` 才真正执行
- 默认只存草稿，不自动群发

---

## 7. 什么时候不要做 L3

出现以下任一情况，就停在 L1/L2：

- 账号未认证（`48001` 会一直挡着）
- 没有固定公网 IP（白名单反复失效）
- 发布频率低（每周 1~2 篇，人工粘贴 3 分钟就完了）
- 涉及医疗、金融、教育等强监管内容（自动化放大了合规风险）

**L1/L2 的粘贴流程只多花 3 分钟，但少了一整类账号安全与合规风险。**
