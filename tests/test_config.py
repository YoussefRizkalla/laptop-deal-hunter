"""Tests for YAML configuration loading and validation."""

from pathlib import Path

import pytest

from laptop_hunter.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_config_loads_cleanly() -> None:
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert cfg.specs.min_ram_gb == 32
    assert cfg.specs.min_ssd_gb == 1000
    assert cfg.specs.max_price_usd is None
    assert "RTX 5070" in cfg.specs.gpu_targets
    assert "RTX 5070 Ti" in cfg.specs.gpu_targets
    assert "RTX 5080" in cfg.specs.gpu_targets
    assert "RTX 4080" in cfg.specs.gpu_targets
    assert cfg.conditions.allowed == ("new", "open_box", "refurbished")
    assert cfg.conditions.non_new_price_multiplier == pytest.approx(0.90)


def test_missing_gpu_targets_raises(tmp_path: Path) -> None:
    bad_cfg = tmp_path / "bad.yaml"
    bad_cfg.write_text("specs:\n  min_ram_gb: 32\n", encoding="utf-8")
    with pytest.raises(ValueError, match="gpu_targets"):
        load_config(bad_cfg)
