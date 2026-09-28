r"""Ask the DeepSeek Harness (DSH) web app about its speaking voice.

DSH reads replies aloud through its dsh-tts plugin. Flow's chat buttons
(the floating pill and the mouse side button) should silence that voice
instead of starting a dictation turn while a reply is still playing.

Two tiny HTTP calls against DSH's loopback server back this up:

  speaking()  ->  GET  /dsh-tts/state   {"speaking": true/false}
  stop()      ->  POST /dsh-tts/stop    tells every open DSH page to stop

Every failure counts as "not speaking": dictation must keep working when
DSH is down, restarting, or listening on another port. Override the port
with the FLOW_DSH_TTS_BASE environment variable if it ever changes.
"""

import json
import logging
import os
import time
import urllib.request

log = logging.getLogger("flow")

DEFAULT_BASE = "http://127.0.0.1:3080"
TIMEOUT_SECONDS = 0.25

# After a transport failure, skip the checks for a while so a dead server
# cannot add latency to every button press.
_FAILURE_COOLDOWN = 30.0
_next_try_after = 0.0


def _base():
    return os.environ.get("FLOW_DSH_TTS_BASE") or DEFAULT_BASE


def _fetch(base, path, method="GET"):
    request = urllib.request.Request(
        base.rstrip("/") + path, method=method,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _call(path, method="GET"):
    global _next_try_after
    if time.monotonic() < _next_try_after:
        return None
    try:
        return _fetch(_base(), path, method)
    except Exception as error:          # DSH down, wrong port, bad JSON
        _next_try_after = time.monotonic() + _FAILURE_COOLDOWN
        log.info("dsh voice check failed: %s", error)
        return None


def reset_cooldown():
    """Tests use this so one injected failure does not poison later calls."""
    global _next_try_after
    _next_try_after = 0.0


def speaking():
    """True when the DSH reply voice is playing right now."""
    state = _call("/dsh-tts/state")
    return bool(state and state.get("speaking"))


def stop():
    """Ask every connected DSH page to stop the reply voice."""
    result = _call("/dsh-tts/stop", method="POST")
    return bool(result and result.get("ok"))
