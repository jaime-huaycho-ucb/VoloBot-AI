"""Cliente WebSocket mínimo para MicroPython, sin librerías externas.

Soporta exactamente lo que este proyecto necesita: handshake inicial, envío
de frames de texto/binario del cliente (con máscara, como exige RFC 6455) y
recepción de frames de texto/binario del servidor (sin máscara). No soporta
fragmentación multi-frame ni mensajes mayores a 65535 bytes (de sobra para
el protocolo de este proyecto: JSON de control + bloques de audio de ~1KB).
"""

import time
import usocket as socket
import ubinascii
import ustruct

try:
    import urandom
except ImportError:
    import random as urandom


class WebSocketClient:
    def __init__(self, host, port, path, headers=None):
        self.host = host
        self.port = port
        self.path = path
        self.headers = headers or {}
        self.sock = None
        self.connected = False
        self._buffer = b""

    def connect(self):
        addr = socket.getaddrinfo(self.host, self.port)[0][-1]
        self.sock = socket.socket()
        self.sock.connect(addr)

        key_bytes = bytes(urandom.getrandbits(8) for _ in range(16))
        key = ubinascii.b2a_base64(key_bytes).strip().decode()

        request = (
            "GET {path} HTTP/1.1\r\n"
            "Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
        ).format(path=self.path, host=self.host, port=self.port, key=key)
        for name, value in self.headers.items():
            request += "{}: {}\r\n".format(name, value)
        request += "\r\n"
        self.sock.send(request.encode())

        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(512)
            if not chunk:
                raise OSError("Conexión cerrada durante el handshake WebSocket")
            response += chunk
        status_line = response.split(b"\r\n", 1)[0]
        if b"101" not in status_line:
            raise OSError("Handshake WebSocket falló: %r" % status_line)

        self.sock.setblocking(False)
        self.connected = True

    def close(self):
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _send_frame(self, opcode, payload):
        mask = bytes(urandom.getrandbits(8) for _ in range(4))
        length = len(payload)
        header = bytearray()
        header.append(0x80 | opcode)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += ustruct.pack(">H", length)
        else:
            raise ValueError("Payload demasiado grande para este cliente WS")
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._send_all(header + masked)

    def _send_all(self, data):
        """send() sobre un socket no bloqueante puede enviar a medias o dar EAGAIN."""
        if not self.connected or self.sock is None:
            raise OSError("WebSocket no conectado")
        view = memoryview(data)
        sent = 0
        deadline = time.ticks_add(time.ticks_ms(), 3000)
        while sent < len(data):
            try:
                n = self.sock.send(view[sent:])
                if n:
                    sent += n
            except OSError as exc:
                if exc.args and exc.args[0] in (11, 119):  # EAGAIN / EINPROGRESS
                    if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                        self.close()
                        raise OSError("Timeout enviando por WebSocket")
                    time.sleep_ms(2)
                    continue
                self.close()
                raise

    def send_text(self, text):
        self._send_frame(0x1, text.encode())

    def send_binary(self, data):
        self._send_frame(0x2, data)

    def _read_available(self):
        try:
            chunk = self.sock.recv(2048)
        except OSError:
            return
        if chunk == b"":
            self.close()
            return
        if chunk:
            self._buffer += chunk

    def poll(self):
        """Devuelve (opcode, payload) de un frame completo si llegó, o None."""
        if not self.connected:
            return None
        self._read_available()
        if len(self._buffer) < 2:
            return None

        b0, b1 = self._buffer[0], self._buffer[1]
        opcode = b0 & 0x0F
        masked = (b1 & 0x80) != 0
        length = b1 & 0x7F
        offset = 2

        if length == 126:
            if len(self._buffer) < 4:
                return None
            length = ustruct.unpack(">H", self._buffer[2:4])[0]
            offset = 4
        elif length == 127:
            self._buffer = b""  # mensaje gigante no soportado; se descarta
            return None

        mask_key = b""
        if masked:
            if len(self._buffer) < offset + 4:
                return None
            mask_key = self._buffer[offset:offset + 4]
            offset += 4

        if len(self._buffer) < offset + length:
            return None

        payload = self._buffer[offset:offset + length]
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        self._buffer = self._buffer[offset + length:]

        if opcode == 0x8:  # close
            self.close()
            return None
        if opcode == 0x9:  # ping del servidor: hay que responder pong o corta a los ~40 s
            self._send_frame(0xA, payload)
            return None
        if opcode == 0xA:  # pong, se ignora
            return None
        return (opcode, payload)
