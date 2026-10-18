"""عميل HTTP مشترك لمواقع الترجمة."""

from __future__ import annotations

import urllib.parse
from typing import Dict

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS: Dict[str, str] = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

DEFAULT_TIMEOUT = 20


def make_session() -> requests.Session:
    """ينشئ جلسة HTTP مع إعدادات متينة."""
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    try:
        s.verify = True
    except Exception:
        pass
    return s


def get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    """طلب GET مع مهلة افتراضية."""
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    kwargs.setdefault("allow_redirects", True)
    return session.get(url, **kwargs)


def post(session: requests.Session, url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    kwargs.setdefault("allow_redirects", True)
    return session.post(url, **kwargs)


def host_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc


def base(url: str) -> str:
    p = urllib.parse.urlparse(url)
    return f"{p.scheme}://{p.netloc}"