"""Model proxy: chuyển chuỗi proxy do người dùng nhập sang config Playwright."""


def parse_proxy(raw: str) -> dict | None:
    """Chuyển chuỗi proxy -> dict Playwright (server/username/password).

    Hỗ trợ các định dạng:
      - "host:port"                      (không auth)
      - "host:port:user:pass"
      - "user:pass@host:port"
    Trả None nếu chuỗi trống -> dùng IP máy (không proxy).
    Trả None nếu không parse được -> bỏ qua proxy.
    """
    raw = (raw or "").strip()
    if not raw:
        return None

    # user:pass@host:port
    if "@" in raw:
        creds, hostport = raw.rsplit("@", 1)
        user, _, pwd = creds.partition(":")
        if ":" not in hostport:
            return None
        proxy = {"server": f"http://{hostport}"}
        if user:
            proxy["username"] = user
        if pwd:
            proxy["password"] = pwd
        return proxy

    parts = raw.split(":")
    if len(parts) == 2 and parts[0] and parts[1]:
        proxy = {"server": f"http://{parts[0]}:{parts[1]}"}
    elif len(parts) == 4 and all(parts):
        host, port, user, pwd = parts
        proxy = {
            "server": f"http://{host}:{port}",
            "username": user,
            "password": pwd,
        }

    if proxy:
        proxy["bypass"] = "localhost,127.0.0.1,<-loopback>"
        return proxy
    return None
