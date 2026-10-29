"""测试机注册接口：凭据只进不出。"""

from __future__ import annotations

import os

import pytest


def _spec() -> tuple[str, int, str, str] | None:
    raw = os.environ.get("RIVERAT_TEST_SSH")
    if not raw:
        return None
    host, port, user, password = raw.split(":", 3)
    return host, int(port), user, password


async def _create_host(
    client,
    name: str = "dummy",
    hostname: str = "10.0.0.9",
    port: int = 22,
    username: str = "tester",
    password: str = "not-a-real-password",
) -> dict:
    response = await client.post(
        "/api/v1/hosts",
        json={
            "name": name,
            "hostname": hostname,
            "port": port,
            "username": username,
            "password": password,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_host_creation_never_returns_secret(session, client):
    host = await _create_host(client)

    assert set(host) >= {"id", "name", "hostname", "port", "username", "status"}
    assert "password" not in host
    assert "secret" not in str(host).lower()


async def test_duplicate_host_name_is_rejected(session, client):
    await _create_host(client, "dup")
    response = await client.post(
        "/api/v1/hosts",
        json={
            "name": "dup",
            "hostname": "10.0.0.10",
            "username": "tester",
            "password": "x",
        },
    )
    assert response.status_code == 422


async def test_key_auth_is_not_supported_yet(session, client):
    response = await client.post(
        "/api/v1/hosts",
        json={
            "name": "keyed",
            "hostname": "10.0.0.1",
            "username": "root",
            "password": "x",
            "auth_type": "key",
        },
    )
    assert response.status_code == 422


async def test_probe_unknown_host_returns_404(session, client):
    response = await client.post(
        "/api/v1/hosts/00000000-0000-0000-0000-000000000000/probe"
    )
    assert response.status_code == 404


@pytest.mark.skipif(_spec() is None, reason="需要 RIVERAT_TEST_SSH 指向真实 sshd")
async def test_probe_updates_status_to_online(session, client):
    spec = _spec()
    assert spec is not None
    host, port, user, password = spec
    created = await _create_host(
        client, "probe-me", hostname=host, port=port, username=user, password=password
    )

    response = await client.post(f"/api/v1/hosts/{created['id']}/probe")

    assert response.status_code == 200, response.text
    assert response.json()["os"] == "linux"

    listing = await client.get("/api/v1/hosts")
    statuses = {item["name"]: item["status"] for item in listing.json()}
    assert statuses["probe-me"] == "online"
