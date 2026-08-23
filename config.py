"""config.py — 配置读写（JSON，纯标准库）。"""
import json
import os

DEFAULTS = {
    # 游戏定位
    "game_title": "电子木鱼",
    "game_process": "ElectronicWoodfish.exe",
    # 挂机刷功德（点击木鱼 / 键盘输入 note.ms）
    "farm_enabled": True,
    "farm_method": "click",
    "notems_url": "https://note.ms/muyu",
    "idle_threshold_seconds": 30,
    "click_interval_ms": 60,
    "clicks_per_burst": 15,
    "fish_center_rel": [112, 152],
    # 宝箱自动化
    "box_enabled": True,
    "box_check_interval_seconds": 3,
    "box_wait_after_open_seconds": 6.0,
    "box_settle_ms": 600,
    "box_icon_region": [0.68, 0.38, 0.92, 0.62],
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
