# Weibo CDP Crawler

基于 Chrome DevTools Protocol 的微博采集工程。浏览器负责手动登录和触发页面请求，程序负责监听 JSON 响应、补抓全文、抓评论、结构化保存。

## 基本流程

1. 启动带 CDP 端口的 Chrome。
2. 手动登录微博。
3. 手动打开目标账户主页。
4. 启动采集脚本，确认当前页面后开始。
5. 程序滚动主页并抓取指定时间范围内的微博。
6. 程序补抓微博全文。
7. 程序抓取评论。
8. 保存 SQLite、JSONL、原始 JSON。

## 启动 Chrome

```powershell
.\scripts\start_chrome.ps1
```

默认参数：

```text
Port=9222
ProfileDir=.\chrome-profile
```

## 启动采集

查看全部参数：

```powershell
.\scripts\run_crawler.ps1 --help
```

当前主要参数：

```text
--cdp                      Chrome CDP 地址，默认 http://127.0.0.1:9222
--out                      输出目录，默认 data/weibo_run
--max-posts                最多保存多少条符合条件的微博，默认 100
--month                    采集单月，例如 2026-07 或 2026年7月
--since                    起始日期/月，包含，例如 2024-01、2024-01-15、2024年1月
--until                    结束日期/月，包含输入的日期或整月，例如 2025-02、2025-02-28
--scroll-rounds            最多滚动次数，默认 80
--scroll-delay             每次滚动等待秒数，默认 1.5
--max-comments-per-post    每条微博最多抓多少评论，默认 200
--comment-delay            评论请求间隔秒数，默认 2.0
--comment-pages            每条微博最多抓多少页评论，默认 50
--skip-comments            只抓微博，不抓评论
--no-fetch-fulltext        不补抓微博全文
--verbose                  输出详细日志
```

## 时间范围示例

采集 2026 年 7 月：

```powershell
.\scripts\run_crawler.ps1 --out data\weibo_2026_07 --month 2026-07 --max-posts 500
```

采集 2024 年 1 月到 2025 年 2 月：

```powershell
.\scripts\run_crawler.ps1 --out data\weibo_2024_01_to_2025_02 --since 2024-01 --until 2025-02 --max-posts 5000
```

采集 2024-01-15 到 2024-02-20：

```powershell
.\scripts\run_crawler.ps1 --out data\weibo_range --since 2024-01-15 --until 2024-02-20 --max-posts 1000
```

说明：

- `--month 2026-07` 等价于 `[2026-07-01, 2026-08-01)`。
- `--since 2024-01 --until 2025-02` 等价于 `[2024-01-01, 2025-03-01)`，包含 2025 年 2 月整月。
- `--until 2024-02-20` 会包含 2024-02-20 当天，内部等价于小于 2024-02-21。

## 输出文件

输出目录包含：

```text
weibo.sqlite
posts.jsonl
comments.jsonl
raw_responses/
run.log
```

SQLite 运行时可能同时出现：

```text
weibo.sqlite
weibo.sqlite-wal
weibo.sqlite-shm
```

`weibo.sqlite-wal` 是 SQLite 写前日志，不是异常文件。用 A5 SQL、DBeaver、SQLiteStudio 打开时选择 `weibo.sqlite`。复制备份时，如果 `-wal/-shm` 仍存在，关闭程序和数据库工具后再复制，或三个文件一起复制。

## posts 表关键字段

```text
post_id              微博 ID
mblogid              微博短 ID
user_id              作者 ID
screen_name          作者昵称
created_at           微博原始时间字符串
created_at_iso       程序解析后的标准时间，便于 SQL 过滤
list_text            主页/列表接口返回文本，可能是缩略文
full_text            全文接口补抓文本
text                 推荐分析字段；有全文用全文，否则用 list_text
text_source          full_text 或 list
is_long_text         是否疑似长微博
reposts_count        转发数
comments_count       评论数
attitudes_count      点赞数
raw_json             列表/卡片原始 JSON
fulltext_raw_json    全文接口原始 JSON
```

推荐查询：

```sql
select
  post_id,
  created_at_iso,
  screen_name,
  reposts_count,
  comments_count,
  attitudes_count,
  text_source,
  length(list_text) as list_len,
  length(full_text) as full_len,
  text
from posts
order by created_at_iso desc;
```

## 合规边界

只采集当前登录账号有权限访问的内容。不要绕过验证码、权限、付费内容或访问控制。评论数据包含个人信息，后续共享和处理前需要按组织规则脱敏或审批。
