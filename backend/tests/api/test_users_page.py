"""用户页（D137）：角色中文、停用态、新建/编辑表单。"""

from __future__ import annotations

from app.models import User


async def test_users_page_lists_roles_and_status(session, client):
    session.add_all(
        [
            User(username="alice", display_name="爱丽丝", role="admin"),
            User(username="bob", display_name="鲍勃", role="engineer"),
            User(username="carol", role="viewer", is_active=False),
        ]
    )
    await session.commit()

    page = await client.get("/users")

    assert page.status_code == 200
    text = page.text
    assert "3 用户 · 1 管理员 · 1 工程师 · 1 只读" in text
    assert "管理员" in text
    assert "工程师" in text
    assert "只读" in text
    assert "停用" in text
    assert "新建用户" in text
    assert 'action="/users"' in text
    assert "编辑" in text


async def test_create_user_via_page(session, client):
    response = await client.post(
        "/users",
        data={
            "username": "newbie",
            "password": "pw-123456",
            "display_name": "新同事",
            "role": "viewer",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    page = await client.get("/users")
    assert "newbie" in page.text
    assert "新同事" in page.text
    assert "只读" in page.text


async def test_invalid_role_shows_error(session, client):
    user = User(username="target", role="engineer")
    session.add(user)
    await session.commit()

    response = await client.post(
        f"/users/{user.id}",
        data={
            "role": "superuser",
            "is_active": "true",
            "display_name": "目标",
            "password": "",
        },
    )

    assert response.status_code == 422
    assert "未知角色" in response.text
    assert "target" in response.text


async def test_engineer_cannot_open_users_page(session, client, login_as):
    login_as("engineer")

    response = await client.get("/users")

    assert response.status_code == 403
