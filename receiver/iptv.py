import re
import urllib.request


class IptvChannel:
    __slots__ = ('name', 'url', 'group')

    def __init__(self, name='', url='', group=''):
        self.name = name
        self.url = url
        self.group = group

    def __repr__(self):
        return 'IptvChannel(%s, %s)' % (self.name, self.url[:60])


class IptvList:

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
                m = re.search(r'group-title="([^"]*)"', line)
                group = m.group(1) if m else ''
                m2 = re.search(r',(.+?)$', line)
                name = m2.group(1).strip() if m2 else ''
                ch = IptvChannel(name=name, group=group)
            elif line.startswith('#EXTM3U') or line.startswith('#EXTGRP'):
                continue
            elif not line.startswith('#'):
                if ch is not None:
                    ch.url = line
                    obj.channels.append(ch)
                    ch = None
                else:
                    obj.channels.append(IptvChannel(url=line))
        return obj


def detect_iptv_url(url):
    low = url.lower().split('?')[0]
    exts = ('.m3u8', '.m3u', '.ts', '.mp4', '.mkv', '.flv', '.rmvb',
            '.avi', '.mov', '.webm', '.mpg', '.mpeg', '.mpg4')
    if any(low.endswith(e) for e in exts):
        return True
    if 'udp://' in low or 'rtp://' in low or 'rtsp://' in low or 'http' in low:
        return True
    return False
