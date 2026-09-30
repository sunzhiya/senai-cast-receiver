"""打包 Windows exe（PyInstaller onefile，无控制台）。

    python build_exe.py

产物：dist/森投屏接收端.exe
注意：Qt6 的 multimedia 后端插件不会被默认收集，必须显式带进去，
否则打包后能启动但无法播放视频（ffmpegmediaplugin 缺失）。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = '森投屏接收端'


def qt_plugin_dir():
    import PyQt6
    return os.path.join(os.path.dirname(PyQt6.__file__), 'Qt6', 'plugins')


def main():
    plug = qt_plugin_dir()
    mm = os.path.join(plug, 'multimedia')
    cmd = [sys.executable, '-m', 'PyInstaller',
           '--noconfirm', '--clean',
           '--windowed', '--onefile',
           '--name', NAME,
           '--icon', os.path.join(HERE, 'receiver', 'assets', 'icon.ico'),
           '--add-data', (os.path.join(HERE, 'receiver', 'assets')
                          + os.pathsep + os.path.join('receiver', 'assets')),
           '--hidden-import', 'PyQt6.QtMultimedia',
           '--hidden-import', 'PyQt6.QtMultimediaWidgets',
           '--hidden-import', 'numpy',
           '--exclude-module', 'torch',
           '--exclude-module', 'PyQt6.QtWebEngineCore',
           '--exclude-module', 'PyQt6.QtWebEngineWidgets',
           'main.py']
    for dll in ('ffmpegmediaplugin.dll', 'windowsmediaplugin.dll'):
        p = os.path.join(mm, dll)
        if os.path.exists(p):
            cmd += ['--add-binary', p + os.pathsep + os.path.join('PyQt6', 'Qt6', 'plugins', 'multimedia')]
    print(' '.join(cmd[:6]), '...')
    r = subprocess.run(cmd, cwd=HERE)
    if r.returncode == 0:
        print('\n打包完成:', os.path.join(HERE, 'dist', NAME + '.exe'))
    return r.returncode


if __name__ == '__main__':
    sys.exit(main())
