"""The bot must not talk over a conversation the humans are already having.

Three signals, each identity or structure and never model judgement:
  (a) `supporters` per tenant: the group's own answerers never get a clarifying question
      (their diagnostic question to a colleague is not a cry for help); an explicit call is exempt.
  (b) `quoted_participant` from the listener: a reply inside a two-person exchange suppresses
      the QUESTION, never an answer above the floor.
  (c) the supporter window: while a supporter was active in the room, no clarifying question.
Plus `clarify_route2` per tenant: the "too vague" question is only worth asking with a dense KB.

Run: python3 -m pytest brain/tests -q
"""
from _load import load, install_stubs

brain = load("brain_ca")

GROUP = "120363000000000011@g.us"     # office-it's real group (route 2 OFF there)
SUPPORTER = "100000000000011@lid"     # office-it's supporter
ASKER = "100000000000099@lid"


def run(text, participant=ASKER, tenant="office-it", **extra):
    ev = {"text": text, "jid": GROUP, "participant": participant, "tenant": tenant}
    ev.update(extra)
    return brain.lambda_handler(ev, None)


# ----------------------------------------------------------- (a) supporters

def test_a_supporters_question_to_a_colleague_is_never_answered():
    install_stubs(brain, score=0.95, kind="specific")
    r = run("is there a yellow bar in Outlook asking you to sign in?", participant=SUPPORTER)
    assert r["outcome"] == "silent", r["note"]
    assert "supporter" in r["note"]


def test_a_supporter_who_calls_the_bot_on_purpose_still_gets_through():
    install_stubs(brain, score=0.95, kind="specific")
    r = run("bot, what is the answer", participant=SUPPORTER, explicit=True)
    assert r["outcome"] == "answer", r["note"]


def test_an_ordinary_member_is_unaffected():
    install_stubs(brain, score=0.95, kind="specific")
    assert run("I get an error")["outcome"] == "answer"


def test_device_suffix_and_bare_id_still_match_the_supporter_list():
    install_stubs(brain)
    for variant in ("100000000000011:12@lid", "100000000000011", "100000000000011@s.whatsapp.net"):
        r = run("some question", participant=variant)
        assert r["outcome"] == "silent" and "supporter" in r["note"], (variant, r["note"])


def test_supporter_path_costs_no_model_call():
    install_stubs(brain, score=0.95, kind="specific")
    r = run("try closing and reopening it", participant=SUPPORTER)
    assert "calls=0" in r["note"], r["note"]


# --------------------------------------------- (b) two-person conversations

def test_a_reply_quoting_another_person_gets_no_clarifying_question():
    install_stubs(brain, score=0.80, kind="specific")      # route 1 would normally ask
    r = run("open.", quoted_participant=SUPPORTER)
    assert r["outcome"] == "silent", r["note"]
    assert "replies to another person" in r["note"]


def test_a_confident_answer_survives_a_quoted_reply():
    install_stubs(brain, score=0.95, kind="specific")
    assert run("open.", quoted_participant=SUPPORTER)["outcome"] == "answer"


def test_a_clarify_is_withheld_while_a_supporter_is_working_the_room():
    install_stubs(brain, score=0.80, kind="specific")
    brain.supporter_recent_secs = lambda *a, **k: 42
    r = run("not working for me")
    assert r["outcome"] == "silent" and "supporter spoke here 42s ago" in r["note"], r["note"]


def test_the_supporter_window_does_not_block_an_answer():
    install_stubs(brain, score=0.95, kind="specific")
    brain.supporter_recent_secs = lambda *a, **k: 42
    assert run("not working for me")["outcome"] == "answer"


# ------------------------------------------------------------- (c) route 2

def test_route_2_is_off_for_the_small_kb_tenant():
    install_stubs(brain, score=0.0, kind="underspecified")
    r = run("it won't load")
    assert r["outcome"] == "silent" and "route 2" in r["note"], r["note"]


def test_route_2_still_runs_for_the_dense_kb_tenant():
    install_stubs(brain, score=0.0, kind="underspecified")
    r = run("I need help with the tool", tenant="dev-platform", jid="120363000000000001@g.us")
    assert r["outcome"] == "clarify" and r["clarify_route"] == "underspecified", r["note"]


def test_route_1_still_clarifies_where_route_2_is_off():
    install_stubs(brain, score=0.80, kind="specific")
    r = run("Outlook asks me to sign in")
    assert r["outcome"] == "clarify" and r["clarify_route"] == "candidate", r["note"]
    assert "לחצתם" in r["reply"]            # the office-it "action" question, in Hebrew, RTL-marked
    assert r["reply"].startswith(brain.RLM)


# ------------------------------------------------------------- the floor and the gate

def test_below_the_band_is_silent_and_reports_the_near_miss():
    install_stubs(brain, score=0.60, kind="specific")
    r = run("something about printers")
    assert r["outcome"] == "silent" and r["suppressed_id"] == "some_entry" and r["suppressed_score"] == 0.6


def test_a_non_request_never_reaches_the_classifier():
    install_stubs(brain, score=0.95, kind="other", is_request=False)
    r = run("thanks all, sorted")
    assert r["outcome"] == "silent" and "no classification attempted" in r["note"]
    assert "calls=1" in r["note"]           # the screen only


def test_no_convo_table_means_no_clarify_but_answers_still_flow():
    install_stubs(brain, score=0.80, kind="specific")
    saved = brain.CONVO_TABLE
    brain.CONVO_TABLE = ""
    try:
        r = run("Outlook asks me to sign in")
        assert r["outcome"] == "silent" and "disabled" in r["note"], r["note"]
        install_stubs(brain, score=0.95, kind="specific")
        assert run("Outlook asks me to sign in")["outcome"] == "answer"
    finally:
        brain.CONVO_TABLE = saved


def test_a_verbatim_error_string_skips_the_screen_and_answers():
    install_stubs(brain, score=0.0, kind="other", is_request=False)
    entry = dict(brain.load_entries()[0][0], error_strings=["Cannot connect to the Docker daemon at unix:///var/run/docker.sock"])
    brain.load_entries = lambda: ([entry], "kb stub (1)")
    r = run("Cannot connect to the Docker daemon at unix:///var/run/docker.sock")
    assert r["outcome"] == "answer" and "verbatim" in r["note"], r["note"]
