# 电子木鱼自动挂机（WoodenFishAuto）

针对 Steam 挂机游戏《电子木鱼》的自动化外挂程序，纯 Python 标准库（`ctypes` + `tkinter`）实现，**零第三方依赖**，兼容 Python 3.8+。

## 功能

- **空闲检测**：用低层钩子 `WH_MOUSE_LL` / `WH_KEYBOARD_LL` 精确判断「鼠标键盘连续 30 秒无输入」。
  通过 `LLMHF_INJECTED` / `LLKHF_INJECTED` 标志位**过滤程序自己的模拟输入**，因此程序刷的功德
  不会误判成"用户已回来"；只有真实的鼠标/键盘活动才会打断空闲。
- **自动刷功德**：两种方式可单选切换——**点击木鱼**或**键盘输入 note.ms**（均已验证有效）。
  键盘方式会自动打开 note.ms、聚焦输入区并模拟打字。用户一动鼠标/键盘立即停止。

> 木鱼中心位置用配置 `fish_center_rel` 固定（已验证）；note.ms 地址用 `notems_url` 配置。
- **功德宝箱自动化**：每 30 分钟图标出现时自动完成
  `检测图标 → 打开开箱页 → 点红色「开箱」→ 等动画 → 点「下一个宝箱」→ 点「x」关闭`
  的完整流程。开箱按钮只有在功德 ≥ 1000 时才为红色，程序按颜色判断是否可开。
- **简洁面板**：启动/停止、功能开关、参数调节、实时状态与日志。

## 使用

```bash
python main.py
```

1. 保持游戏《电子木鱼》窗口在屏幕上**可见、不被遮挡**（可放在副屏）。
2. 面板中点「启动」。
3. 离开电脑 30 秒后，机器人自动开始刷功德；宝箱出现时自动开箱。
4. 回来动一下鼠标/键盘，机器人立即挂起。

## 工作原理（实测校准）

| 目标 | 特征 | 判定 |
| --- | --- | --- |
| 木鱼中心 | 固定相对坐标 `[112,152]` | 配置 `fish_center_rel`（已验证的点击点，可用动态检测回退） |
| 宝箱图标 | 橙黄色，约 19×14 px，木鱼右上角固定区域 | 静置 600ms 等"功德+1"点击特效消退后，在右上角区域(x0.68~0.92, y0.38~0.62)扫描橙黄像素 `R>150,G>80,R>B+40` |
| 开箱按钮 | 红色 `RGB(231,91,67)`，开箱页下半部 | 开箱页下半部扫描红色 `R>200,G<120,B<110,R-G>100` |
| 下一个宝箱 | 结果页底部 3 个红按钮中最右（最宽） | 按 x 间隙聚类取第 3 个 |
| x 关闭 | 开箱页右上角红色 x | 右上角区域扫描红色 |

所有按钮位置都是**运行时动态取色定位**，不写死像素坐标，窗口移动也能自适应。

## 配置

`config.json`（面板中改动会自动保存）：

- `idle_threshold_seconds`：空闲判定阈值，默认 30 秒
- `farm_method`：刷功德方式，`"click"`（点击木鱼）或 `"keyboard"`（键盘输入 note.ms）
- `notems_url`：键盘方式使用的 note.ms 地址，默认 `https://note.ms/muyu`
- `click_interval_ms`：点击/按键间隔，默认 60 毫秒
- `box_wait_after_open_seconds`：开箱动画等待时长，默认 6 秒
- `farm_enabled` / `box_enabled`：两个功能开关

## 文件结构

```
WoodenFishAuto/
├── main.py        # 入口
├── gui.py         # 面板
├── bot.py         # 机器人引擎（后台线程）
├── win32.py       # Win32 API ctypes 封装
├── config.py      # 配置读写
└── config.json    # 运行时配置
```

## 打包 exe

```bash
python -m PyInstaller --onefile --windowed --icon=icon.ico --name=WoodenFishAuto --add-data "icon.ico;." --noconfirm main.py
```

生成的单文件在 `dist/WoodenFishAuto.exe`，双击即用（`config.json` 会自动生成在 exe 同目录）。

## 许可

[MIT License](LICENSE)，可自由使用、修改、分发。

## 免责声明

仅用于个人学习与自家电脑上单机/挂机游戏的自用自动化，请自行确认不违反游戏服务条款。
