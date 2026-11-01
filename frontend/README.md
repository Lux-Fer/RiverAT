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
- **离线优先**：不引用 CDN。要引入第三方库（HTMX / Alpine / Chart.js），把文件
  vendor 到 `static/vendor/` 并在模板里用 `/static/vendor/xxx.js` 引用。
- **模板引用**：后端通过 `app/web/templates.py` 的 `templates` 单例渲染，不要在页面
  模块里各自创建 `Jinja2Templates`。
- **部署**：Dockerfile 会 `COPY frontend ./frontend`，镜像里路径与仓库一致。

## 还没落地的部分

D32 定了 HTMX + Alpine.js + Chart.js，但当前页面都是"表单 POST + 跳转"，
执行中的轮询用整页 `meta refresh`。等出现"局部刷新 / 图表"的真实需求时再 vendor，
避免引入没人用的依赖。
