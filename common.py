"""Helpers the family's tasks share: polite GETs that report the counters the hub's speed control runs on, and a stand-in hub
for `--local` runs."""
import time

import requests

UA = "s1d-labs scraper (https://github.com/s1d-labs)"


class LocalHub:
    """Stand-in for HubClient so `--local` runs without the hub: counters go to stderr."""
    settings = {"threads": 1, "delay_ms": 0, "paused": False}

    def __init__(self):
        self.counts = {}

    def metric(self, name, value=1):
        self.counts[name] = self.counts.get(name, 0) + value

    def error(self, n=1):
        self.metric("errors", n)

    def block(self, n=1):
        self.metric("blocked", n)


def request(hub, session, url, stream=False, timeout=(30, 120)):
    """GET with the standard counters; the response if 200, else None. For a stream, t_http_s is the time to the answer's
    headers (what tells a busy server from a calm one); the transfer itself is counted as download_s."""
    t = time.time()
    try:
        r = session.get(url, timeout=timeout, stream=stream, headers={"User-Agent": UA})
    except requests.RequestException:
        hub.metric("http_error")
        hub.error()
        return None
    hub.metric("n_http")
    hub.metric("t_http_s", time.time() - t)
    if r.status_code != 200:
        hub.metric(f"http_{r.status_code}")
        if r.status_code in (403, 429, 503):
            hub.block()
        r.close()
        return None
    return r
