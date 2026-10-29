"""Configuration loading (config.toml + env overrides)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PlayerCfg:
    name: str = ""
    tag: str = ""
    region: str = "eu"
    platform: str = "pc"


@dataclass
class HenrikCfg:
    api_key: str = ""
    base_url: str = "https://api.henrikdev.xyz"


@dataclass
class OllamaCfg:
    url: str = "http://127.0.0.1:11434"
    model: str = "qwen3.8:27b"
    temperature: float = 0.3
    num_ctx: int = 16384
    parallel: int = 4
    timeout_s: int = 300
    think: str = "off"            # "" = model default, "off", "on"


@dataclass
class CoachCfg:
    mode: str = "both"
    language: str = "English"
    playbook: str = "knowledge/playbook.yaml"
    notes_dir: str = "notes"


@dataclass
class VideoCfg:
    minimap_roi: list[float] = field(default_factory=lambda: [0.012, 0.025, 0.215, 0.382])
    killfeed_roi: list[float] = field(default_factory=lambda: [0.70, 0.08, 0.29, 0.25])
    sample_fps: float = 4.0


@dataclass
class PathsCfg:
    cache_dir: str = "data/cache"
    output_dir: str = "output"


@dataclass
class Config:
    player: PlayerCfg = field(default_factory=PlayerCfg)
    henrik: HenrikCfg = field(default_factory=HenrikCfg)
    ollama: OllamaCfg = field(default_factory=OllamaCfg)
    coach: CoachCfg = field(default_factory=CoachCfg)
    video: VideoCfg = field(default_factory=VideoCfg)
    paths: PathsCfg = field(default_factory=PathsCfg)
    root: Path = field(default_factory=Path.cwd)

    def path(self, p: str) -> Path:
        pp = Path(p)
        return pp if pp.is_absolute() else self.root / pp


def _fill(dc, data: dict):
    for k, v in (data or {}).items():
        if hasattr(dc, k):
            setattr(dc, k, v)
    return dc


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path) if path else Path.cwd() / "config.toml"
    cfg = Config(root=path.parent.resolve() if path.exists() else Path.cwd())
    if path.exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        _fill(cfg.player, raw.get("player"))
        _fill(cfg.henrik, raw.get("henrik"))
        _fill(cfg.ollama, raw.get("ollama"))
        _fill(cfg.coach, raw.get("coach"))
        _fill(cfg.video, raw.get("video"))
        _fill(cfg.paths, raw.get("paths"))
    if os.environ.get("HENRIK_API_KEY"):
        cfg.henrik.api_key = os.environ["HENRIK_API_KEY"]
    if os.environ.get("OLLAMA_URL"):
        cfg.ollama.url = os.environ["OLLAMA_URL"]
    if os.environ.get("VALCOACH_MODEL"):
        cfg.ollama.model = os.environ["VALCOACH_MODEL"]
    return cfg
