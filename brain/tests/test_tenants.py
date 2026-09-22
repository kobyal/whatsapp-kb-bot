"""Tenant plumbing: routing by group jid, per-tenant header, prompts, questions and texts.

Run: python3 -m pytest brain/tests -q
"""
import json

from _load import BRAIN_DIR, load

brain = load("brain_tenants")
TEN = json.loads((BRAIN_DIR / "tenants.json").read_text(encoding="utf-8"))["tenants"]


def with_tenant(tid, fn):
    tok = brain._current_tenant.set(TEN[tid])
    try:
        return fn()
    finally:
        brain._current_tenant.reset(tok)


def test_default_tenant_catches_unknown_and_missing_jids():
    assert brain.resolve_tenant({})["id"] == brain.DEFAULT_TENANT
    assert brain.resolve_tenant({"jid": "999@g.us"})["id"] == brain.DEFAULT_TENANT


def test_every_group_routes_to_its_tenant():
    for tid, t in TEN.items():
        for g in t.get("groups") or []:
            assert brain.resolve_tenant({"jid": g})["id"] == tid, (g, tid)


def test_explicit_tenant_wins_over_the_jid():
    assert brain.resolve_tenant({"tenant": "office-it", "jid": "120363000000000001@g.us"})["id"] == "office-it"


def test_header_and_texts_follow_the_tenant():
    a = with_tenant("dev-platform", lambda: brain.compose_fixed("x"))
    b = with_tenant("office-it", lambda: brain.compose_fixed("x"))
    assert TEN["dev-platform"]["header"] in a and TEN["office-it"]["header"] not in a
    assert TEN["office-it"]["header"] in b and TEN["dev-platform"]["header"] not in b
    assert not a.startswith(brain.RLM) and b.startswith(brain.RLM)   # RTL only where Hebrew appears


def test_clarify_questions_follow_the_tenant():
    q = with_tenant("office-it", lambda: brain.compose_clarify("app"))
    assert "Outlook" in q
    q = with_tenant("dev-platform", lambda: brain.compose_clarify("env"))
    assert "VPN" in q
    try:
        with_tenant("dev-platform", lambda: brain.compose_clarify("app"))
        assert False, "dev-platform has no 'app' question"
    except KeyError:
        pass


def test_screen_and_vision_prompts_are_tenant_specific():
    def screen_sys():
        return brain.SCREEN_SYSTEM.replace("__DOMAIN__", brain.T("screen_domain")).replace("__ASK_KEYS__", brain.ask_lines())
    s_it, s_dev = with_tenant("office-it", screen_sys), with_tenant("dev-platform", screen_sys)
    assert "Outlook" in s_it and "devctl" not in s_it
    assert "devctl" in s_dev and "printers" not in s_dev
    assert "__DOMAIN__" not in s_it and "__ASK_KEYS__" not in s_it
    assert '"app":' in s_it and '"env":' in s_dev


def test_snapshot_is_per_tenant_and_published_only():
    dev = with_tenant("dev-platform", brain._snapshot_entries)
    it = with_tenant("office-it", brain._snapshot_entries)
    assert len(dev) == 17 and len(it) == 4
    assert all(e.get("status", "published") == "published" for e in dev + it)


def test_catalogue_shows_six_triggers_and_a_130_char_gloss():
    dev = with_tenant("dev-platform", brain._snapshot_entries)
    cat = brain._catalogue(dev)
    assert "EXACT ERROR SEEN ON SCREEN" in cat
    for e in dev:
        assert f"- id: {e['id']}" in cat
        assert (e["answer"][:130].replace("\n", " ")) in cat


def test_kb_table_name_defaults_to_prefix_plus_tenant_id():
    saved = brain.KB_TABLE_PREFIX
    brain.KB_TABLE_PREFIX = "wakb-kb-"
    try:
        assert with_tenant("office-it", brain._kb_table_name) == "wakb-kb-office-it"
    finally:
        brain.KB_TABLE_PREFIX = saved
    brain.KB_TABLE_PREFIX = ""
    assert with_tenant("office-it", brain._kb_table_name) == ""   # snapshot only
    brain.KB_TABLE_PREFIX = saved


def test_kb_count_placeholder_is_substituted():
    dev = with_tenant("dev-platform", brain._snapshot_entries)
    help_entry = next(e for e in dev if e["id"] == "how_to_ask_the_bot")
    msg = with_tenant("dev-platform", lambda: brain.compose(help_entry, kb_size=len(dev)))
    assert "{KB_COUNT}" not in msg and f"{len(dev)} entries" in msg
