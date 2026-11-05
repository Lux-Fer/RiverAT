"""assistant 消息的极简 markdown。"""

from __future__ import annotations

from app.web.templates import soft_markdown


def test_soft_markdown_renders_fenced_code():
    html = str(soft_markdown("说明：\n```json\n{\"user\": \"tester\"}\n```\n确认后执行"))

    assert "<pre><code>" in html
    assert "user" in html and "tester" in html
    assert "```" not in html


def test_soft_markdown_escapes_html_and_keeps_inline():
    html = str(soft_markdown("<script>alert(1)</script> **粗体** `code`"))

    assert "&lt;script&gt;" in html
    assert "<strong>粗体</strong>" in html
    assert "<code>code</code>" in html
