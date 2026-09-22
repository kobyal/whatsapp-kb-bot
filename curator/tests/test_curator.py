"""The curator's deterministic parts, against a small hand-written bot.log in the template's
own log format (curator/tests/fixture-bot.log). No Bedrock is called here; the model-facing
pieces (confirmation judgement, drafting, trigger distillation) are exercised only live.

The fixture holds: a supporter interjection, both BRAIN line generations, a Lambda timeout
envelope and a `BRAIN ERROR` line, 1:1 routing turns, a confirmed thread (question ->
supporter answer -> asker confirms), an unconfirmed thread (asker never speaks after the
answer), a self-answered thread in a test room, and an open gap.

Run: python3 -m pytest curator/tests -q
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import curate  # noqa: E402
import events  # noqa: E402

LOG = HERE / "fixture-bot.log"
DEV_REAL, DEV_TEST = "120363000000000001@g.us", "120363000000000002@g.us"
IT_REAL, IT_TEST = "120363000000000011@g.us", "120363000000000012@g.us"


def load():
    return events.load(LOG)


def test_both_log_generations_parse_and_the_jid_comes_from_the_right_place():
    ev = load()
    assert len(ev) >= 18
    old = next(e for e in ev if "git push" in e.text)
    assert old.tenant == "dev-platform" and old.outcome == "answer" and old.entry == "git_pat_auth_failed"
    assert old.jid == DEV_TEST                      # from the preceding `upsert` line
    assert old.sent
    new = next(e for e in ev if "laptop lid" in e.text)
    assert new.jid == DEV_REAL and new.outcome == "clarify" and new.conf == 0.80 and new.is_request is True


def test_timeout_envelope_and_brain_error_line_are_error_events_not_silence():
    ev = load()
    err = [e for e in ev if e.outcome == "error"]
    assert len(err) == 2
    assert any("thanks a lot" in e.text for e in err), "the empty envelope (outcome=undefined) must be an error"
    assert any("time out" in e.text and "timed out" in e.note for e in err), "the BRAIN ERROR line must be an error"
    assert all(e.tenant == "dev-platform" for e in err), "tenant recovered from the group jid"
    assert not any(e.is_miss for e in err)


def test_supporter_messages_are_recognised_by_identity_and_never_misses():
    ev = load()
    sup = [e for e in ev if e.user in ("100000000000001", "100000000000011")]
    assert sup and all(e.supporter and not e.is_miss for e in sup)


def test_dm_events_carry_their_tenant_and_count_as_requests():
    ev = load()
    dms = [e for e in ev if e.dm]
    assert len(dms) == 4
    setup = [e for e in dms if e.outcome == "dm_setup"]
    assert any(e.tenant == "undecided" for e in setup) and any(e.tenant == "office-it" for e in setup)
    assert not any(e.outcome == "error" for e in dms)
    assert next(e for e in dms if e.outcome == "nomatch").is_miss
    u = curate.usage(ev, "office-it")
    assert u["dms"] == 2 and u["dm_people"] == 1 and u["dm_answered"] == 1


def test_a_thread_stops_at_the_next_question():
    ev = load()
    first = next(e for e in ev if e.jid == IT_TEST and e.is_miss and "לא עולה" in e.text)
    later, _ = curate.thread_after(ev, first, self_ok=True)
    assert not any("מיקרופון" in e.text for e in later), "the 6-hour window must not swallow the later question"


def test_a_confirmed_thread_in_a_real_group_is_harvested():
    ev = load()
    threads = curate.threads_for_drafts(ev, "dev-platform")
    vpn = [(m, later) for m, later in threads if "laptop lid" in m.text]
    assert len(vpn) == 1
    m, later = vpn[0]
    assert any(e.supporter for e in later) and any(e.user == m.user and "works now" in e.text for e in later)


def test_no_draft_when_the_asker_never_speaks_after_the_answer():
    # question 10:17, asker's screenshot 10:18, peer's answer 10:20, then nothing. The order
    # gate is code, not judgement: the screenshot predates the answer and confirms nothing.
    ev = load()
    declined = []
    threads = curate.threads_for_drafts(ev, "dev-platform", unconfirmed=declined)
    assert not any("trace viewer" in m.text for m, _ in threads)
    assert any("trace viewer" in d["miss"].text and "never replied after" in d["why"] for d in declined)


def test_self_answered_thread_counts_only_in_test_group_mode():
    ev = load()
    real = curate.threads_for_drafts(ev, "office-it")
    assert not any("מיקרופון" in m.text for m, _ in real), "one person cannot confirm themselves in a real group"
    test = curate.threads_for_drafts(ev, "office-it", test_groups=(IT_TEST,))
    mic = [(m, later) for m, later in test if "מיקרופון" in m.text]
    assert len(mic) == 1 and any("עבד" in e.text for e in mic[0][1])


def test_open_gaps_honour_test_group_mode_and_find_the_unanswered_question():
    ev = load()
    gaps_real = curate.open_gaps(ev, "office-it")
    assert any("זום" in g.text for g in gaps_real)               # nobody answered the Zoom question
    assert any("מיקרופון" in g.text for g in gaps_real)          # self-answer does not count in a real group
    gaps_test = curate.open_gaps(ev, "office-it", test_groups=(IT_TEST,))
    assert not any("מיקרופון" in g.text for g in gaps_test)


def test_review_flag_when_a_supporter_speaks_soon_after_a_confident_answer():
    ev = load()
    flags = curate.review_flags(ev, "office-it")
    assert len(flags) == 1 and flags[0]["answer"].entry == "outlook_keeps_asking_to_sign_in"


def test_usage_counts_fired_and_never_fired_entries():
    ev = load()
    u = curate.usage(ev, "office-it")
    assert u["kb_size"] == 4
    fired = {eid for eid, _ in u["fired"]}
    assert fired == {"outlook_keeps_asking_to_sign_in"}
    assert {eid for eid, _ in u["never_fired"]} == {"teams_camera_black_screen", "printer_not_found", "wifi_guest_vs_corp"}
    assert u["misses"] >= 3 and u["errors"] == 0
    assert curate.usage(ev, "dev-platform")["errors"] == 2


def test_kbcheck_gate_refuses_new_errors_but_ignores_pre_existing_warnings(monkeypatch):
    good = {"id": "curator_test_entry_ok", "category": "test", "status": "draft",
            "triggers": ["test phrasing one", "test phrasing two", "test phrasing three"], "error_strings": [],
            "answer": "A short test answer that names its subject.", "owner": "x", "source": "test",
            "verified_against": "test", "last_verified": "2026-09-22"}
    ok, _ = curate.kbcheck_ok(good, "office-it")
    assert ok
    bad = dict(good, id="curator_test_entry_bad", answer="תשובה ב*שורת המשימות* לבדיקה, ארוכה מספיק.")
    ok, out = curate.kbcheck_ok(bad, "office-it")
    assert not ok and "R14" in out
    # A base KB that already carries a warning must not block a clean draft.
    base = curate.tenant_kb("office-it")
    base[0] = dict(base[0], triggers=base[0]["triggers"][:2])      # R9 warning on an unrelated entry
    monkeypatch.setattr(curate, "tenant_kb", lambda tid: base)
    ok, out = curate.kbcheck_ok(good, "office-it")
    assert ok, out
    noisy = dict(good, id="curator_test_entry_noisy", triggers=good["triggers"] + ["four", "five", "six", "seven"])
    ok, out = curate.kbcheck_ok(noisy, "office-it")
    assert not ok and "R15" in out, "a draft may not ADD a warning either"
