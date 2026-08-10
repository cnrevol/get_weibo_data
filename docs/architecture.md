# Weibo CDP Crawler Architecture

本文档总结当前程序的代码架构、实现方式、功能模块、处理流程和能力边界。

## 1. 目标

本工程用于采集微博账号主页中当前登录账号有权限访问、且微博前端接口实际返回的数据。

核心目标：

- 复用真实 Chrome 登录态。
- 通过 CDP 监听页面请求和 JSON 响应。
- 从主页流中提取微博。
- 对微博补抓全文。
- 对微博抓取评论。
- 保存结构化数据和原始 JSON，便于后续清洗和审计。

非目标：

- 不绕过微博权限、验证码、付费、隐藏或平台限制。
- 不保证抓取任意账号的全部历史微博。
- 不保证抓取平台没有返回给当前登录态的数据。

## 2. 目录结构

```text
.
├── README.md
├── requirements.txt
├── scripts/
│   ├── start_chrome.ps1
│   └── run_crawler.ps1
├── weibo_cdp_crawler/
│   ├── __init__.py
│   ├── cli.py
│   ├── crawler.py
│   ├── dates.py
│   ├── extractors.py
│   └── storage.py
└── docs/
    └── architecture.md
```

## 3. 启动脚本

### `scripts/start_chrome.ps1`

职责：

- 查找本机 Chrome。
- 使用独立 profile 目录启动 Chrome。
- 打开 CDP 端口。
- 默认打开微博首页。

默认参数：

```text
Port=9222
ProfileDir=.\chrome-profile
```

启动后用户需要手动登录微博，并打开目标博主主页。

### `scripts/run_crawler.ps1`

职责：

- 创建 `.venv`。
- 安装 `requirements.txt`。
- 调用 Python CLI：

```text
python -m weibo_cdp_crawler.cli
```

## 4. Python 模块职责

### `cli.py`

命令行入口。

职责：

- 定义命令行参数。
- 解析时间范围参数。
- 初始化日志。
- 构造 `CrawlerConfig`。
- 启动 `WeiboCdpCrawler`。

主要参数：

```text
--cdp
--out
--max-posts
--month
--since
--until
--scroll-rounds
--scroll-delay
--max-comments-per-post
--comment-delay
--comment-pages
--skip-comments
--no-fetch-fulltext
--verbose
```

### `crawler.py`

核心采集控制器。

主要对象：

```python
CrawlerConfig
WeiboCdpCrawler
```

职责：

- 连接 Chrome CDP。
- 选择当前微博页面。
- 注册网络响应监听器。
- 控制主页滚动。
- 调用抽取器解析微博和评论。
- 按时间范围过滤微博。
- 补抓微博全文。
- 抓取评论。
- 调用存储层写入 SQLite、JSONL 和原始 JSON。

### `extractors.py`

数据抽取和规范化模块。

职责：

- 遍历微博接口返回的嵌套 JSON。
- 识别微博对象。
- 识别评论对象。
- 清理 HTML 文本。
- 标准化微博字段。
- 标准化评论字段。
- 从全文接口响应中提取 `longTextContent`。
- 根据 URL 粗略分类响应类型。

主要输出：

```text
post dict
comment dict
```

### `dates.py`

时间解析和时间范围过滤模块。

职责：

- 解析 `--month`。
- 解析 `--since` / `--until`。
- 构造半开时间区间 `[start, end)`。
- 解析微博时间字符串。

支持示例：

```text
2026-07
2026年7月
2024-01-15
2026-07-17 12:34
今天 09:10
昨天 21:30
5分钟前
2小时前
```

### `storage.py`

持久化模块。

职责：

- 初始化 SQLite schema。
- 执行 schema migration。
- 保存采集 run。
- 保存微博。
- 保存评论。
- 保存原始接口响应。
- 输出 `posts.jsonl` 和 `comments.jsonl`。

存储策略：

- `posts.post_id` 是微博主键。
- `comments.comment_id` 是评论主键。
- `raw_responses.sha256` 去重保存原始 JSON。
- 微博补全文时采用补丁式更新，避免全文更新覆盖发布时间、作者、转评赞等已有字段。

## 5. 主处理流程

整体流程：

```text
start_chrome.ps1
    ↓
用户手动登录微博并打开目标主页
    ↓
run_crawler.ps1
    ↓
cli.py 解析参数
    ↓
crawler.py 连接 Chrome CDP
    ↓
等待用户确认当前页面
    ↓
注册 response 监听器
    ↓
滚动主页
    ↓
监听并解析微博列表 JSON
    ↓
按时间范围过滤
    ↓
保存 posts
    ↓
补抓 full_text
    ↓
抓取 comments
    ↓
保存 SQLite / JSONL / raw JSON
```

## 6. 网络采集方式

程序不直接解析页面 DOM。

当前主要依赖两类数据来源：

1. 浏览器页面滚动触发的微博接口响应。
2. 程序直接请求的全文和评论接口。

### 主页微博

主页微博来自浏览器实际收到的 JSON 响应。

程序监听所有微博相关响应：

```python
page.on("response", ...)
```

