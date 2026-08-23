"""config.py — 配置读写（JSON，纯标准库）。"""
import json
import os

DEFAULTS = {
    # 游戏定位
    "game_title": "电子木鱼",
    "game_process": "ElectronicWoodfish.exe",
    # 挂机刷功德
    "farm_enabled": True,
    "idle_threshold_seconds": 30,
    "type_delay_ms": 25,
    "keys_per_burst": 12,
    # 宝箱自动化
    "box_enabled": True,
    "box_check_interval_seconds": 3,
    "box_wait_after_open_seconds": 6.0,
    # 颜色判定阈值（实测校准）
    "icon_min_pixels": 20,
    "red_min_pixels": 100,
}


def load(path):
    data = dict(DEFAULTS)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data.update(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
    return data


def save(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
