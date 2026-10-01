# -*- coding: utf-8 -*-
"""UPnP 兼容性测试：按一个自研投屏 App 实际会走的流程逐步验证接收端。

  1. SSDP M-SEARCH 发现（SearchType: upnp:rootdevice / MediaRenderer:1）
  2. 下载 LOCATION 的 device.xml，解析
     DeviceInfo(deviceType, friendlyName, manufacturer, modelName)
     ServiceInfo(serviceType, serviceId, controlURL, eventSubURL, SCPDURL)
  3. 逐个下载各服务 SCPD，校验 actionList / argumentList 完整（空壳会被判设备不可用）
  4. GetProtocolInfo 取 Source / Sink，Sink 需覆盖常见片源格式
  5. SetAVTransportURI -> Play -> GetPositionInfo 确认播放态
     （UPnP 标准：SetAVTransportURI 后为 TRANSITIONING，Play 后 PLAYING，
      Pause 后 PAUSED_PLAYBACK，Stop 后 STOPPED）
  6. RenderingControl 音量控制（SetVolume / GetVolume）
  7. 各响应体积控制在安全范围内
"""
import sys
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, '.')

from receiver.dlna.server import DlnaStack
from receiver.dlna.services import RendererState

PORT = 8301
BASE = 'http://127.0.0.1:%d' % PORT
NS = '{urn:schemas-upnp-org:device-1-0}'
SNS = '{urn:schemas-upnp-org:service-1-0}'

# 一个自研投屏 App 会调用的动作集合，接收端需全部覆盖
REQUIRED_ACTIONS = {
    'SetAVTransportURI', 'Play', 'Pause', 'Stop', 'Seek',
    'GetTransportInfo', 'GetPositionInfo', 'GetProtocolInfo',
}

LOGS = []


def get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def soap_post(url, service_type, action, body_inner=''):
    env = ('<?xml version="1.0"?>'
           '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
           '<s:Body><u:%s xmlns:u="%s">%s</u:%s></s:Body></s:Envelope>'
           % (action, service_type, body_inner, action))
    req = urllib.request.Request(
        url, data=env.encode('utf-8'),
        headers={'Content-Type': 'text/xml; charset="utf-8"',
                 'SOAPACTION': '"%s#%s"' % (service_type, action)})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read().decode('utf-8', 'ignore')


