# 森投屏接收端 (CastReceiver)

一台「虚拟投屏设备」软件：让手机上 **爱奇艺 / 腾讯视频 / 优酷 / 哔哩哔哩** 等 App 自带的「投屏 / TV」按钮
能扫到这台电脑，把视频推流到电脑上播放。本质是 **DLNA/UPnP MediaRenderer 接收端**——
手机推的是视频 URL，电脑直接拉流播放，所以 **画质 = 片源画质、延迟远低于屏幕镜像**。

## 支持情况

| 来源 | 协议 | 状态 |
|------|------|------|
| 爱奇艺 / 腾讯视频 / 优酷 / 芒果 / B站 等 | DLNA/UPnP | [OK] 主通道，完整支持 |
| **华为手机 App 内视频投屏**（华为视频 / 腾讯视频 / B站 华为版等） | DLNA/UPnP | [OK] 同上，走标准 DLNA，已兼容 |
| iPhone / 部分小众投屏 App | AirPlay (mDNS 被发现 + 视频投屏) | [OK] 视频投屏可用（legacy RSA 配对 + /play 拉流）；[实验] 最新 iOS 的 method1 配对待补 |
| **IPTV 电视**（m3u/m3u8 频道列表、单条流地址） | HTTP/UDP 拉流 | [OK] 工具栏「IPTV 电视」直接拉 |
| 华为 / 安卓「无线投屏 / 多屏协同」整屏镜像 | 系统 Miracast | -> 工具栏「华为多屏协同」帮检测组件 + 一键调起系统「投影到此电脑」，不重复实现协议 |

> **关于「华为私有协议」**：华为手机在**视频 App 内部**点投屏按钮，底层就是标准 DLNA（和爱优腾一样），
> 本软件已完整兼容；华为的**屏幕镜像**（下拉菜单「无线投屏 / 多屏协同」）走的是系统级 Miracast / 华为 Cast+，
> 由 Windows 自带「无线显示」接收，本软件一键帮你打开设置入口。**华为 Cast+ 的加密视频直传通道需华为私有密钥与加密协商，
> 属于封闭协议，无法在第三方软件里重新实现**——这与 AirPlay FairPlay 同理。

## 特殊软件适配

爱优腾/B站这类主流 App 都是标准 DLNA，开箱即用。但**小众 / 冷门 App** 常有私有实现，
典型症状：扫不到设备、连上了不出画面、手机端不能暂停/拖进度、进度不回传、画质或音效不对。
这类问题基本都得**拿到它的安装包针对性逆向**才能改。

**需要适配就把安装包发给 QQ：1218563952**
直接发 `.apk` 即可，附一句现象（扫不到 / 不出画面 / 不能暂停 / 进度不回传 / 画质或音效不对）。
**适配好了会通过 QQ 回复你**，并放进后续版本。
求助前可以先自己试：换「系统解码」快捷方式启动、点「一键修复网络」后重启、手机 App 里手动切清晰度。

## 安装

依赖：Python 3.10+，PyQt6（含 QtMultimedia / QtMultimediaWidgets）、numpy（画质增强，可选）。

