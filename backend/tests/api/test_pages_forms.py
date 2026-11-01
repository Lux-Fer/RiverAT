"""页面表单：建产品 / 版本 / 组成 / 计划，并点按钮跑一轮。"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Product, ProductVersion
from tests.plugins import make_plugin


async def test_static_css_is_served(client):
    response = await client.get("/static/app.css")

    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "badge" in response.text


async def _create_product(client, code: str, name: str) -> None:
    response = await client.post(
        "/products", data={"code": code, "name": name}, follow_redirects=False
    )
    assert response.status_code == 303, response.text


async def _product_id(session, code: str):
    product = await session.scalar(select(Product).where(Product.code == code))
    assert product is not None
    return product.id


async def _version_id(session, product_id, version: str):
    row = await session.scalar(
        select(ProductVersion).where(
            ProductVersion.product_id == product_id,
            ProductVersion.version == version,
        )
    )
    assert row is not None
    return row.id


async def test_create_product_and_version_via_forms(session, client):
    await _create_product(client, "WEB-A", "网页部件")
    product_id = await _product_id(session, "WEB-A")

    response = await client.post(
        f"/products/{product_id}/versions",
        data={"version": "2.0.0"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    await session.rollback()  # 读到其他请求提交的数据
    detail = await client.get(f"/products/{product_id}")
    assert detail.status_code == 200
    assert "2.0.0" in detail.text


async def test_lock_component_via_form(session, client):
    await _create_product(client, "WEB-B", "部件 B")
    await _create_product(client, "WEB-C", "组合 C")
    b_id = await _product_id(session, "WEB-B")
    c_id = await _product_id(session, "WEB-C")

    await client.post(
        f"/products/{b_id}/versions", data={"version": "1.0.0"}, follow_redirects=False
    )
    await client.post(
        f"/products/{c_id}/versions", data={"version": "1.0.0"}, follow_redirects=False
    )
    b_version = await _version_id(session, b_id, "1.0.0")
    c_version = await _version_id(session, c_id, "1.0.0")

    response = await client.post(
        f"/versions/{c_version}/components",
        data={"child_version_id": str(b_version)},
        follow_redirects=False,
    )
    assert response.status_code == 303

    detail = await client.get(f"/versions/{c_version}")
    assert "WEB-B" in detail.text


async def test_create_plan_and_run_via_forms(session, client, tmp_path):
    plugin = make_plugin(tmp_path, "ok", 'echo "ok"\n', 'Write-Output "ok"\n')
    await _create_product(client, "WEB-P", "被测产品")
    product_id = await _product_id(session, "WEB-P")
    await client.post(
        f"/products/{product_id}/versions",
        data={"version": "1.0.0"},
        follow_redirects=False,
    )
    version_id = await _version_id(session, product_id, "1.0.0")

    yaml_text = "nodes:\n" f"  - key: demo\n    plugin: {plugin}\n    timeout: 30\n"
    created = await client.post(
        "/plans",
        data={
            "product_version_id": str(version_id),
            "name": "网页计划",
            "definition": yaml_text,
        },
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    plan_url = created.headers["location"]

    plan_page = await client.get(plan_url)
    assert plan_page.status_code == 200
    assert "网页计划" in plan_page.text

    run = await client.post(
        f"{plan_url}/run", data={"host_id": ""}, follow_redirects=False
    )
    assert run.status_code == 303, run.text

    run_page = await client.get(run.headers["location"])
    assert run_page.status_code == 200
    assert 'class="badge passed"' in run_page.text