def main():
    state = RendererState()
    stack = DlnaStack('127.0.0.1', PORT, 'CompatTest', state,
                      log=lambda m: LOGS.append(m))
    stack.start()
    try:
        # ---------- device.xml ----------
        print('[1] 下载 device.xml')
        root = ET.fromstring(get(BASE + '/device.xml'))
        dev = root.find(NS + 'device')
        dtype = dev.find(NS + 'deviceType').text
        fname = dev.find(NS + 'friendlyName').text
        manu = dev.find(NS + 'manufacturer').text
        model = dev.find(NS + 'modelName').text
        print('     deviceType   =', dtype)
        print('     friendlyName =', fname)
        print('     manufacturer =', manu, '| modelName =', model)
        assert dtype == 'urn:schemas-upnp-org:device:MediaRenderer:1', 'deviceType 必须是 MediaRenderer:1'

        services = []
        for svc in dev.find(NS + 'serviceList'):
            services.append({
                'type': svc.find(NS + 'serviceType').text,
                'id': svc.find(NS + 'serviceId').text,
                'control': svc.find(NS + 'controlURL').text,
                'event': svc.find(NS + 'eventSubURL').text,
                'scpd': svc.find(NS + 'SCPDURL').text,
            })
        print('     服务数 =', len(services))
        assert any('AVTransport' in s['type'] for s in services)
        assert any('RenderingControl' in s['type'] for s in services)
        assert any('ConnectionManager' in s['type'] for s in services)

        # ---------- 逐个下载 SCPD ----------
        print('[2] 逐个下载 SCPD')
        all_actions = set()
        for s in services:
            scpd = ET.fromstring(get(BASE + s['scpd']))
            alist = scpd.find(SNS + 'actionList')
            acts = [a.find(SNS + 'name').text for a in alist]
            all_actions.update(acts)
            nargs = 0
            for a in alist:
                arglist = a.find(SNS + 'argumentList')
                nargs += len(arglist) if arglist is not None else 0
            svt = scpd.find(SNS + 'serviceStateTable')
            nsv = len(svt) if svt is not None else 0
            print('     %-28s 动作%2d 参数%2d 状态变量%2d'
                  % (s['type'].split(':')[-2], len(acts), nargs, nsv))
            assert acts, 'SCPD 无任何动作: ' + s['type']
            assert nargs > 0, 'SCPD argumentList 为空壳: ' + s['type']

        missing = REQUIRED_ACTIONS - all_actions
        print('     所需动作全覆盖检查:', 'PASS' if not missing else 'FAIL %s' % missing)
        assert not missing, '缺少动作: %s' % missing

        # ---------- GetProtocolInfo -> Source / Sink ----------
        print('[3] GetProtocolInfo -> Source / Sink')
        cm = next(s for s in services if 'ConnectionManager' in s['type'])
        resp = soap_post(BASE + cm['control'], cm['type'], 'GetProtocolInfo')
        vals = {}
        for el in ET.fromstring(resp).iter():
            tag = el.tag.split('}')[-1]
            if tag in ('Source', 'Sink'):
                vals[tag] = el.text or ''
        print('     Source 长度 =', len(vals.get('Source', '')))
        print('     Sink   长度 =', len(vals.get('Sink', '')))
        assert vals.get('Sink'), 'Sink 为空 -> 部分控制点会判 UnsupportedMedia'
        assert vals.get('Source'), 'Source 为空 -> 部分控制点会判设备无效'
        for must in ('application/vnd.apple.mpegurl', 'application/x-mpegURL', 'video/mp4'):
            assert must in vals['Sink'], 'Sink 缺少常见片源格式: ' + must
        print('     Sink 含 m3u8/mp4 等关键格式: PASS')

        # ---------- 完整播放状态机 ----------
        # UPnP 标准：SetAVTransportURI 后为 TRANSITIONING，Play 后 PLAYING，
        # Pause 后 PAUSED_PLAYBACK，Stop 后 STOPPED。
        print('[4] 完整状态机（TRANSITIONING -> PLAYING -> PAUSED_PLAYBACK -> STOPPED）')
        av = next(s for s in services if 'AVTransport' in s['type'])
        inner = ('<InstanceID>0</InstanceID>'
                 '<CurrentURI>http://example.com/a.m3u8</CurrentURI>'
                 '<CurrentURIMetaData></CurrentURIMetaData>')

        def transport_state():
            r = soap_post(BASE + av['control'], av['type'], 'GetTransportInfo',
                          '<InstanceID>0</InstanceID>')
            d = {}
            for el in ET.fromstring(r).iter():
                d[el.tag.split('}')[-1]] = el.text
            return d.get('CurrentTransportState')

        soap_post(BASE + av['control'], av['type'], 'SetAVTransportURI', inner)
        s1 = transport_state()
        print('     SetAVTransportURI 后 =', s1)
        assert s1 == 'TRANSITIONING', '应为 TRANSITIONING，实际: %s' % s1

        soap_post(BASE + av['control'], av['type'], 'Play',
                  '<InstanceID>0</InstanceID><Speed>1</Speed>')
        s2 = transport_state()
        print('     Play 后              =', s2)
        assert s2 == 'PLAYING'

        # GetPositionInfo 也必须可调，用于确认播放态
        pi = soap_post(BASE + av['control'], av['type'], 'GetPositionInfo',
                       '<InstanceID>0</InstanceID>')
        assert 'GetPositionInfoResponse' in pi, 'GetPositionInfo 响应异常'

        # Seek / Pause / Stop 逐个确认返回 200 且状态正确
        soap_post(BASE + av['control'], av['type'], 'Seek',
                  '<InstanceID>0</InstanceID><Unit>REL_TIME</Unit><Target>00:00:30</Target>')
        soap_post(BASE + av['control'], av['type'], 'Pause', '<InstanceID>0</InstanceID>')
        s3 = transport_state()
        print('     Pause 后             =', s3)
        assert s3 == 'PAUSED_PLAYBACK'
        # 暂停态再 Play 必须回到 PLAYING（不能卡住）
        soap_post(BASE + av['control'], av['type'], 'Play',
                  '<InstanceID>0</InstanceID><Speed>1</Speed>')
        assert transport_state() == 'PLAYING', '暂停后 Play 未恢复 PLAYING'
        soap_post(BASE + av['control'], av['type'], 'Stop', '<InstanceID>0</InstanceID>')
        s4 = transport_state()
        print('     Stop 后              =', s4)
        assert s4 == 'STOPPED'
        print('     状态机全流程: PASS')

        # ---------- RenderingControl 音量 ----------
        print('[5] RenderingControl 音量控制')
        rc = next(s for s in services if 'RenderingControl' in s['type'])
        soap_post(BASE + rc['control'], rc['type'], 'SetVolume',
                  '<InstanceID>0</InstanceID><Channel>Master</Channel><DesiredVolume>60</DesiredVolume>')
        gv = soap_post(BASE + rc['control'], rc['type'], 'GetVolume',
                       '<InstanceID>0</InstanceID><Channel>Master</Channel>')
        vol = None
        for el in ET.fromstring(gv).iter():
            if el.tag.split('}')[-1] == 'CurrentVolume':
                vol = el.text
        print('     SetVolume(60) -> GetVolume =', vol)
        assert vol == '60', '音量未生效: %s' % vol
        print('     音量控制: PASS')

        # ---------- 响应体积 ----------
        print('[6] 响应体积检查')
        sizes = {}
        for s in services:
            sizes[s['type'].split(':')[-2]] = len(get(BASE + s['scpd']))
        sizes['device.xml'] = len(get(BASE + '/device.xml'))
        for k, v in sizes.items():
            print('     %-20s %6d bytes' % (k, v))
            assert v < 131072, '%s 过大(%d bytes)，有被判 ResponseTooLarge 的风险' % (k, v)
        print('     体积检查: PASS')

        print('\n全部 UPnP 兼容性检查通过')
    finally:
        stack.stop()


if __name__ == '__main__':
    main()
