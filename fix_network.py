"""一键修复网络/防火墙（需管理员权限），由 GUI 的「一键修复网络」按钮提权调用。

做两件事：
  1) 给 pythonw.exe 加防火墙入站规则：TCP 8200(控制) + UDP 1900(SSDP)。
  2) 停掉系统 SSDP Discovery 服务，释放 1900 端口（手机"扫不到"的常见原因之一）。
     只影响 Windows「网络发现」，不影响上网；重启后服务自动恢复，需要时再点一次。

本脚本由 pythonw 以 runas 启动，subprocess 必须显式 PIPE 并隐藏窗口，
否则 netsh 输出为 None，看起来成功实际没生效。
"""
import os
import subprocess
import sys
import time

LOG = os.path.join(os.environ.get('TEMP', '.'), 'cast-fix.log')

RULE_TCP_IN = '森投屏接收端-TCP8200'
RULE_UDP_IN = '森投屏接收端-UDP1900'
RULE_TCP_OUT = '森投屏接收端-TCP8200-出'
RULE_UDP_OUT = '森投屏接收端-UDP1900-出'


def _log(msg):
    ts = time.strftime('%H:%M:%S')
    line = '[%s] %s' % (ts, msg)
    print(line)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def _is_admin():
    """检测是否以管理员身份运行。"""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def _run(cmd):
    """运行命令；在 pythonw 无控制台环境下也要保证 stdout/stderr 可用。"""
    _log('执行: %s' % ' '.join(cmd))
    try:
        # 隐藏子进程窗口，避免 netsh 弹黑框；同时显式指定 PIPE，防止返回 None
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        r = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='ignore',
            startupinfo=si,
        )
        out = (r.stdout or '').strip()
        err = (r.stderr or '').strip()
        if out:
            _log('  stdout: ' + out[:500])
        if r.returncode != 0 and err:
            _log('  stderr: ' + err[:500])
        return r.returncode == 0
    except Exception as e:
        _log('  异常: %s' % e)
        return False


def _rule_exists(name):
    """检查指定名称的防火墙规则是否存在。"""
    ok = _run(['netsh', 'advfirewall', 'firewall', 'show', 'rule', 'name=%s' % name])
    return ok


def add_firewall_rules():
    exe = sys.executable  # 当前 pythonw.exe 路径
    rules = [
        (RULE_TCP_IN, 'in', 'TCP', '8200'),
        (RULE_UDP_IN, 'in', 'UDP', '1900'),
        (RULE_TCP_OUT, 'out', 'TCP', '8200'),
        (RULE_UDP_OUT, 'out', 'UDP', '1900'),
    ]
    ok_all = True
    for name, direction, proto, port in rules:
        # 先删旧规则避免重复堆积
        _run(['netsh', 'advfirewall', 'firewall', 'delete', 'rule',
              'name=%s' % name])
        ok = _run(['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                   'name=%s' % name, 'dir=%s' % direction, 'action=allow',
                   'program=%s' % exe, 'protocol=%s' % proto,
                   'localport=%s' % port, 'profile=any', 'enable=yes'])
        if not ok:
            ok_all = False
            _log('  !! 规则 %s 添加可能失败' % name)
        else:
            # 关键：主动校验规则是否真的写进去了
            if not _rule_exists(name):
                ok_all = False
                _log('  !! 规则 %s 校验失败（show rule 查不到）' % name)
            else:
                _log('  规则 %s 添加并校验成功' % name)
    return ok_all


def stop_ssdp():
    """停止系统 SSDP Discovery 服务，释放 1900 端口。"""
    _log('尝试停止系统 SSDP Discovery 服务(SSDPSRV)……')
    ok = _run(['net', 'stop', 'ssdpsrv', '/y'])
    if ok:
        _log('SSDPSRV 已停止，1900 端口已释放。请重启本软件以启用主动响应。')
    else:
        _log('SSDPSRV 停止失败（可能已被停止或权限不足）。若仍扫不到，请手动在服务中停止它。')
    return ok


def main():
    _log('==== 森投屏接收端 网络修复开始 ====')
    if not _is_admin():
        _log('!! 警告：当前未以管理员身份运行，netsh 命令大概率会失败')

    fw_ok = add_firewall_rules()
    ssdpsrv_ok = stop_ssdp()

    if fw_ok and ssdpsrv_ok:
        _log('==== 修复完成。请重启「森投屏接收端」软件。====')
        msg = ('防火墙规则已添加并校验通过，系统 SSDP 服务已成功停止。\n\n'
               '请重启「森投屏接收端」软件，手机即可主动搜索到本设备。\n'
               '（SSDPSRV 重启电脑后会自动恢复，不影响上网）')
        title = '森投屏接收端 - 网络修复完成'
    elif not fw_ok:
        _log('==== 修复部分失败：防火墙规则未成功添加 ====')
        msg = ('防火墙规则添加或校验失败。\n\n'
               '请手动以管理员身份运行 cmd，执行以下命令后重启本软件：\n'
               'netsh advfirewall firewall add rule name=森投屏接收端-TCP8200 '
               'dir=in action=allow program="%s" protocol=TCP localport=8200 profile=any\n'
               'netsh advfirewall firewall add rule name=森投屏接收端-UDP1900 '
               'dir=in action=allow program="%s" protocol=UDP localport=1900 profile=any'
               % (sys.executable, sys.executable))
        title = '森投屏接收端 - 防火墙规则失败'
    else:
        _log('==== 修复部分失败：SSDPSRV 未能停止 ====')
        msg = ('防火墙规则已添加，但系统 SSDP 服务未能停止。\n\n'
               '请手动以管理员运行 services.msc，找到 "SSDP Discovery" 服务并停止，'
               '然后重启本软件。')
        title = '森投屏接收端 - SSDP 服务停止失败'

    _log('详细日志见: ' + LOG)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, title, 0x40)
    except Exception:
        pass


if __name__ == '__main__':
    main()
