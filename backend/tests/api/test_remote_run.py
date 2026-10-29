"""远端执行：注册测试机 → 计划 → 在 SSH 目标上真的跑一次。

用"在目标机 /tmp 留一个标记文件"来证明执行确实发生在远端，而不是本地。
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.transport.ssh import SshTransport
from tests.plugins import make_plugin


def _spec() -> tuple[str, int, str, str] | None:
    raw = os.environ.get("RIVERAT_TEST_SSH")
    if not raw:
        return None
    host, port, user, password = raw.split(":", 3)
    return host, int(port), user, password


pytestmark = pytest.mark.skipif(_spec() is None, reason="需要 RIVERAT_TEST_SSH")


async def _create_host(client) -> dict:
    spec = _spec()
    assert spec is not None
    host, port, user, password = spec
    response = await client.post(
        "/api/v1/hosts",
        json={
            "name": "exec-target",
            "hostname": host,
            "port": port,
            "username": user,
            "password": password,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_run_executes_on_remote_host(session, client, tmp_path):
    host = await _create_host(client)

    marker = f"/tmp/riverat-proof-{uuid.uuid4().hex}"
    plugin = make_plugin(
        tmp_path,
        "marker",
        f"touch {marker}\necho remote-ok\n",
        "Write-Output 'unused'\n",
    )

    product = (
        await client.post(
            "/api/v1/products", json={"code": "REMOTE", "name": "远端产品"}
        )
    ).json()
    version = (
        await client.post(
            f"/api/v1/products/{product['id']}/versions", json={"version": "1.0.0"}
        )
    ).json()
    plan = await client.post(
        "/api/v1/plans",
        json={
            "product_version_id": version["id"],
            "name": "远端冒烟",
            "definition": {
                "nodes": [{"key": "mark", "plugin": str(plugin), "timeout": 30}]
            },
        },
    )
    assert plan.status_code == 201, plan.text

    run = await client.post(
        "/api/v1/runs",
        json={"plan_id": plan.json()["id"], "host_id": host["id"]},
    )

    assert run.status_code == 201, run.text
    body = run.json()
    assert body["status"] == "passed"
    assert body["host_id"] == host["id"]
    assert {step["node_key"]: step["status"] for step in body["steps"]} == {
        "mark": "passed"
    }

    # 证据：目标机上确实出现了标记文件（说明命令跑在远端）
    spec = _spec()
    assert spec is not None
    transport = SshTransport(
        host=spec[0], username=spec[2], port=spec[1], password=spec[3]
    )
    try:
        check = transport.exec(["sh", "-c", f"test -e {marker}; echo $?"])
        assert check.stdout_text.strip() == "0"
        transport.exec(["sh", "-c", f"rm -f {marker}"])
    finally:
        transport.close()
