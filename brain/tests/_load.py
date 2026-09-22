"""Load brain/lambda_function.py offline, with every AWS call replaced by a stub.

Nothing here talks to Bedrock or DynamoDB. `install_stubs()` decides what the screen and the
classifier "say", so each test states the situation it is about and asserts the decision.
"""
import importlib.util
import os
import pathlib
import subprocess
import sys

BRAIN_DIR = pathlib.Path(__file__).resolve().parent.parent
if not (BRAIN_DIR / "tenants.json").exists():
    subprocess.run(["bash", str(BRAIN_DIR / "build.sh")], check=True, stdout=subprocess.DEVNULL)

os.environ.setdefault("CONVO_TABLE", "stub-convo")      # so the clarify paths are reachable
os.environ.setdefault("KB_TABLE_PREFIX", "")            # snapshot only
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "stub")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "stub")


def load(name="brain_under_test"):
    spec = importlib.util.spec_from_file_location(name, BRAIN_DIR / "lambda_function.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ENTRY = {"id": "some_entry", "answer": "Do this, then that.", "category": "network",
         "error_strings": [], "owner": "on-call", "triggers": ["x"]}
USAGE = {"inputTokens": 1, "outputTokens": 1}


def install_stubs(brain, score=0.0, kind="underspecified", ask="action", is_request=True, domain="on"):
    """`score` is what the classifier returns for ENTRY (0 = "none"); `kind` is the screen's verdict."""
    brain.load_entries = lambda: ([ENTRY], "kb stub (1)")
    brain.screen = lambda text, categories="": (is_request, domain, kind, ask, USAGE)
    brain.bedrock_classify = lambda q, e: ((ENTRY, score, "stub", USAGE) if score > 0 else (None, 0.0, "stub", USAGE))
    brain.read_image = lambda *a, **k: "I get error XYZ on screen"
    brain.state_get = lambda key: {}
    brain.state_try_claim = lambda *a, **k: True
    brain.state_clear_pending = lambda *a, **k: True
    brain.supporter_touch = lambda *a, **k: None
    brain.supporter_recent_secs = lambda *a, **k: None
    brain._prefs = {}
    brain.dm_pref_get = lambda user: brain._prefs.get(brain._user_part(user))
    brain.dm_pref_set = lambda user, t, now: brain._prefs.__setitem__(brain._user_part(user), t)
