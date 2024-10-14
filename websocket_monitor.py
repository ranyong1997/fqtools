import asyncio
import ctypes
import websockets
import sys
import time
import logging
import subprocess
from multiprocessing import Process
import psutil
import os
import tempfile

# 关闭cmd 没有重启
# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# WebSocket URL
# WS_URL = "ws://monitor.convercomm.com:18908/rtp/44010200491320000001_44010200491320000001.live.flv"
WS_URL = "ws://172.29.0.15:6080/fq/1001.live.flv"

BAT_SCRIPT_CONTENT = """
@echo off
setlocal enabledelayedexpansion
REM 定义标记文件路径
set "FLAG_FILE=%TEMP%\startup_executed.flag"
REM 检查是否存在标记文件
if exist "%FLAG_FILE%" (
    REM 如果存在，直接退出脚本
    for /f "tokens=2 delims==" %%I in ('wmic os get lastbootuptime /format:list') do set "BOOT_TIME=%%I"
    for /f %%I in ('dir /b /a:-d "%FLAG_FILE%"^|findstr /v /r "^$"') do set "FLAG_TIME=%%~tI"
) else (
    REM 如果不存在标记文件，执行命令
    goto :execute_command
)
:execute_command
REM 创建标记文件
echo. > "%FLAG_FILE%"
REM 执行您的命令（请替换为实际命令）
start "" /min cmd /c ffmpeg -i rtsp://192.168.144.25:8554/main.264 -c:v libx264 -c:a aac -f flv rtmp://172.29.0.15:1935/fq/1001
REM 等待一小段时间，确保命令开始执行
timeout /t 5 /nobreak > nul
REM 保留标记文件，不删除
exit
"""

script_process = None


def create_temp_bat_script():
    temp_dir = tempfile.gettempdir()
    bat_file_path = os.path.join(temp_dir, "websocket_monitor_script.bat")
    with open(bat_file_path, "w") as bat_file:
        bat_file.write(BAT_SCRIPT_CONTENT)
    return bat_file_path


def call_bat_script():
    global script_process
    try:
        bat_file_path = create_temp_bat_script()
        script_process = subprocess.Popen(
            [bat_file_path], shell=True, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )
        logging.info(f"成功启动批处理脚本: {bat_file_path}")
    except subprocess.SubprocessError as e:
        logging.error(f"启动批处理脚本时出错: {e}")
        script_process = None


def stop_bat_script():
    global script_process
    if script_process:
        try:
            parent = psutil.Process(script_process.pid)
            children = parent.children(recursive=True)
            for child in children:
                child.terminate()
            parent.terminate()
            logging.info("已停止批处理脚本及其子进程")
        except psutil.NoSuchProcess:
            logging.info("批处理脚本已经停止")
        finally:
            script_process = None


async def monitor_websocket():
    stream_active = False
    while True:
        try:
            logging.warning(f"尝试连接到 WebSocket:{WS_URL}")
            call_bat_script()
            async with websockets.connect(WS_URL) as websocket:
                logging.info("已连接到WebSocket")
                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=5)
                        logging.info(f"接收到数据: {len(message)} 字节")
                        if not stream_active:
                            stream_active = True
                            call_bat_script()
                    except asyncio.TimeoutError:
                        logging.warning("5秒内未收到数据，可能没有推流")
                        if stream_active:
                            stream_active = False
                            stop_bat_script()
                    except websockets.ConnectionClosed:
                        logging.error("WebSocket连接已关闭")
                        stream_active = False
                        stop_bat_script()
                        break
        except Exception as e:
            logging.error(f"发生异常: {str(e)}")
            stream_active = False
            stop_bat_script()
            await asyncio.sleep(5)  # 等待5秒后重试


def run_monitor():
    asyncio.run(monitor_websocket())


def is_process_running(process_name):
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] == process_name:
            return True
    return False


def start_monitor():
    while True:
        if not is_process_running("websocket_monitor.exe"):
            process = Process(target=run_monitor)
            process.start()
            process.join()
            logging.warning("监控进程已退出，正在重启...")
        time.sleep(5)  # 每5秒检查一次


# 添加程序到启动文件夹
def create_shortcut():
    import win32com.client
    startup_folder = os.path.join(os.getenv('APPDATA'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
    path = os.path.join(startup_folder, "WebSocketMonitor.lnk")
    target = sys.executable

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(path)
    shortcut.Targetpath = target
    shortcut.WorkingDirectory = os.path.dirname(target)
    shortcut.save()
    logging.info("程序快捷方式已添加到启动文件夹")


# 隐藏控制台
def hide_console():
    kernel32 = ctypes.WinDLL('kernel32')
    user32 = ctypes.WinDLL('user32')

    hWnd = kernel32.GetConsoleWindow()
    if hWnd:
        user32.ShowWindow(hWnd, 0)


def check_environment():
    logging.info(f"当前工作目录: {os.getcwd()}")
    logging.info(f"Python 版本: {sys.version}")
    logging.info(f"操作系统: {sys.platform}")


if __name__ == "__main__":
    logging.debug('程序开始运行')
    try:
        check_environment()
        create_shortcut()  # 将程序添加到启动项
        hide_console()
        call_bat_script()
        run_monitor()
        start_monitor()
    except KeyboardInterrupt:
        logging.info("程序被用户中断")
        sys.exit(0)
