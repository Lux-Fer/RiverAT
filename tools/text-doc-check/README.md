# text_doc_check

RiverAT 工具：检查**本地文本文档**是否存在、大小、编码、非空，以及是否包含指定文字。

## 安装

```bash
cd tools/text-doc-check
tar -czf text_doc_check-1.0.0.tar.gz tool.json main.py README.md
```

管理员在 RiverAT「工具」页上传 `text_doc_check-1.0.0.tar.gz`，审核通过后即可在手动建任务或助手里调用。

## 参数

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `path` | 是 | — | 文本文档路径；相对路径基于 `RIVERAT_DOCS_ROOT` |
| `contains` | 否 | — | 必须包含的文字 |
| `encoding` | 否 | `utf-8` | `utf-8` / `utf-8-sig` / `gbk` / `latin-1` |
| `min_chars` | 否 | `1` | 去掉首尾空白后的最少字符数 |
| `max_bytes` | 否 | `5000000` | 文件大小上限，避免误读大文件 |

## 在 RiverAT 里的路径

工具在 **worker** 所在环境执行，不是浏览器所在机器：

- Docker 部署：`backend/var/` 已挂载到容器 `/app/backend/var/`。把文档放在宿主机
  `backend/var/documents/` 下，容器内路径就是 `/app/backend/var/documents/xxx.txt`；
  也可以只传相对路径 `xxx.txt`（默认根目录是 `/app/backend/var/documents`）。
- 本地 `uvicorn/worker`：直接传绝对路径，或设置 `RIVERAT_DOCS_ROOT` 指向文档目录。

示例参数：

```json
{
  "path": "sample.txt",
  "contains": "RiverAT",
  "encoding": "utf-8",
  "min_chars": 1,
  "max_bytes": 1000000
}
```

## 输出

每个检查一条 `cases[]`：

```json
{
  "status": "passed",
  "cases": [
    {"case_id": "doc-exists", "status": "passed", "duration_ms": 0, "reason": "/app/backend/var/documents/sample.txt"},
    {"case_id": "doc-size", "status": "passed", "duration_ms": 0, "reason": "128 字节"},
    {"case_id": "doc-encoding", "status": "passed", "duration_ms": 0, "reason": "utf-8 解码通过"},
    {"case_id": "doc-min-chars", "status": "passed", "duration_ms": 0, "reason": "去空白后 32 字"},
    {"case_id": "doc-contains", "status": "passed", "duration_ms": 0, "reason": "包含「RiverAT」"}
  ]
}
```

有失败项时顶层 `status=failed`，平台会把任务标成失败并展示失败原因。

## 本地自测

```bash
echo '{"args":{"path":"/tmp/sample.txt","contains":"RiverAT"}}' | python main.py
```

## 安全

工具以 RiverAT worker 的进程权限读取文件，路径参数可以指向 worker 能访问的任意位置。
只安装可信工具，并限制 `RIVERAT_DOCS_ROOT` 指向允许的文档目录。
