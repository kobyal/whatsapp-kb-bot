"""1:1 mode: who may use it, which tenant they get, and the group path staying as it was.

The listener authorises a DM by live group membership and passes `candidate_tenants`; the
brain picks when there is one, asks once when there are several, and treats every DM as an
explicit call (no screen, and a no-match says so instead of staying silent).

Run: python3 -m pytest brain/tests -q
"""
from _load import load, install_stubs

brain = load("brain_dm")

BOTH = "100000000000050@lid"       # a member of both tenants' groups
ONE = "100000000000051@lid"        # dev-platform only
GROUP_IT = "120363000000000011@g.us"


def dm(text, user=ONE, tenants=("dev-platform",)):
    return brain.lambda_handler({"text": text, "jid": user, "participant": user,
                                 "dm": True, "candidate_tenants": list(tenants)}, None)


# ------------------------------------------------- one tenant: never asked anything

def test_a_member_of_one_group_is_answered_with_no_questions():
    install_stubs(brain, score=0.95, kind="specific")
    r = dm("I get an error")
    assert r["outcome"] == "answer" and r["tenant"] == "dev-platform", r["note"]


def test_the_tenant_comes_from_the_roster_not_from_the_default():
    # A DM has no group jid, so resolve_tenant would fall back to the default for everyone.
    install_stubs(brain, score=0.95, kind="specific")
    assert dm("I get an error", tenants=("office-it",))["tenant"] == "office-it"


def test_a_dm_that_matches_nothing_says_so_instead_of_going_silent():
    install_stubs(brain, score=0.0)
    r = dm("something with no answer")
    assert r["outcome"] == "nomatch" and r["reply"], r["note"]


def test_a_dm_skips_the_screen():
    install_stubs(brain, score=0.95, kind="other", is_request=False)   # the screen would say "not a request"
    r = dm("thanks, and also my VPN is broken")
    assert r["outcome"] == "answer" and "screen skipped: explicit call" in r["note"]


# ------------------------------------------------- several tenants: asked once, remembered

def test_someone_in_both_groups_is_asked_which_one():
    install_stubs(brain, score=0.95, kind="specific")
    r = dm("I get an error", user=BOTH, tenants=("dev-platform", "office-it"))
    assert r["outcome"] == "dm_setup", r["note"]
    assert "1  Developer Platform" in r["reply"] and "2  Office IT Help" in r["reply"]


def test_the_choice_is_remembered_and_then_never_asked_again():
    install_stubs(brain, score=0.95, kind="specific")
    both = ("dev-platform", "office-it")
    assert dm("I get an error", BOTH, both)["outcome"] == "dm_setup"
    saved = dm("2", BOTH, both)
    assert saved["outcome"] == "dm_setup" and saved["tenant"] == "office-it", saved["note"]
    for _ in range(3):
        r = dm("I get an error", BOTH, both)
        assert r["outcome"] == "answer" and r["tenant"] == "office-it", r["note"]


def test_one_word_switches_back():
    install_stubs(brain, score=0.95, kind="specific")
    both = ("dev-platform", "office-it")
    dm("1", BOTH, both)
    assert dm("I get an error", BOTH, both)["tenant"] == "dev-platform"
    assert dm("switch", BOTH, both)["outcome"] == "dm_setup"
    assert dm("2", BOTH, both)["tenant"] == "office-it"
    assert dm("I get an error", BOTH, both)["tenant"] == "office-it"


def test_a_choice_that_cannot_be_stored_asks_again_rather_than_guessing():
    install_stubs(brain, score=0.95, kind="specific")

    def boom(*a, **k):
        raise RuntimeError("ddb down")
    brain.dm_pref_set = boom
    r = dm("1", BOTH, ("dev-platform", "office-it"))
    assert r["outcome"] == "dm_setup" and "1  " in r["reply"], r["note"]


# ------------------------------------------------- the group path must not move

def test_a_group_message_is_unchanged_by_any_of_this():
    install_stubs(brain, score=0.95, kind="specific")
    r = brain.lambda_handler({"text": "I get an error", "jid": GROUP_IT, "participant": "someone@lid"}, None)
    assert r["outcome"] == "answer" and r["tenant"] == "office-it", r["note"]


def test_a_group_message_still_goes_silent_on_a_non_request():
    install_stubs(brain, score=0.0, kind="other", is_request=False)
    r = brain.lambda_handler({"text": "thanks", "jid": GROUP_IT, "participant": "someone@lid"}, None)
    assert r["outcome"] == "silent", r["note"]


def test_supporter_suppression_does_not_leak_into_dms():
    # A supporter in a 1:1 is a person asking a question, and must be answered.
    install_stubs(brain, score=0.95, kind="specific")
    r = dm("I get an error", user="100000000000011@lid", tenants=("office-it",))
    assert r["outcome"] == "answer", r["note"]