对响应做基本过滤：

- URL 包含 `weibo`。
- content-type 类似 JSON / JavaScript / text。
- 响应体可以解析为 JSON。

随后调用：

```python
extract_posts(payload, url)
```

### 全文补抓

对已保存微博，程序尝试用 `post_id` 和 `mblogid` 请求全文接口。

当前尝试：

```text
https://weibo.com/ajax/statuses/longtext?id={id}
https://m.weibo.cn/statuses/extend?id={id}
```

如果返回中存在明确全文字段，例如 `longTextContent`，则写入：

```text
posts.full_text
posts.text
posts.text_source = full_text
posts.fulltext_raw_json
```

### 评论抓取

优先直接请求网页端评论接口：

```text
https://weibo.com/ajax/statuses/buildComments
```

核心参数：

```text
id
uid
count
max_id
fetch_level
locale
```

如果直接接口没有抓到评论，程序会尝试打开微博详情页，通过页面响应监听做兜底抓取。

## 7. 时间范围处理

命令示例：

```powershell
.\scripts\run_crawler.ps1 --month 2026-07 --max-posts 500
```

```powershell
.\scripts\run_crawler.ps1 --since 2024-01 --until 2025-02 --max-posts 5000
```

内部使用半开区间：

```text
[start, end)
```

示例：

```text
--month 2026-07
=> [2026-07-01, 2026-08-01)

--since 2024-01 --until 2025-02
=> [2024-01-01, 2025-03-01)
```

处理逻辑：

- 每条微博先解析 `created_at`。
- 成功解析后写入 `created_at_iso`。
- 如果设置了时间范围，只保存范围内微博。
- 日志会显示：

```text
saved_posts
seen_posts
in_range
newer
older
unknown_date
```

这些指标用于判断：

- 页面是否还在返回新微博。
- 当前微博是否都比目标区间新。
- 是否已经滚过目标区间。
- 是否时间解析失败。

## 8. SQLite 数据模型

### `runs`

记录每次采集任务。

主要字段：

```text
run_id
started_at
target_url
config_json
status
```

### `posts`

微博主表。

关键字段：

```text
post_id
mblogid
user_id
screen_name
created_at
created_at_iso
list_text
full_text
text
text_source
is_long_text
source
reposts_count
comments_count
attitudes_count
detail_url
source_url
raw_json
fulltext_raw_json
first_seen_at
updated_at
```

字段说明：

- `list_text`：主页/列表接口返回文本，可能是缩略文。
- `full_text`：全文接口补抓文本。
- `text`：推荐分析字段，有全文则等于全文，否则使用 `list_text`。
- `text_source`：`full_text` 或 `list`。
- `raw_json`：列表/卡片原始 JSON。
- `fulltext_raw_json`：全文接口原始 JSON。

### `comments`

评论主表。

关键字段：

```text
comment_id
post_id
root_id
parent_id
user_id
screen_name
created_at
text
like_count
source
source_url
raw_json
first_seen_at
updated_at
```

### `raw_responses`

原始接口响应索引表。

关键字段：

```text
response_id
run_id
captured_at
kind
url
sha256
body_path
```

原始 JSON 文件保存在：

```text
raw_responses/
```

## 9. 输出文件

每次采集输出目录包含：

```text
weibo.sqlite
posts.jsonl
comments.jsonl
raw_responses/
run.log
```

SQLite 可能产生：

```text
weibo.sqlite-wal
weibo.sqlite-shm
```

这是 SQLite WAL 模式的正常文件。打开数据库时选择 `weibo.sqlite`。

## 10. 完整性和停止条件

程序当前依赖主页滚动触发更多微博接口。

停止条件包括：

- `saved_posts >= max_posts`
- 达到 `scroll_rounds`
- `seen_posts` 连续多轮不增长
- 已抓到范围内微博后，又看到足够多早于起始时间的微博

需要注意：

- 如果主页接口只返回最近半年，程序不能抓到更早微博。
- 如果博主或平台限制主页展示范围，程序不能绕过。
- 如果接口不再返回下一页，继续滚动无效。

## 11. 当前能力边界

当前程序可以作为通用主页可见数据采集器。

能抓：

- 当前登录账号有权限访问的数据。
- 目标主页滚动过程中接口实际返回的数据。
- 能通过全文接口补到的微博全文。
- 能通过评论接口返回的评论。

不能保证：

- 任意账号全部历史微博。
- 平台不向当前登录态返回的数据。
- 被博主隐藏、删除、限制展示的数据。
- 所有评论楼中楼都完整返回。

## 12. 后续可增强方向

优先级较高的增强：

1. 主页分页接口直接续爬  
   解析主页接口下一页参数，不只依赖滚动。

2. 完整性报告  
   输出最早微博时间、最新微博时间、停止原因、接口页数、过滤统计。

3. 多入口补采  
   使用微博搜索按用户和月份补采，再按 `post_id` 去重合并。

4. 评论楼中楼增强  
   对评论回复单独分页抓取。

5. 导出工具  
   从 SQLite 导出清洗后的 CSV / Parquet。
