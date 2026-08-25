import random

UA_TEMPLATES = {
    "windows": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36",
    "macos": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36",
    "linux": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36",
}

DESKTOP_OS = ["windows", "macos", "linux"]


def random_desktop_os() -> str:
    return random.choices(DESKTOP_OS, weights=[60, 25, 15])[0]


def random_chrome_ua(os_name: str | None = None) -> str:
    if os_name is None:
        os_name = random_desktop_os()
    major = random.randint(126, 148)
    minor = random.randint(0, 9999)
    ver = f"{major}.0.{minor}.0"
    return UA_TEMPLATES[os_name].format(ver=ver)


def extract_os(ua: str) -> str:
    if "Windows NT" in ua:
        return "windows"
    if "Macintosh" in ua:
        return "macos"
    if "X11; Linux" in ua:
        return "linux"
    return "unknown"