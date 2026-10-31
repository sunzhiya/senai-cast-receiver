import subprocess
import sys


def _run_netsh_show(name):
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
    if sys.platform != 'win32':
        return True
    rc, out, _ = _run_netsh_show(name)
    out_lower = out.lower()
    return rc == 0 and ('规则名称' in out_lower or 'rule name' in out_lower
                        or name.lower() in out_lower)


def check_cast_rules():
    return (has_firewall_rule('森投屏接收端-TCP8200') and
            has_firewall_rule('森投屏接收端-UDP1900'))
