import asyncio
import os


async def _handle_health_request(reader, writer):
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5)
        parts = request_line.decode("ascii", errors="ignore").split()
        path = parts[1] if len(parts) >= 2 else ""
        if path == "/":
            status = "200 OK"
            body = b"OK"
        else:
            status = "404 Not Found"
            body = b"Not Found"
        response = (
            f"HTTP/1.1 {status}\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii") + body
        writer.write(response)
        await writer.drain()
    except (asyncio.TimeoutError, ConnectionError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass


async def start_health_server(host="0.0.0.0", port=None):
    if port is None:
        try:
            port = int(os.getenv("PORT", "10000"))
        except ValueError:
            port = 10000
    return await asyncio.start_server(_handle_health_request, host, port)
