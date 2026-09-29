"""测试参数完全自定义（System Prompt、超参数、Skills、MCP与Agent）功能。"""
import pytest
from app.config import config_manager, ProfileConfig
from app.ir import IRRequest
from app.skills import skill_registry
from app.transform import (
    apply_profile_to_request,
    parse_openai_request,
    parse_anthropic_request,
    resolve_model_and_skills,
)


def test_resolve_model_and_skills():
    """测试模型名称中提取技能后缀。"""
    base, skills = resolve_model_and_skills("ling-3.0-flash-fin-free")
    assert base == "ling-3.0-flash-fin-free"
    assert skills == []

    base, skills = resolve_model_and_skills("ling-3.0-flash-fin-free+codebase-memory+git")
    assert base == "ling-3.0-flash-fin-free"
    assert skills == ["codebase-memory", "git"]


def test_system_prompt_modes():
    """测试 System Prompt 的 4 种注入模式：prepend, append, override, fallback。"""
    # 1. Prepend 模式
    config_manager.config.profiles.global_profile = ProfileConfig(
        system_prompt="全局角色设定",
        system_prompt_mode="prepend",
    )
    config_manager.config.profiles.models = {}

    req = IRRequest(model="test-model", messages=[], system_prompt="用户临时人设")
    apply_profile_to_request(req)
    assert req.system_prompt == "全局角色设定\n\n用户临时人设"

    # 2. Append 模式
    config_manager.config.profiles.global_profile.system_prompt_mode = "append"
    req = IRRequest(model="test-model", messages=[], system_prompt="用户临时人设")
    apply_profile_to_request(req)
    assert req.system_prompt == "用户临时人设\n\n全局角色设定"

    # 3. Override 模式
    config_manager.config.profiles.global_profile.system_prompt_mode = "override"
    req = IRRequest(model="test-model", messages=[], system_prompt="用户临时人设")
    apply_profile_to_request(req)
    assert req.system_prompt == "全局角色设定"

    # 4. Fallback 模式（有用户人设则不覆盖）
    config_manager.config.profiles.global_profile.system_prompt_mode = "fallback"
    req = IRRequest(model="test-model", messages=[], system_prompt="用户临时人设")
    apply_profile_to_request(req)
    assert req.system_prompt == "用户临时人设"

    # Fallback 模式（无用户人设时填充）
    req_empty = IRRequest(model="test-model", messages=[], system_prompt=None)
    apply_profile_to_request(req_empty)
    assert req_empty.system_prompt == "全局角色设定"


def test_model_specific_profile_override():
    """测试模型专属 Profile 优先级高于全局 Profile。"""
    config_manager.config.profiles.global_profile = ProfileConfig(
        system_prompt="全局提示",
        temperature=0.7,
        force_hyperparams=False,
    )
    config_manager.config.profiles.models = {
        "special-model": ProfileConfig(
            system_prompt="专属提示",
            temperature=0.1,
            reasoning_effort="high",
            force_hyperparams=True,
            agent="codebase-memory",
            active_skills=["codebase-memory"],
        )
    }

    req = IRRequest(model="special-model", messages=[], temperature=0.9)
    apply_profile_to_request(req)

    assert req.system_prompt == "专属提示"
    assert req.temperature == 0.1  # 被 force 覆盖
    assert req.reasoning_effort == "high"
    assert req.agent == "codebase-memory"
    assert "codebase-memory" in req.skills


def test_skills_formatting():
    """测试已注册 Skill 格式化注入提示词。"""
    skills = skill_registry.list_skills()
    assert isinstance(skills, list)
    if skills:
        first_skill_name = skills[0]["name"]
        prompt = skill_registry.format_skills_prompt([first_skill_name])
        assert "[Attached Skills & Capabilities]" in prompt
        assert first_skill_name in prompt


def test_parse_openai_request_with_headers_and_model_suffix():
    """测试通过请求头与模型名后缀动态注入 Skills。"""
    data = {
        "model": "ling-3.0-flash-fin-free+codebase-memory",
        "messages": [{"role": "user", "content": "你好"}],
    }
    ir_req = parse_openai_request(data, header_skills=["extra-skill"])
    assert "codebase-memory" in ir_req.skills
    assert "extra-skill" in ir_req.skills


if __name__ == "__main__":
    pytest.main(["-v", __file__])
