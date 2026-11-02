# frontend/

RiverAT 的所有前端资源都在这里，后端目录（`backend/app`）里不放任何 HTML/CSS/JS。

```
frontend/
├── templates/        # Jinja2 模板（服务端渲染）
│   ├── base.html     # 布局、导航、CSS 引用
│   ├── login.html
│   ├── runs.html / run_detail.html
│   ├── products.html / product_detail.html / version_detail.html
│   ├── plans.html / plan_detail.html
│   ├── dashboard.html
│   ├── users.html
│   └── forbidden.html
└── static/           # 静态资源，挂载到 /static
    └── app.css
```

## 约定

- **没有 Node 构建**：模板由后端 Jinja2 直接渲染；静态资源原样挂载（D32）。
- **离线优先**：不引用 CDN。第三方库放 `static/vendor/`，模板里用 `/static/vendor/xxx.js` 引用。
  已 vendor：
  | 文件 | 版本 | 用在哪 |
  |---|---|---|
  | `htmx.min.js` | 2.0.4 | `base.html` 全局引入；run 详情轮询 |
  | `chart.umd.min.js` | 4.4.7 | 仅 `dashboard.html` 引入，画 14 天趋势 |
- **模板引用**：后端通过 `app/web/templates.py` 的 `templates` 单例渲染，不要在页面
  模块里各自创建 `Jinja2Templates`。
- **部署**：Dockerfile 会 `COPY frontend ./frontend`，镜像里路径与仓库一致。

## HTMX 用法

run 详情页拆成 `run_detail.html`（外壳）+ `_run_panel.html`（片段）：

- 未结束：片段根节点带 `hx-get="/runs/{id}/panel"` + `hx-trigger="every 2s"` + `hx-swap="outerHTML"`；
- 结束后：服务端返回的片段不再带这些属性，轮询自动停止。

## 还没落地的部分

Alpine.js 仍没引入 —— 目前没有任何"需要客户端状态"的交互（展开/折叠用原生
`<details>` 就够）。等出现真实场景再 vendor，避免死代码。

