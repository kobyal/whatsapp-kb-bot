"""Turn the listener's bot.log into events: one per message the brain saw.

The listener writes one line per thing that happens; the brain's verdict on a message is the
BRAIN line that follows its IN line. Nothing in the bot is changed to produce this: the curator
reads what is already written, which is the point. It is a separate layer, and a bug here can
never reach a group.

    [ts] IN  <group jid> <participant>: <text> [+image] [explicit:word]     current format
    [ts] IN  DM <participant>: <text> [tenants:a|b]                         a 1:1 message
    [ts] IN  <participant>: <text>                                          older format (jid
         came from a preceding `upsert ... jids=["<jid>"]` line)
    [ts] BRAIN tenant=<t> outcome=<o> matched=<b> id=<id|null> score=<f> | <note, 200 chars>
    [ts] BRAIN matched=<b> id=<id> score=<f>                                older format
    [ts] BRAIN tenant=? outcome=undefined ...                               a timeout envelope
    [ts] BRAIN ERROR <what>                                                 a crashed/timed-out brain
    [ts] OUT sent <outcome> <id> (<n> chars)

Known limits of the log as a source, so nobody over-reads the numbers: `text` is cut at 160
characters, the note at 200, and the near-miss entry (`suppressed_id`) is not in the note; the
curator re-classifies misses offline to recover it.
"""
from __future__ import annotations
import json
import pathlib
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
TS = r"\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z)\]"
RE_UPSERT = re.compile(TS + r' upsert .*?jids=\["([^"]+)"')
RE_IN = re.compile(TS + r" IN  (?:(DM) |(\S+@g\.us) )?(\S+): (.*)$")
RE_BRAIN = re.compile(TS + r" BRAIN (?:tenant=(\S+) )?(?:outcome=(\S+) )?matched=(\S+) id=(\S+) score=(\S+)(?: \| ?(.*))?$")
RE_BRAIN_ERR = re.compile(TS + r" BRAIN ERROR (.*)$")
RE_OUT = re.compile(TS + r" OUT sent (\S+)")
RE_CONF = re.compile(r"classify (\S+) ([0-9.]+)")
RE_SCREEN = re.compile(r"screen request=(True|False) domain=(\w+) kind=(\w+)")

# Group jid -> tenant, and tenant -> supporter ids, read from tenants/<id>/tenant.json.
# Supporters are recognised BY IDENTITY, not by the brain's note, so older logs read correctly.
GROUPS, SUPPORTERS, TEST_GROUPS, TENANT_IDS = {}, {}, {}, []
for _d in sorted((ROOT / "tenants").iterdir()) if (ROOT / "tenants").exists() else []:
    _cfg = _d / "tenant.json"
    if _cfg.exists():
        _c = json.loads(_cfg.read_text(encoding="utf-8"))
        TENANT_IDS.append(_c["id"])
        for _g in _c.get("groups") or []:
            GROUPS[_g] = _c["id"]
        SUPPORTERS[_c["id"]] = {str(s).split("@")[0].split(":")[0] for s in (_c.get("supporters") or [])}
        TEST_GROUPS[_c["id"]] = list(_c.get("test_groups") or [])
DEFAULT_TENANT = "dev-platform" if "dev-platform" in TENANT_IDS else (TENANT_IDS[0] if TENANT_IDS else "default")


@dataclass
class Event:
    ts: str
    jid: str
    tenant: str             # a tenant id, or "undecided" for a 1:1 routing turn
    participant: str
    text: str
    outcome: str            # answer | clarify | silent | nomatch | help | dm_setup | error
    entry: str | None
    score: float
    conf: float | None      # the classifier's own confidence, when it ran
    is_request: bool | None # the screen's verdict, when it ran
    kind: str | None
    note: str
    explicit: bool = False
    dm: bool = False
    image: bool = False
    supporter: bool = False
    sent: bool = False

    @property
    def when(self) -> datetime:
        return datetime.strptime(self.ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)

    @property
    def user(self) -> str:
        return self.participant.split("@")[0].split(":")[0]

    @property
    def is_miss(self) -> bool:
        """A request the bot could not answer. A clarify counts (the person asked and did not
        get an answer). A supporter's message and a non-request never count."""
        if self.supporter or self.outcome in ("answer", "help", "dm_setup", "error"):
            return False
        if self.explicit or self.dm:
            return self.outcome in ("nomatch", "clarify", "silent")
        return self.is_request is True and self.outcome in ("silent", "clarify", "nomatch")

    def to_dict(self):
        d = asdict(self)
        d["user"], d["is_miss"] = self.user, self.is_miss
        return d


def parse(lines) -> list[Event]:
    events: list[Event] = []
    jid = ""
    pending: Event | None = None
    for raw in lines:
        line = raw.rstrip("\n")
        m = RE_UPSERT.match(line)
        if m:
            jid = m.group(2)
            continue
        m = RE_IN.match(line)
        if m:
            ts, dm, in_jid, part, rest = m.groups()
            if in_jid:
                jid = in_jid
            text = re.sub(r"\s*\[(\+image|explicit:\w+|tenants:[^\]]*)\]", "", rest).strip()
            pending = Event(ts=ts, jid=part if dm else jid, tenant="?", participant=part.strip(), text=text,
                            outcome="?", entry=None, score=0.0, conf=None, is_request=None, kind=None, note="",
                            explicit="[explicit:" in rest, dm=bool(dm), image="[+image]" in rest)
            continue
        m = RE_BRAIN.match(line)
        if m and pending is not None:
            ts, tenant, outcome, matched, eid, score, note = m.groups()
            note = note or ""
            if outcome == "undefined":
                # A Lambda timeout came back as an empty envelope (older listener). The message
                # still happened; record it as an error so the thread stays whole and the failure
                # is visible, not as silence.
                tenant, outcome = None, "error"
            elif tenant == "?":
                # A 1:1 routing turn: the brain has not chosen a tenant yet. Not an error, and
                # it must stay out of per-tenant statistics.
                tenant = "undecided"
            pending.tenant = tenant or GROUPS.get(pending.jid, DEFAULT_TENANT)
            pending.outcome = outcome or ("answer" if matched == "true" else "silent")
            pending.entry = None if eid in ("null", "undefined", "None") else eid
            try:
                pending.score = float(score)
            except ValueError:
                pending.score = 0.0
            pending.note = note
            c = RE_CONF.search(note)
            pending.conf = float(c.group(2)) if c else None
            s = RE_SCREEN.search(note)
            if s:
                pending.is_request = s.group(1) == "True"
                pending.kind = s.group(3)
            if "explicit call" in note:
                pending.explicit = True
            pending.supporter = "supporter:" in note or pending.user in SUPPORTERS.get(pending.tenant, set())
            events.append(pending)
            pending = None
            continue
        m = RE_BRAIN_ERR.match(line)
        if m and pending is not None:
            pending.tenant = GROUPS.get(pending.jid, DEFAULT_TENANT)
            pending.outcome = "error"
            pending.note = m.group(2)[:200]
            events.append(pending)
            pending = None
            continue
        m = RE_OUT.match(line)
        if m and events:
            events[-1].sent = True
    return events


def load(path) -> list[Event]:
    with open(path, encoding="utf-8", errors="replace") as f:
        return parse(f)
