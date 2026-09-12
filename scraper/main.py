"""Scraper sidecar — the ONLY network egress point for sandboxed scripts.

The sandbox containers have no internet access; they can only reach this
service over an internal network. This service fetches arbitrary public URLs,
rejects private/internal destinations (SSRF protection), and returns the raw
HTML body.

Security notes:
- Destination hostname is resolved before each request and every resolved
  address must be public. DNS-rebinding (name flips between check and connect)
  is a residual risk that is out of scope for this single-user tool.
- Redirects are followed manually so each hop is re-validated.
- Response size and total time are capped.
"""

import ipaddress
import logging
import os
import socket
import urllib.parse

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=_log_level)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("scraper")

app = FastAPI()

MAX_BYTES = int(os.environ.get("SCRAPE_MAX_BYTES", str(1024 * 1024)))  # 1 MB
TIMEOUT = float(os.environ.get("SCRAPE_TIMEOUT", "15"))
MAX_REDIRECTS = 5
USER_AGENT = "docx-engineer-scraper/1.0"

_BLOCKED_NETS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::ffff:0:0/96"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]


def is_public_host(host: str) -> bool:
    """Return True if the host resolves and every resolved address is public."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if any(ip in net for net in _BLOCKED_NETS):
            return False
    return True


@app.get("/fetch")
def fetch(url: str):
    current = url
    try:
        with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            for _ in range(MAX_REDIRECTS + 1):
                parsed = urllib.parse.urlparse(current)
                if parsed.scheme not in ("http", "https"):
                    raise HTTPException(400, "Only http:// and https:// URLs are allowed")
                host = parsed.hostname
                if not host:
                    raise HTTPException(400, "URL has no hostname")
                if not is_public_host(host):
                    raise HTTPException(403, "URL resolves to a private/internal address")

                with client.stream("GET", current, follow_redirects=False) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            raise HTTPException(502, "Redirect without Location header")
                        current = urllib.parse.urljoin(current, location)
                        continue

                    resp.raise_for_status()
                    data = bytearray()
                    for chunk in resp.iter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise HTTPException(413, f"Page exceeds {MAX_BYTES} bytes")
                    log.info("Fetched %d bytes from %s", len(data), current)
                    return Response(
                        content=bytes(data), media_type="text/html; charset=utf-8"
                    )

        raise HTTPException(502, "Too many redirects")
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(504, f"Upstream timed out after {TIMEOUT}s")
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"Upstream returned {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(502, f"Fetch error: {e}")


@app.get("/health")
def health():
    return {"status": "ok"}
