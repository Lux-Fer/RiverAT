"""v1.1：模型配置、产品注册、工具上传/审核（M1 + M2）。"""

from __future__ import annotations

import io
import json
import tarfile


def _tool_bundle(name: str = "login_smoke", version: str = "1.0.0") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        manifest = {
            "name": name,
            "version": version,
            "description": "登录冒烟",
            "entrypoint": {"linux": ["sh", "main.sh"]},
            "input_schema": {
                "type": "object",
                "properties": {"base_url": {"type": "string"}},
                "required": ["base_url"],
            },
            "output_schema": {"type": "object", "properties": {"cases": {"type": "array"}}},
        }
        data = json.dumps(manifest).encode()
        info = tarfile.TarInfo("tool.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

        script = b'echo "ok"\n'
        info = tarfile.TarInfo("main.sh")
        info.size = len(script)
        tar.addfile(info, io.BytesIO(script))
    return buffer.getvalue()


async def test_llm_config_saved_and_key_hidden(session, client):
    saved = await client.put(
        "/api/v1/llm-config",
        json={
            "base_url": "http://127.0.0.1:9/v1",
            "model": "test-model",
            "api_key": "sk-secret-value",
        },
    )
    assert saved.status_code == 200, saved.text

    config = (await client.get("/api/v1/llm-config")).json()
    assert config["configured"] is True
    assert config["source"] == "database"
    assert config["has_key"] is True
    assert "sk-secret-value" not in json.dumps(config)


async def test_llm_test_connection_reports_failure_fast(session, client):
    await client.put(
        "/api/v1/llm-config",
        json={"base_url": "http://127.0.0.1:9/v1", "model": "m", "api_key": "x"},
    )

    result = (await client.post("/api/v1/llm-config/test")).json()

    assert result["ok"] is False
    assert result["model"] == "m"


async def test_llm_config_rejects_bad_base_url(session, client):
    response = await client.put(
        "/api/v1/llm-config", json={"base_url": "ftp://x", "model": "m"}
    )
    assert response.status_code == 422


async def test_work_product_create_and_list(session, client):
    created = await client.post(
        "/api/v1/work-products",
        json={
            "code": "DEMO",
            "name": "演示产品",
            "base_url": "http://10.0.0.5:8080",
            "ci_provider": "jenkins",
            "ci_webhook_url": "http://ci/hook",
            "ci_secret": "s3cret",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["code"] == "DEMO"
    assert body["has_ci_secret"] is True
    assert "s3cret" not in created.text

    listed = (await client.get("/api/v1/work-products")).json()
    assert [item["code"] for item in listed] == ["DEMO"]


async def test_work_product_duplicate_and_bad_code(session, client):
    await client.post("/api/v1/work-products", json={"code": "DEMO", "name": "A"})

    duplicate = await client.post(
        "/api/v1/work-products", json={"code": "DEMO", "name": "B"}
    )
    assert duplicate.status_code == 422

    bad = await client.post("/api/v1/work-products", json={"code": "带空格 的", "name": "C"})
    assert bad.status_code == 422


async def test_viewer_cannot_register_product(session, client, login_as):
    login_as("viewer")
    response = await client.post(
        "/api/v1/work-products", json={"code": "X-1", "name": "只读"}
    )
    assert response.status_code == 403


async def test_tool_upload_pending_then_approved(session, client):
    uploaded = await client.post(
        "/api/v1/tools",
        files={"file": ("tool.tar.gz", _tool_bundle(), "application/gzip")},
    )
    assert uploaded.status_code == 201, uploaded.text
    tool = uploaded.json()
    assert tool["status"] == "pending"
    assert tool["name"] == "login_smoke"

    approved = await client.post(f"/api/v1/tools/{tool['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    listed = (await client.get("/api/v1/tools?status_filter=approved")).json()
    assert [item["name"] for item in listed] == ["login_smoke"]


async def test_tool_upload_rejects_bad_package(session, client):
    broken = await client.post(
        "/api/v1/tools",
        files={"file": ("bad.tar.gz", b"not a tarball", "application/gzip")},
    )
    assert broken.status_code == 422

    duplicate = _tool_bundle()
    assert (
        await client.post(
            "/api/v1/tools",
            files={"file": ("a.tar.gz", duplicate, "application/gzip")},
        )
    ).status_code == 201
    assert (
        await client.post(
            "/api/v1/tools",
            files={"file": ("b.tar.gz", duplicate, "application/gzip")},
        )
    ).status_code == 422


async def test_tools_page_and_product_page(session, client):
    product_page = await client.get("/products")
    assert product_page.status_code == 200
    assert "注册产品" in product_page.text

    tools_page = await client.get("/tools")
    assert tools_page.status_code == 200
    assert "上传工具包" in tools_page.text