**方式 A：exe（最省事）**
去 [Releases](https://github.com/sunzhiya/senai-cast-receiver/releases) 下载
`森投屏接收端.exe`，双击即用，无需装 Python。

**方式 B：pip**
```
pip install senai-cast-receiver
```
装完跑一次 `senai-cast-receiver`（或 `python -m main`），**桌面会自动多出一个图标**，
以后直接双击那个图标就进 GUI，不用再敲命令。桌面图标没出现就再跑一次，或手动 `senai-cast-shortcut`。

**方式 C：源码**
```
git clone https://github.com/sunzhiya/senai-cast-receiver.git
cd senai-cast-receiver
pip install -r requirements.txt
python main.py          # 跑完桌面也会有图标
```

自己打包 exe：`pip install pyinstaller` 后 `python build_exe.py`，产物在 `dist/`。

> 早期版本用 PyQt6-WebEngine 内嵌 Chromium 播放，但其自带 Chromium **未编译 H.264/AAC**，
> 投 mp4 会直接解码失败。现已改为 **Qt6 Multimedia**（QMediaPlayer + QVideoWidget），
> 不再依赖 WebEngine。

## 使用步骤

1. 电脑与手机连到 **同一个 Wi-Fi**（路由器需关闭「AP 隔离 / 客户端隔离」）。
2. 首次运行若弹 Windows 防火墙提示，选 **允许（专用网络）**。若未弹窗或之后搜不到设备，请点击界面「一键修复网络(扫不到时点)」，在 UAC 弹窗点“是”，然后**重启软件**——它会自动添加 pythonw 的入站规则并停止系统 SSDP 服务。
3. 软件启动后，顶栏显示设备名、端口与「本机IP」下拉框，以及绿色的「自动选网」标签（显示当前选中的真实网卡名）。默认会**自动排除 VPN / 虚拟网卡**，选用真实 Wi-Fi/以太网网卡 IP（如 `192.168.1.23`）。若自动选错（极少数情况），可在「本机IP」下拉选对 IP，再点「应用并切换IP」重启服务。**软件在运行时持续监控网络变化**——你中途开关 VPN、切换 Wi-Fi、插拔网线导致真实网卡 IP 变动时，会自动热切换投屏服务（无需手动干预）。
4. 手机打开视频 App  点右上角「TV / 投屏」 选择 **「森投屏接收端」**  视频即在电脑播放。
5. 可改设备名（回车生效）、调音量、暂停/继续/停止，或点「自测」按钮验证播放器。

### IPTV 电视接收

工具栏点「**IPTV 电视**」，能：

- **输流地址**：贴一个 m3u8 / ts / mp4 直链（或 udp://、rtp://），点「打开流/列表」直接播。
- **选本地 m3u 文件**：把下载好的频道列表丢进去解析。
- **拉在线列表**：一键拉 `iptv-org` 公开的频道列表（全量 / 中文 / 新闻 / 体育 / 动漫），
  列表下来后点频道名就能播。

频道是直播流，没有进度条可拖（`SetAVTransportURI` 播直播时 `position` 一直为 0 属正常）。
拉不到的频道多半是源本身挂了或地区限制，换个频道试。

### 华为多屏协同

工具栏点「**华为多屏协同**」。华为手机投到 Windows 电脑，走的是**系统 Miracast**，
不是一个能自己实现的私有协议（华为 HiSuite / 微软 Your Phone 都是闭源客户端）。
这个按钮会帮你：检测系统装没装「无线显示器」组件 → 一键打开「投影到此电脑」
→ 启动 Windows「连接」应用等手机接入。然后华为手机下拉菜单点「无线投屏 / 多屏协同」
选这台电脑就行。

### 播放中的控制（双向同步）

| 你要的效果 | 怎么做 |
|-----------|--------|
| **暂停 / 继续** | 电脑上点工具栏「暂停」「继续」，或手机上点暂停——**双向同步**：手机点了电脑真的停，电脑点了手机界面也会显示已暂停 |
| **全屏** | 点「全屏」按钮 / **双击画面** / 按 **F11**；按 **Esc** 退出（全屏时自动隐藏工具栏与日志） |
| **拖进度条** | 手机上拖动进度条  SOAP Seek  电脑端真的跳转；电脑端实时把播放进度回传（手机进度条会走） |
| **看当前画质** | 工具栏右侧「码流」实时显示真实分辨率/帧率/码率，如 `1920x1080 · 1080P · 25 fps · 3200 kbps` |
| **画面增强** | 「画质」下拉：原画 / 生动 / 影院 / 锐利 / 柔和——逐帧处理（numpy：亮度·对比度·饱和度·非锐化掩蔽锐化） |
| **音效** | 「音效」下拉：原声 / 杜比风格·宽阔 / 影院氛围 / 人声清晰 / 夜间·轻柔——真实作用于音量映射的**增益 + 等响度补偿** |
| **争取更高码率** | 工具栏「清晰度策略」选「电视模式(争取1080P/4K)」：把设备型号声明为 4K 智能电视 + 在 GetProtocolInfo 声明 HD/4K 解码能力 + 立即重新宣告，诱导部分 App 推高码率 |

**关于「调 1080P / 4K」的说明**：DLNA 投屏的清晰度由**手机端 App 选择的片源**决定，
接收端无法凭空把 720P 变成 4K。你能做的是：① 用电视模式争取更高码率；② 在手机 App 内
手动切清晰度（投屏后 App 里通常仍有清晰度按钮）；③ 用画质增强与系统解码链提升还原度。

**关于杜比**：Dolby Atmos / Dolby Vision 是**授权技术**，第三方播放器无法凭空实现其解码。
本软件提供「杜比/高清检测」按钮，如实告诉你系统装了哪些组件（HEVC / AV1 / VP9 / Dolby Access），
并给出一键启用路径。可用的方式是：系统装了 Dolby Access，在「设置 → 系统 → 声音 → 空间音效」
选 Dolby Atmos，用 **系统解码** 快捷方式（走 Media Foundation 原生管道）启动本软件，
系统级解码与音效增强会自动作用于播放。

### 自定义背景与开屏动画

工具栏「外观」里设置，配置存到 `%APPDATA%/SenAICast/settings.json`。

- **开屏动画默认关闭**，想用就自己开：可指定背景图（**gif 会当动图播**，不填则用蓝紫渐变）、
  标题、副标题、停留时长，还能先「预览开屏动画」看效果。
- **播放器背景**：没播视频时显示，可选图片铺满或纯色（默认黑）。
- 想跳过开屏启动：`python main.py --no-splash`。

两种方式，效果一样：

- **软件内一键生成**：界面工具栏点「创建桌面快捷方式」，会生成**两个** .lnk：
  - `森投屏接收端.lnk` —— 默认引擎（ffmpeg），格式覆盖广，支持 m3u8/HLS。
  - `森投屏接收端 (系统解码·杜比).lnk` —— `--backend windows`，走系统 Media Foundation
    原生管道，可调用系统 HEVC/AV1/VP9 扩展与**硬件解码**，系统装了 Dolby 组件时音效也自动生效。
- **命令行生成**：`senai-cast-shortcut`（pip 装完自带），或 `python -m receiver.shortcut`。

### 华为手机怎么投

- **App 内视频投屏**（推荐，画质=源画质、延迟低）：华为视频 / 腾讯视频 / B站 等 App 里点「TV/投屏」 选「森投屏接收端」，走 DLNA，已兼容。
- **屏幕镜像**（把整个手机画面投到电脑）：点界面「打开无线显示(华为镜像/Miracast)」 在设置页安装“无线显示”可选功能、设为“随处可用”，
  再打开“无线显示”应用等待连接  华为手机下拉菜单点「无线投屏 / 多屏协同」选本机即可（系统级 Miracast）。

## 自测 / 验证

- 点界面「自测」：用一段公开测试视频验证本地解码与播放正常。
- 用安卓 `UPnP Browser` 等工具扫描局域网，应能看到本设备（MediaRenderer）。
- 本仓库附 5 套回归测试，可在无界面环境下验证：

| 脚本 | 验证内容 |
|------|---------|
| `test_headless.py` | DLNA 内核：device.xml、SOAP 控制、播放回调 |
| `test_upnp_compat.py` | 按真实视频 App 流程模拟（拉 SCPD / GetProtocolInfo / SetAVTransportURI） |
| `test_transport_compat.py` | 针对 Dart 系控制点的状态机（三态、RelTime、GENA `<TransportState>`，含非 Dart 对照） |
| `test_doublebind.py` | 双绑监听对照实验（证明"先关旧栈再建新栈"修复有效） |
| `test_airplay.py` | AirPlay /server-info、/info、/play、/stop |

```
python test_control.py
```

## 命令行参数

```
python main.py --name 我的电脑 --port 8200 --no-airplay --backend windows
```
- `--name`  设备显示名
- `--port`  HTTP 控制端口（默认 8200）
- `--no-airplay` 关闭 AirPlay 被发现
- `--backend` 播放引擎：`ffmpeg`（默认，格式广含 m3u8/HLS）/ `windows`（Media Foundation
  原生管道，可调用系统 HEVC / 杜比视界扩展与硬件解码）。**必须在 QApplication 创建前设置**，
  已在 `main.py` 中于启动前写入环境变量。

## 目录结构

```
cast-receiver/
├── main.py                 # 入口
├── requirements.txt
├── receiver/
│   ├── config.py           # IP / 端口配置（自动排除 VPN/虚拟网卡选真实网卡）
│   ├── netwatch.py        # 运行时网络监控（自动检测 VPN/网卡变化并热切换 IP）
│   ├── firewall.py         # Windows 防火墙规则检测
│   ├── player.py           # DLNA 事件  GUI 信号桥接（含 seek 信号）
│   ├── player_widget.py    # Qt6 Multimedia 播放器（画质增强 / 音效 / 进度 / 全屏信号）
│   ├── dolby.py            # 系统杜比 / HEVC·AV1·VP9 扩展检测与启用引导
│   ├── gui.py              # PyQt6 主窗口（工具栏 / 全屏 / 状态同步 / 日志）
│   ├── shortcut.py         # 桌面 .lnk 生成（无 COM，支持 --backend windows 变体）
│   ├── dlna/
│   │   ├── device.py       # UPnP 设备描述 XML
│   │   ├── ssdp.py         # SSDP 发现（NOTIFY + 响应 M-SEARCH）
│   │   ├── services.py     # AVTransport/RenderingControl/ConnectionManager 状态机
│   │   └── server.py       # HTTP 控制服务 + DlnaStack 封装
│   └── airplay/
│       ├── mdns.py         # AirPlay mDNS 被发现
│       └── server.py       # AirPlay 视频控制 HTTP 服务 (/play 等)
└── assets/
    └── icon.ico            # 应用图标（多尺寸，快捷方式与窗口共用）
```

## 依赖的开源项目致谢

本软件构建在以下开源项目之上（许可证见各自仓库）：

| 项目 | 用途 | 许可证 |
|------|------|--------|
| [PyQt6](https://riverbankcomputing.com) / [Qt 6](https://www.qt.io) | GUI 框架 + Qt6 Multimedia 播放（QMediaPlayer + QVideoWidget，双后端 FFmpeg / Media Foundation） | LGPL / GPL / 商业 |
| [FFmpeg](https://ffmpeg.org) | Qt 媒体后端 `ffmpegmediaplugin.dll`，负责解码与 m3u8/HLS 拉流 | LGPL/GPL |
| [NumPy](https://numpy.org) | 帧级画质增强（锐化 / 对比度 / 去色偏） | BSD-3 |
| [qrcode](https://github.com/lincolnloop/python-qrcode) + [Pillow](https://pillow.readthedocs.io) | 「手机连通性自检」页生成二维码 | BSD / MIT |
| [pylnk3](https://github.com/jonathan-s/pylnk3) | 纯 Python 生成 Windows `.lnk`（桌面快捷方式，不走 COM） | MIT |
| [cryptography](https://cryptography.io) | AirPlay legacy RSA 配对握手的加密原语 | Apache-2.0 |
| [PyInstaller](https://www.pyinstaller.org) | 打包为单文件 `.exe` | GPL |
| [Python](https://python.org) | 解释器与标准库 | PSF |

> 各库的完整许可证文本随包分发于你的 site-packages（或解压后的 dist 内），本仓库
> `LICENSE` 为 **MIT**（仅约束本仓库自身代码）。若分发商业产品，请自行核对
> Qt 的 LGPL/商业双许可与 PyInstaller 的 GPL 义务。
