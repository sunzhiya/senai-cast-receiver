# -*- coding: utf-8 -*-
"""IPTV 电视接收模块。

支持三种拉流方式：
  1. m3u8/HLS 直接地址
  2. m3u 播放列表文件（本地或 URL）
  3. 单条 HTTP/HTTPS 视频流（.mp4/.mkv/.ts 直链）

提供 IptvList 解析 m3u 文件，以及 IptvChannel 数据结构。
"""
import re
import urllib.request


class IptvChannel:
    """一条频道。"""
    __slots__ = ('name', 'url', 'group')

    def __init__(self, name='', url='', group=''):
        self.name = name
        self.url = url
        self.group = group

    def __repr__(self):
        return 'IptvChannel(%s, %s)' % (self.name, self.url[:60])


class IptvList:
    """解析 m3u / m3u8 播放列表。支持 #EXTINF 元数据。"""

    def __init__(self):
        self.channels = []
        self.title = ''

    @classmethod
    def from_file(cls, path):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception:
            return cls()
        return cls._parse(content)

    @classmethod
    def from_url(cls, url, timeout=15):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'SenAICast/1.2'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read().decode('utf-8', errors='ignore')
        except Exception:
            return cls()
        return cls._parse(content)

    @classmethod
    def _parse(cls, content):
        obj = cls()
        # 提取 #EXTM3U 里的 title
        m = re.search(r'#EXTM3U.*?tvg-name="([^"]*)"', content)
        if m:
            obj.title = m.group(1)

        lines = content.splitlines()
        ch = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith('#EXTINF'):
                # #EXTINF:-1,Channel Name  或  #EXTINF:-1 group-title="xxx",Channel Name
                m = re.search(r'group-title="([^"]*)"', line)
                group = m.group(1) if m else ''
                # 最后一个逗号后的内容是频道名
                m2 = re.search(r',(.+?)$', line)
                name = m2.group(1).strip() if m2 else ''
                ch = IptvChannel(name=name, group=group)
            elif line.startswith('#EXTM3U') or line.startswith('#EXTGRP'):
                continue
            elif not line.startswith('#'):
                # URL 行
                if ch is not None:
                    ch.url = line
                    obj.channels.append(ch)
                    ch = None
                else:
                    # 没有 EXTINF 的裸 URL
                    obj.channels.append(IptvChannel(url=line))
        return obj


def detect_iptv_url(url):
    """判断一个 URL 是不是可播的流媒体（m3u8/m3u/ts/mp4/mkv/flv/rtp/udp）。"""
    low = url.lower().split('?')[0]
    exts = ('.m3u8', '.m3u', '.ts', '.mp4', '.mkv', '.flv', '.rmvb',
            '.avi', '.mov', '.webm', '.mpg', '.mpeg', '.mpg4')
    if any(low.endswith(e) for e in exts):
        return True
    if 'udp://' in low or 'rtp://' in low or 'rtsp://' in low or 'http' in low:
        # 有 http/udp/rtp/rtsp 前缀的都算
        return True
    return False
