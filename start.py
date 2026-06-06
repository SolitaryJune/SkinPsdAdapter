from __future__ import annotations

import socket
import threading
import time
import urllib.request
import webbrowser
from contextlib import closing

import uvicorn


HOST = "127.0.0.1"
DEFAULT_PORT = 18724


def find_free_port(start_port: int = DEFAULT_PORT) -> int:
    """找一个本机可用端口。

    发给别人使用时，18724 可能被其它软件占用；启动器自动后移查找，避免用户看到黑窗口报错。
    """

    for port in range(start_port, start_port + 100):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex((HOST, port)) != 0:
                return port
    raise RuntimeError("没有找到可用端口，请关闭占用本机端口的软件后重试。")


def open_browser_when_ready(port: int) -> None:
    """服务启动后自动打开浏览器。

    uvicorn.run 会阻塞主线程，所以浏览器探活放到后台线程里；等 /health 返回后再打开页面。
    """

    url = f"http://{HOST}:{port}/"
    health_url = f"http://{HOST}:{port}/health"
    for _ in range(80):
        try:
            with urllib.request.urlopen(health_url, timeout=0.5) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.25)
    print(f"服务已启动，请手动打开：{url}")


def main() -> None:
    port = find_free_port()
    print("=" * 64)
    print("皮肤 PSD 自动适配工具")
    print(f"本地地址：http://{HOST}:{port}/")
    print("关闭这个窗口即可停止服务。")
    print("=" * 64)

    threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()

    # 直接传入 app 对象，PyInstaller 打包后也能稳定启动，不依赖命令行模块路径解析。
    from backend.main import app

    uvicorn.run(app, host=HOST, port=port, log_level="info")


if __name__ == "__main__":
    main()

