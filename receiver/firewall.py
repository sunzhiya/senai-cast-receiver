"""Windows 防火墙规则检测。

本软件用 pythonw（无控制台）跑，netsh 必须显式 STARTUPINFO 隐藏窗口，
stdout/stderr 做 None 保护，否则提权环境下会拿到 None。
"""
import subprocess
import sys


def _run_netsh_show(name):
    """执行 netsh show rule；返回 (returncode, stdout_text, stderr_text)。"""
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        r = subprocess.run(
            ['netsh', 'advfirewall', 'firewall', 'show', 'rule',
             'name=%s' % name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='ignore',
            startupinfo=si,
        )
        return r.returncode, r.stdout or '', r.stderr or ''
    except Exception:
        return -1, '', ''


def has_firewall_rule(name):
    """检查指定名称的 Windows 防火墙规则是否存在。

    非 Windows 平台直接返回 True（无需检查）。
    """
    if sys.platform != 'win32':
        return True
    rc, out, _ = _run_netsh_show(name)
    out_lower = out.lower()
    # netsh 成功时输出包含"规则名称"或"Rule Name"；失败时通常提示"找不到"
    return rc == 0 and ('规则名称' in out_lower or 'rule name' in out_lower
                        or name.lower() in out_lower)


def check_cast_rules():
    """检查本软件的两条关键入站规则是否都存在。"""
    return (has_firewall_rule('森投屏接收端-TCP8200') and
            has_firewall_rule('森投屏接收端-UDP1900'))
