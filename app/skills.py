"""本地 Skill 自动发现、解析与提示词装配管理。"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("zen_gateway.skills")


@dataclass
class SkillInfo:
    """本地技能元数据。"""
    name: str
    description: str
    path: str
    source: str  # "opencode" | "gateway"
    content: str


class SkillRegistry:
    """本地技能注册表与装配器。"""

    def __init__(self) -> None:
        self._skills: dict[str, SkillInfo] = {}
        self.reload()

    def get_search_directories(self) -> list[tuple[Path, str]]:
        """获取技能探测目录列表及其来源标识。"""
        dirs: list[tuple[Path, str]] = []

        # 1. 扫描 OpenCode 用户配置技能目录
        home = Path.home()
        opencode_skills = home / ".config" / "opencode" / "skills"
        if opencode_skills.is_dir():
            dirs.append((opencode_skills, "opencode"))

        # 2. 扫描 Zen Gateway 本地 skills 目录
        local_skills = Path(__file__).resolve().parent.parent / "skills"
        if local_skills.is_dir():
            dirs.append((local_skills, "gateway"))

        return dirs

    def reload(self) -> None:
        """重新扫描并加载所有本地技能文件。"""
        new_skills: dict[str, SkillInfo] = {}

        for base_dir, source in self.get_search_directories():
            try:
                for entry in base_dir.iterdir():
                    skill_file: Path | None = None
                    if entry.is_dir():
                        target = entry / "SKILL.md"
                        if target.is_file():
                            skill_file = target
                    elif entry.is_file() and entry.name.endswith(".md"):
                        skill_file = entry

                    if skill_file:
                        skill = self._parse_skill_file(skill_file, source, fallback_name=entry.name.replace(".md", ""))
                        if skill:
                            new_skills[skill.name] = skill
            except Exception as e:
                logger.warning("扫描技能目录 %s 失败: %s", base_dir, e)

        self._skills = new_skills
        logger.info("已加载 %s 个本地技能", len(self._skills))

    def _parse_skill_file(self, file_path: Path, source: str, fallback_name: str) -> SkillInfo | None:
        """解析 SKILL.md 的 Frontmatter 元数据及正文内容。"""
        try:
            raw_text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

        name = fallback_name
        description = ""
        body = raw_text

        # 匹配 YAML Frontmatter
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw_text, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            body = fm_match.group(2).strip()

            name_m = re.search(r"^name:\s*['\"]?(.*?)['\"]?\s*$", fm_text, re.MULTILINE)
            if name_m:
                name = name_m.group(1).strip()

            desc_m = re.search(r"^description:\s*['\"]?(.*?)['\"]?\s*$", fm_text, re.MULTILINE)
            if desc_m:
                description = desc_m.group(1).strip()
            elif "description:" in fm_text:
                # 兼容多行描述
                lines = fm_text.splitlines()
                for i, line in enumerate(lines):
                    if line.startswith("description:"):
                        remainder = line[len("description:"):].strip().strip("'\"")
                        desc_parts = [remainder] if remainder else []
                        for sub_line in lines[i + 1:]:
                            if sub_line.startswith("  ") or sub_line.startswith("\t"):
                                desc_parts.append(sub_line.strip().strip("'\""))
                            else:
                                break
                        description = " ".join(desc_parts).strip()
                        break

        if not description:
            # 提取正文第一段非标题文字作为描述
            for line in body.splitlines():
                line_s = line.strip()
                if line_s and not line_s.startswith("#"):
                    description = line_s[:120]
                    break

        return SkillInfo(
            name=name,
            description=description,
            path=str(file_path.resolve()),
            source=source,
            content=body,
        )

    def list_skills(self) -> list[dict[str, Any]]:
        """列出所有已发现技能的摘要字典。"""
        res = []
        for s in self._skills.values():
            res.append({
                "name": s.name,
                "description": s.description,
                "source": s.source,
                "path": s.path,
            })
        return res

    def get_skill(self, name: str) -> SkillInfo | None:
        """获取指定名称的技能。"""
        return self._skills.get(name)

    def format_skills_prompt(self, skill_names: list[str]) -> str:
        """将指定技能集合格式化为提示词上下文注入块。"""
        blocks = []
        for name in skill_names:
            skill = self.get_skill(name)
            if skill and skill.content:
                blocks.append(f"### Skill: {skill.name}\n{skill.content}")

        if not blocks:
            return ""

        return "[Attached Skills & Capabilities]\n" + "\n\n".join(blocks)


skill_registry = SkillRegistry()
