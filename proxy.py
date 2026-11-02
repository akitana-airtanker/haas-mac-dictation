#!/usr/bin/env python3
"""OpenAI 互換の文字起こしクライアント (VoiceInk など) と speech.cpp の間の中継。

- speech.cpp が拒否する項目 (temperature, model, stream など) を落とす
- keywords.txt の語彙を keywords[] として足す (Haas のカスタム語彙)
- 長い音声 (CHUNK_SECONDS 超) だけ chunking_strategy=auto を足し、silero-vad の区間ごとに認識させる
  (短い音声は丸ごとの方が句読点が正確。長い一括は文が抜けることがある)
標準ライブラリだけで動く。
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.error
import urllib.request
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
UPSTREAM = os.environ.get("HAAS_UPSTREAM", "http://127.0.0.1:8080")
PORT = int(os.environ.get("HAAS_PROXY_PORT", "8081"))
KEYWORDS_FILE = os.environ.get("HAAS_KEYWORDS", os.path.join(HERE, "keywords.txt"))
FFMPEG = "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else "ffmpeg"
PASS = {"file", "language", "response_format"}
CHUNK_SECONDS = float(os.environ.get("HAAS_CHUNK_SECONDS", "90"))


def ensure_wav(data, filename):
    """RIFF WAVE 以外で、中身が空でなければ ffmpeg で 16kHz mono PCM WAV に変換する。"""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return data, filename or "audio.wav", "audio/wav", False
    if not data or all(b == 0 for b in data[:64]):
        return data, filename or "audio.wav", "audio/wav", False
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            p = subprocess.run(
                [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", "pipe:0",
                 "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", tmp.name],
                input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30
            )
            if p.returncode == 0:
                wav = tmp.read()
                if wav[:4] == b"RIFF":
                    return wav, "audio.wav", "audio/wav", True
    except Exception:
        pass
    return data, filename or "audio.wav", "audio/wav", False


def wav_seconds(data):
    """RIFF の fmt と data チャンクから長さを求める。読めなければ None。"""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    i, rate_bytes = 12, None
    while i + 8 <= len(data):
        cid, size = data[i:i + 4], int.from_bytes(data[i + 4:i + 8], "little")
        if cid == b"fmt ":
            rate_bytes = int.from_bytes(data[i + 16:i + 20], "little")  # byte rate
        elif cid == b"data" and rate_bytes:
            return min(size, len(data) - i - 8) / rate_bytes
        i += 8 + size + (size & 1)
    return None


def keywords():
    try:
        with open(KEYWORDS_FILE, encoding="utf-8") as f:
            lines = (l.strip() for l in f)
            return [l for l in lines if l and not l.startswith("#")]
    except FileNotFoundError:
        return []


def parse(ctype, body):
    msg = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
    for part in msg.iter_parts():
        yield part.get_param("name", header="content-disposition"), part


def rebuild(ctype, body):
    boundary = "haas-" + uuid.uuid4().hex
    out = bytearray()

    def add(name, data, filename=None, ptype=None):
        disp = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
        out.extend(f"--{boundary}\r\nContent-Disposition: {disp}\r\n".encode())
        if ptype:
            out.extend(f"Content-Type: {ptype}\r\n".encode())
        out.extend(b"\r\n" + data + b"\r\n")

    dropped, seconds = [], None
    for name, part in parse(ctype, body):
        if name not in PASS:
            dropped.append(name)
            continue
        data = part.get_payload(decode=True) or b""
        if name == "language" and data.strip() not in (b"ja", b"auto"):
            dropped.append("language")  # Haas は ja だけ
            continue
        if name == "file":
            data, fname, ptype, transcoded = ensure_wav(data, part.get_filename())
            if transcoded:
                dropped.append("(ffmpeg->wav)")
            seconds = wav_seconds(data)
            add(name, data, fname, ptype)
            continue
        add(name, data, part.get_filename(), part.get_content_type() if part.get_filename() else None)
    for kw in keywords():
        add("keywords[]", kw.encode())
    if seconds and seconds > CHUNK_SECONDS:
        add("chunking_strategy", b"auto")
        dropped.append(f"(chunked {seconds:.0f}s)")
    out.extend(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", bytes(out), dropped


class Handler(BaseHTTPRequestHandler):
    def _forward(self, method, path, body=None, ctype=None):
        req = urllib.request.Request(UPSTREAM + path, data=body, method=method)
        if ctype:
            req.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                status, headers, data = r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            status, headers, data = e.code, e.headers, e.read()
        except urllib.error.URLError as e:
            status, headers = 502, {}
            data = ('{"error":{"message":"speech serve に接続できません: %s"}}' % e.reason).encode()
        self.send_response(status)
        self.send_header("Content-Type", headers.get("Content-Type", "application/json"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return status, data

    def do_GET(self):
        self._forward("GET", self.path)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        ctype = self.headers.get("Content-Type", "")
        if self.path.rstrip("/").endswith("/audio/transcriptions") and ctype.startswith("multipart/"):
            ctype, body, dropped = rebuild(ctype, body)
            status, data = self._forward("POST", "/v1/audio/transcriptions", body, ctype)
            sys.stderr.write(f"  dropped={dropped} -> {status} {data[:200].decode(errors='replace')}\n")
        elif self.path.rstrip("/").endswith("/chat/completions"):
            # OpenWhispr の AI クリーンアップが誤って向いてきた場合は最後の user 入力をそのまま返す
            text = ""
            try:
                req = json.loads(body.decode("utf-8"))
                for m in reversed(req.get("messages", [])):
                    if m.get("role") == "user":
                        c = m.get("content", "")
                        text = c if isinstance(c, str) else "".join(p.get("text", "") for p in c if isinstance(p, dict))
                        break
            except Exception:
                pass
            # OpenWhispr は <transcript>…</transcript> で包み、指示文を前後に付けて送ってくる。中身だけを返す
            s, e = text.rfind("<transcript>"), text.rfind("</transcript>")
            if s != -1 and e > s:
                text = text[s + len("<transcript>"):e]
            text = text.strip()
            resp = json.dumps({
                "id": "chatcmpl-passthrough",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "passthrough",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            }, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            sys.stderr.write(f"  chat/completions passthrough ({len(text)} chars)\n")
        else:
            self._forward("POST", self.path, body, ctype)


if __name__ == "__main__":
    print(f"haas proxy on http://127.0.0.1:{PORT} -> {UPSTREAM}", file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
