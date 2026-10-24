"""Small standard-library Chrome DevTools Protocol client for local browsers."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import urllib.error
import urllib.request
from urllib.parse import urlsplit

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class CdpError(RuntimeError):
    pass


class WebSocket:
    """Minimal RFC 6455 client: masked sends, text replies, ping and close."""

    def __init__(self, url: str, timeout: float = 5.0):
        parts = urlsplit(url)
        if parts.scheme not in {"ws", "wss"}:
            raise CdpError("DevTools returned an unsupported websocket URL")
        host = parts.hostname or "127.0.0.1"
        port = parts.port or (443 if parts.scheme == "wss" else 80)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        raw = socket.create_connection((host, port), timeout=timeout)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host) if parts.scheme == "wss" else raw
        self.sock.settimeout(timeout)
        self.buffer = b""
        self._handshake(host, port, path)

    def _handshake(self, host: str, port: int, path: str) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
                   "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(request.encode("ascii"))
        while b"\r\n\r\n" not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise CdpError("DevTools websocket closed during handshake")
            self.buffer += chunk
        header, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
        lines = header.decode("latin-1").split("\r\n")
        if not lines or " 101 " not in f"{lines[0]} ":
            raise CdpError(f"DevTools websocket refused the connection: {lines[0] if lines else 'no response'}")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1((key + _GUID).encode("ascii")).digest()).decode("ascii")
        if headers.get("sec-websocket-accept") != expected:
            raise CdpError("DevTools websocket handshake returned a bad accept key")

    def _exact(self, size: int) -> bytes:
        while len(self.buffer) < size:
            chunk = self.sock.recv(max(4096, size - len(self.buffer)))
            if not chunk:
                raise CdpError("DevTools websocket closed")
            self.buffer += chunk
        value, self.buffer = self.buffer[:size], self.buffer[size:]
        return value

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length < 1 << 16:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        self.sock.sendall(bytes(header) + bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload)))

    def send(self, value: str) -> None:
        self._send_frame(0x1, value.encode("utf-8"))

    def recv(self) -> str:
        chunks: list[bytes] = []
        while True:
            first, second = self._exact(2)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._exact(8))[0]
            mask = self._exact(4) if second & 0x80 else b""
            payload = self._exact(length)
            if mask:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
            opcode = first & 0x0F
            if opcode == 0x9:
                self._send_frame(0xA, payload)
            elif opcode in {0x1, 0x2, 0x0}:
                chunks.append(payload)
                if first & 0x80:
                    return b"".join(chunks).decode("utf-8")
            elif opcode == 0x8:
                raise CdpError("DevTools websocket closed")

    def close(self) -> None:
        try:
            self._send_frame(0x8, struct.pack("!H", 1000))
        except OSError:
            pass
        self.sock.close()


def page_targets(port: int, target_url: str = "") -> list[dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1.5) as response:
            targets = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise CdpError(f"no CDP endpoint answering on port {port}") from exc
    pages = [target for target in targets if target.get("type") == "page" and target.get("webSocketDebuggerUrl")]
    if target_url:
        pages.sort(key=lambda item: not item.get("url", "").startswith(target_url))
    else:
        pages.sort(key=lambda item: item.get("url", "").startswith("chrome://"))
    if not pages:
        raise CdpError(f"no page target found on CDP port {port}")
    return pages


class CdpTransport:
    def __init__(self, port: int, *, target_url: str = "", timeout: float = 5.0):
        pages = page_targets(port, target_url)
        self.url = pages[0]["webSocketDebuggerUrl"]
        self.ws = WebSocket(self.url, timeout=timeout)
        self.timeout = timeout
        self.next_id = 0

    def send(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        request_id = self.next_id
        self.ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise CdpError(f"CDP {method} failed: {message['error'].get('message', 'unknown error')}")
            return message.get("result", {})

    def close(self) -> None:
        self.ws.close()
