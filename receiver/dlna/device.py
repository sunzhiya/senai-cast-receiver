from . import DEVICE_UUID


def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def device_description(ip, port, name, tv_mode=False):
    """生成 MediaRenderer 设备描述 XML。

    tv_mode=True 时把型号报成 4K 智能电视——部分 App 看型号名决定推不推
    高码率流。尽力而为，最终清晰度还是手机说了算。
    """
    loc = "http://%s:%d/device.xml" % (ip, port)
    pres = "http://%s:%d/device.xml" % (ip, port)
    if tv_mode:
        model_name = "SenAI 4K Smart TV"
        model_desc = "SenAI 4K Ultra HD Smart TV DLNA Renderer (supports 1080P/4K HEVC)"
        model_num = "UHD-4K"
        dlna_doc = "DMR-1.50"
    else:
        model_name = "CastReceiver"
        model_desc = "SenAI DLNA/AirPlay Cast Receiver for Windows"
        model_num = "1.0"
        dlna_doc = "DMR-1.50"
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<root xmlns="urn:schemas-upnp-org:device-1-0" '
        'xmlns:dlna="urn:schemas-dlna-org:device-1-0">\n'
        '  <specVersion><major>1</major><minor>0</minor></specVersion>\n'
        '  <device>\n'
        '    <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>\n'
        '    <friendlyName>' + _esc(name) + '</friendlyName>\n'
        '    <manufacturer>SenAI</manufacturer>\n'
        '    <manufacturerURL>https://yutongguoji.cn</manufacturerURL>\n'
        '    <modelName>' + _esc(model_name) + '</modelName>\n'
        '    <modelNumber>' + model_num + '</modelNumber>\n'
        '    <modelURL>https://yutongguoji.cn</modelURL>\n'
        '    <modelDescription>' + _esc(model_desc) + '</modelDescription>\n'
        '    <serialNumber>0001</serialNumber>\n'
        '    <UDN>uuid:' + DEVICE_UUID + '</UDN>\n'
        '    <UPC>000000000001</UPC>\n'
        '    <dlna:X_DLNADOC>' + dlna_doc + '</dlna:X_DLNADOC>\n'
        '    <presentationURL>' + pres + '</presentationURL>\n'
        '    <iconList>\n'
        '      <icon>\n'
        '        <mimetype>image/png</mimetype>\n'
        '        <width>120</width>\n'
        '        <height>120</height>\n'
        '        <depth>24</depth>\n'
        '        <url>/icon.png</url>\n'
        '      </icon>\n'
        '    </iconList>\n'
        '    <serviceList>\n'
        '      <service>\n'
        '        <serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>\n'
        '        <serviceId>urn:upnp-org:serviceId:RenderingControl</serviceId>\n'
        '        <controlURL>/upnp/control/RenderingControl</controlURL>\n'
        '        <eventSubURL>/upnp/event/RenderingControl</eventSubURL>\n'
        '        <SCPDURL>/upnp/scpd/RenderingControl</SCPDURL>\n'
        '      </service>\n'
        '      <service>\n'
        '        <serviceType>urn:schemas-upnp-org:service:ConnectionManager:1</serviceType>\n'
        '        <serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>\n'
        '        <controlURL>/upnp/control/ConnectionManager</controlURL>\n'
        '        <eventSubURL>/upnp/event/ConnectionManager</eventSubURL>\n'
        '        <SCPDURL>/upnp/scpd/ConnectionManager</SCPDURL>\n'
        '      </service>\n'
        '      <service>\n'
        '        <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>\n'
        '        <serviceId>urn:upnp-org:serviceId:AVTransport</serviceId>\n'
        '        <controlURL>/upnp/control/AVTransport</controlURL>\n'
        '        <eventSubURL>/upnp/event/AVTransport</eventSubURL>\n'
        '        <SCPDURL>/upnp/scpd/AVTransport</SCPDURL>\n'
        '      </service>\n'
        '    </serviceList>\n'
        '  </device>\n'
        '</root>'
    )
