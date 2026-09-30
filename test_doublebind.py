"""对照实验：验证 main.py 里"创建两个 DlnaStack"是否会让连接落到无人 accept 的 socket。

流程 A(修复前)：造初始 stack(构造即 bind) 不关 -> 再造第二个并启动 -> 客户端 GET
流程 B(修复后)：造初始 stack -> 先 stop 彻底释放 -> 再造新的并启动 -> 客户端 GET
"""
import socket
import subprocess
import sys
import time

sys.path.insert(0, '.')
from receiver.dlna.server import DlnaStack
from receiver.dlna.services import RendererState

LOGS = []


def log(m):
    LOGS.append(m)


def count_listening(port):
    """统计 netstat 中该端口的 LISTENING socket 数量。"""
    try:
        out = subprocess.run(['netstat', '-ano'], capture_output=True,
                             text=True, timeout=15).stdout or ''
    except Exception:
        return -1
    return sum(1 for l in out.splitlines()
               if (':%d' % port) in l and 'LISTENING' in l.upper())


def client_get(port, timeout=3):
    """客户端连上去 GET /device.xml，返回结果摘要。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(('127.0.0.1', port))
        s.sendall(b'GET /device.xml HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n'
                  b'Connection: close\r\n\r\n' % port)
        data = b''
        while True:
            c = s.recv(4096)
            if not c:
                break
            data += c
        first = data.split(b'\r\n', 1)[0].decode('utf-8', 'ignore')
        return 'OK: ' + first
    except Exception as e:
        return 'FAIL: %s' % e
    finally:
        s.close()


def scenario_a(port):
    print('--- 流程 A(修复前: 不关旧栈, 直接建新栈) ---')
    state = RendererState()
    initial = DlnaStack('127.0.0.1', port, 'TestA', state, log=log)
    print('  初始栈已建(未启动), 监听数 =', count_listening(port))
    second = DlnaStack('127.0.0.1', port, 'TestA', state, log=log)
    second.start()
    time.sleep(0.4)
    print('  第二个栈启动后, 监听数 =', count_listening(port))
    r = client_get(port)
    print('  客户端 GET ->', r)
    try:
        second.stop()
    except Exception:
        pass
    try:
        initial.stop()
    except Exception:
        pass
    return r


def scenario_b(port):
    print('--- 流程 B(修复后: 先彻底关旧栈, 再建新栈) ---')
    state = RendererState()
    initial = DlnaStack('127.0.0.1', port, 'TestB', state, log=log)
    print('  初始栈已建(未启动), 监听数 =', count_listening(port))
    initial.stop()  # 关键修复
    print('  已 stop 初始栈,   监听数 =', count_listening(port))
    st = DlnaStack('127.0.0.1', port, 'TestB', state, log=log)
    st.start()
    time.sleep(0.4)
    print('  新栈启动后,       监听数 =', count_listening(port))
    r = client_get(port)
    print('  客户端 GET ->', r)
    try:
        st.stop()
    except Exception:
        pass
    return r


if __name__ == '__main__':
    ra = scenario_a(8391)
    print()
    rb = scenario_b(8392)
    print()
    print('=' * 60)
    print('流程A(修复前) 客户端结果:', ra)
    print('流程B(修复后) 客户端结果:', rb)
    print('结论:', '双绑确实破坏服务 -> 修复有效'
          if (not ra.startswith('OK') and rb.startswith('OK'))
          else ('未复现破坏(但双绑仍需修)' if rb.startswith('OK')
                else '两种都失败, 需进一步排查'))
