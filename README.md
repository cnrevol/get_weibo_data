# Weibo CDP Crawler

一个基于 Chrome DevTools Protocol 的微博采集工程。

目标流程：

1. 启动带 CDP 端口的 Chrome。
2. 手动登录微博。
3. 手动打开要采集的账号主页。
4. 在终端启动爬虫并确认开始。
5. 程序监听页面 JSON 响应、自动滚动主页、提取微博列表。
6. 程序用登录态补抓微博全文。
7. 程序尝试用登录态请求评论接口，并把原始 JSON 与结构化数据落盘。

## 合规边界

只采集当前登录账号有权限访问的内容。不要绕过验证码、权限、付费内容或访问控制。评论数据包含个人信息，后续共享和处理前需要按你的组织规则脱敏或审批。

## 安装

Windows PowerShell：

```powershell
.\scripts\run_crawler.ps1 --help
```

脚本会自动创建 `.venv` 并安装依赖。

## 使用

1. 启动 Chrome：

```powershell
.\scripts\start_chrome.ps1
```

2. 在打开的 Chrome 中登录微博，并进入目标账号主页。

3. 启动采集：

```powershell
.\scripts\run_crawler.ps1 --out data\weibo_run --max-posts 100 --max-comments-per-post 200
```

4. 终端提示后确认目标页面无误，输入回车开始。

## 输出

默认输出目录包含：

- `weibo.sqlite`：结构化 SQLite 数据库。
- `posts.jsonl`：规范化微博，一行一条。
- `comments.jsonl`：规范化评论，一行一条。
- `raw_responses/`：浏览器监听到的原始 JSON 响应。
- `run.log`：运行日志。

SQLite 表：

- `runs`：每次采集任务。
- `posts`：微博正文、作者、时间、互动数、原始 JSON。
- `comments`：评论内容、评论人、时间、点赞数、原始 JSON。
- `raw_responses`：原始接口响应文件索引。

SQLite 运行时可能同时出现这些文件：

- `weibo.sqlite`：主数据库文件。
- `weibo.sqlite-wal`：SQLite write-ahead log，写前日志。程序运行中或连接未完全 checkpoint 时会存在。
- `weibo.sqlite-shm`：SQLite WAL 共享内存索引文件。

打开数据库时选择 `weibo.sqlite`。不要只复制一个 `weibo.sqlite` 文件做备份；如果程序刚跑完且 `-wal/-shm` 仍存在，先关闭所有数据库工具，或把三个文件一起复制。

## 常用参数

```powershell
.\scripts\run_crawler.ps1 `
  --cdp http://127.0.0.1:9222 `
  --out data\account_a `
  --max-posts 300 `
  --scroll-rounds 120 `
  --max-comments-per-post 500 `
  --comment-delay 2.0
```

默认会补抓微博全文。字段含义：

- `posts.list_text`：账号主页/列表接口返回的正文，可能是缩略文。
- `posts.full_text`：详情/长文接口补抓到的全文。
- `posts.text`：分析推荐使用字段。若存在全文，则等于 `full_text`；否则回退为 `list_text`。
- `posts.text_source`：`full_text` 或 `list`。
- `posts.is_long_text`：是否疑似长微博。
- `posts.raw_json`：列表/详情卡片原始 JSON。
- `posts.fulltext_raw_json`：全文接口原始 JSON。

如果只想快速抓列表，不补全文：

```powershell
.\scripts\run_crawler.ps1 --out data\quick --max-posts 100 --no-fetch-fulltext
```

## 注意

- 程序优先保存原始 JSON，再做字段抽取。后续接口变化时，可以基于 `raw_responses/` 重新清洗。
- 如果评论接口请求失败，程序会继续保留已经抓到的微博和原始响应。
- 如果微博页面要求验证码或重新登录，需要在 Chrome 里手动处理后重新运行。
