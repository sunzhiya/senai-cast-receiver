# -*- coding: utf-8 -*-
"""Windows 上的杜比 / 高清解码能力检测。

边界先说清：Dolby Atmos/Vision 是授权技术，第三方软件做不了它的解码。
能做的是：检测系统装没装杜比组件和 HEVC/AV1/VP9 扩展、判断当前播放引擎
能不能吃到系统解码链、缺什么就给商店/设置的跳转路径。
真要杜比生效：系统装 Dolby Access + 用 --backend windows 启动。
"""
import os
import subprocess

# 已知的"关键组件"关键字 -> 显示名 / 说明 / 商店或设置入口
KNOWN = [
    ('DolbyAccess', '杜比全景声(Dolby Access)',
     '提供系统级 Dolby Atmos 空间音效。装上后在「设置系统声音空间音效」'
     '选“Dolby Atmos for headphones/扬声器”，本软件播放即可吃到。',
     'ms-windows-store://search/?query=Dolby%20Access'),
    ('DolbyAtmos', '杜比全景声(Dolby Atmos)',
     '系统级空间音效组件。', 'ms-windows-store://search/?query=Dolby%20Atmos'),
    ('DolbyVision', '杜比视界扩展(Dolby Vision)',
     '让系统解码器支持杜比视界片源；装了 HEVC 扩展后 Dolby Vision 内容才能正常出画面。',
     'ms-windows-store://search/?query=Dolby%20Vision'),
    ('HEVC', 'HEVC 视频扩展(H.265)',
     '系统 H.265 解码器。爱优腾/哔哩哔哩的高码率 4K 片源多为 HEVC，'
     '缺它会出现"有声无画"或降级到低码率。',
     'ms-windows-store://search/?query=HEVC%20Video%20Extensions'),
    ('AV1', 'AV1 视频扩展',
     '新一代编码，B站/YouTube 4K 常用。', 'ms-windows-store://search/?query=AV1%20Video%20Extension'),
    ('VP9', 'VP9 视频扩展',
     'Google 系 4K 片源常用。', 'ms-windows-store://search/?query=VP9%20Video%20Extensions'),
]

_PS = (
    "$p = Get-AppxPackage | Where-Object { $_.Name -match 'Dolby|HEVC|AV1|VP9|VideoExtension' } "
    "| Select-Object -ExpandProperty Name -Unique; "
    "$p | ForEach-Object { $_ }"
)


def _run_ps(script, timeout=30):
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        raw = subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
            capture_output=True, timeout=timeout, startupinfo=si,
            stdin=subprocess.DEVNULL).stdout or b''
    except Exception:
        return []
    # PowerShell 在中文 Windows 下输出 GBK，按 utf-8 忽略解码即可（包名全是 ASCII）
    out = raw.decode('utf-8', errors='ignore')
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def scan_installed():
    """扫描本机已安装的杜比/高清解码相关组件，返回组件名列表。"""
    return _run_ps(_PS)


def current_backend():
    return os.environ.get('QT_MEDIA_BACKEND', 'ffmpeg')


def build_report():
    """生成可读报告：{'lines': [...], 'items': [(显示名, 状态, 说明, 链接)], 'backend': str}"""
    installed = scan_installed()
    joined = ' | '.join(installed)
    items = []
    for key, title, desc, link in KNOWN:
        hit = any(key.lower() in n.lower() for n in installed)
        # DolbyAccess / DolbyAtmos 只要装了任一即视为杜比音频可用
        if key in ('DolbyAccess', 'DolbyAtmos'):
            hit = any('dolby' in n.lower() for n in installed)
        items.append((title, '已安装 [OK]' if hit else '未安装 [X]', desc, link))
    backend = current_backend()
    lines = ['播放引擎: %s' % (
        'windows（Media Foundation 原生管道 —— 会调用系统 HEVC/杜比视界扩展并走硬件解码）'
        if backend == 'windows' else
        'ffmpeg（内置解码器，格式覆盖广含 m3u8；不吃系统杜比/HEVC 扩展）')]
    lines.append('检测到系统组件: %s' % (joined or '（无）'))
    return {'lines': lines, 'items': items, 'backend': backend,
            'installed': installed}


def advice_text(report):
    """按检测结果给出可执行建议（真实可操作，不画饼）。"""
    backend = report['backend']
    ins = ' '.join(report['installed']).lower()
    tips = []
    if 'dolby' not in ins:
        tips.append('未装系统杜比组件：点下方「打开商店」装 Dolby Access，'
                    '装完到「设置系统声音空间音效」选 Dolby Atmos，'
                    '本软件（无需改动）播放的音频即会经过杜比处理。')
    else:
        tips.append('已装杜比组件：请确认「设置系统声音空间音效」里当前输出设备'
                    '选中的是 Dolby Atmos，否则不会生效。')
    if 'hevc' not in ins:
        tips.append('未装 HEVC 视频扩展：4K/高码率片源可能不出画面或被降级。'
                    '装它（商店搜索 "HEVC Video Extensions"）后，'
                    '并用 --backend windows 启动本软件才能调用。')
    if backend != 'windows':
        tips.append('当前是 ffmpeg 引擎：不会调用系统杜比视界/HEVC 扩展。'
                    '想要吃系统解码链，请关闭本软件后用 '
                    '"python main.py --backend windows" 启动（快捷方式可加该参数）。')
    else:
        tips.append('当前已是 windows 引擎：系统 HEVC / 杜比视界扩展与硬件解码会自动生效。')
    return tips
