"""测试模型持久化缓存与自动同步机制。"""
import json
import pytest
from pathlib import Path
from app.models import ModelRegistry, ModelMeta


def test_model_cache_persistence(tmp_path, monkeypatch):
    """测试模型元数据在本地缓存的保存与冷启动恢复。"""
    cache_file = tmp_path / "models_cache.json"
    monkeypatch.setattr("app.models.CACHE_FILE", cache_file)

    # 1. 模拟初始空缓存
    reg1 = ModelRegistry()
    assert len(reg1.list_models()) == 0

    # 2. 模拟写入模型并保存缓存
    reg1._models["mimo-v2.6-flash-free"] = ModelMeta(
        id="mimo-v2.6-flash-free",
        name="Mimo v2.6 Flash (Free)",
        provider="opencode",
        is_free=True,
        verification_tier="heavy",
        description="测试模型",
        context_window=128000,
        support_reasoning=True,
    )
    reg1._save_cache()

    assert cache_file.is_file()
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["id"] == "mimo-v2.6-flash-free"

    # 3. 模拟冷启动重新实例化，验证自动恢复
    reg2 = ModelRegistry()
    models = reg2.list_models()
    assert len(models) == 1
    assert models[0]["id"] == "mimo-v2.6-flash-free"
    assert models[0]["support_reasoning"] is True
