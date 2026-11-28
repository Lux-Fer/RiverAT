from permissions import SKILLS_DIR, WORKSPACE
from tools.tools import tool

SKILL_MARK = "[skill]"
MAX_NOTES_CHARS = 3000

def parse_skill(text):

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip()
    meta = {}
    for i, line in enumerate(line[1:], start=1):
        if line.strip() == "---":
            return meta, "\n".join(lines[i + 1:]).strip()
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return {}, text.strip()

def discover(skills_dir=None):
    skills_dir = skills_dir or SKILLS_DIR
    found = {}
    if not skills_dir.is_dir():
        return found
    for f in sorted(skills_dir.glob("*/SKILL.md")):
        meta, _ = parse_skill(f.read_text(encoding="utf-8"))
        name = meta.get("name") or f.parent.name
        if not meta.get("description"):
            print(f"[skills]跳过{f}:缺少 description")
            continue
        found[name] = {"description": meta["description"], "path": f}
    return found

def skills_section(found=None):
    found = discover() if found is None else found
    if not found:
        return ""
    lines = [
        "", "## 可用技能",
        "下面只列出技能的名字和用途。当任务和某个技能的用途匹配时，"
        "先调用 load_skill 读取完整说明，再按说明执行。"
    ]
    lines += [f"- {n}: {s['description']}" for n, s in found.items()]
    return "\n".join(lines)

def project_notes():
    p = WORKSPACE / "AGENT.md"
    if not p.is_file():
        return ""
    text = p.read_text(encoding="utf-8")[:MAX_NOTES_CHARS]
    return f"\n\n## 项目说明（来自AGENT.md）\n{text}"

