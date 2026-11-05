"""工具页（D135）：待审优先、参数可见、管理员可审核。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Tool


def _tool(name: str, status: str, *, minutes: int = 0) -> Tool:
    return Tool(
        name=name,
        version="1.0.0",
        description=f"{name} 的说明",
        status=status,
        bundle_sha256="a" * 64,
        bundle_path=f"/tmp/{name}.tar.gz",
        manifest={
            "name": name,
            "version": "1.0.0",
            "entrypoint": {"linux": ["./run.sh"]},
            "input_schema": {
                "type": "object",
                "properties": {"base_url": {"type": "string"}},
                "required": ["base_url"],
            },
            "runtime": {"setup": ["echo ready"]},
        },
        created_at=datetime.now(UTC) - timedelta(minutes=minutes),
    )


async def test_tools_page_pending_first_and_actions(session, client):
    session.add_all(
        [
            _tool("approved-tool", "approved", minutes=20),
            _tool("pending-tool", "pending", minutes=5),
        ]
    )
    await session.commit()

    page = await client.get("/tools")

    assert page.status_code == 200
    text = page.text
    assert text.index("pending-tool") < text.index("approved-tool")
    assert "待审" in text
    assert "可用" in text
    assert "base_url" in text
    assert "必填 base_url" in text
    assert "环境 1 步" in text
    assert "通过" in text
    assert "拒绝" in text


async def test_viewer_tools_page_has_no_upload_or_review(session, client, login_as):
    session.add(_tool("pending-tool", "pending"))
    await session.commit()
    login_as("viewer")

    page = await client.get("/tools")

    assert page.status_code == 200
    assert "上传工具包" not in page.text
    assert 'action="/tools"' not in page.text
    assert "等 admin 审核" in page.text


async def test_tools_page_empty_state(session, client):
    page = await client.get("/tools")

    assert page.status_code == 200
    assert "还没有工具" in page.text
    assert "上传工具包" in page.text
