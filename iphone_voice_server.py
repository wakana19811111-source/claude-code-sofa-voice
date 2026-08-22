#!/usr/bin/env python3
"""iPhone のショートカットから送られた音声入力テキストを受け取って標準出力に出す。

iCloud を通らないので、同じ Wi-Fi にいれば1秒かからず届く。
LaunchAgent（com.example.iphone-voice.plist）から起動し、標準出力を
~/Library/Logs/iphone_voice.log へ流して使う。

iPhone 側（ショートカット）の設定：
  アクション「URLの内容を取得」
    URL        : http://<MacのローカルIP>:9100
    方法       : POST
    本文を要求 : ファイル → 変数「音声入力されたテキスト」
"""
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 9100  # 他で使っていない番号なら何でもよい（lsof -i :9100 で確認）


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace").strip()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("OK".encode())
        if body:
            print("【iPhone音声】" + " ".join(body.splitlines()), flush=True)

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("iPhone voice server is running".encode())

    def log_message(self, *args):
        pass  # アクセスログは出さない（通知が増えるため）


if __name__ == "__main__":
    try:
        HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except OSError as e:
        print(f"起動できない: {e}", flush=True)
        sys.exit(1)
