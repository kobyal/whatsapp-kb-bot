"""Demo film: a knowledge-base support bot in a chat app. One Manim scene, two languages.

    DEMO_LANG=he python build.py     # Hebrew, right-to-left   -> demo.mp4
    DEMO_LANG=en python build.py     # English, left-to-right  -> demo-en.mp4

Generic chat UI drawn from primitives (no third-party branding). The whole layout mirrors with the
language: in Hebrew the avatar, names and incoming bubbles sit on the right and timestamps on the
left, and in English all of that flips, because a chat app that reads the wrong way round is the
first thing an audience notices. Fictional people and a fictional group. The bot's answers are
shortened from the example KB (tenants/dev-platform/kb.json): vpn_not_connecting,
proxy_auth_dialog_407, git_pat_auth_failed.

Every on-screen string lives in STRINGS below, so a translation is never a second copy of the film.
"""
from manim import *
import os as _os, json as _json

# ---------------------------------------------------------------- palette (generic, green-ish)
WALL = "#e7ede6"        # chat wallpaper
BAR = "#1f5f4f"         # header bar
BUB_IN = "#ffffff"      # other people / bot
BUB_OUT = "#d5f2cf"     # the viewer's own messages
INK = "#1c2422"; MUTED = "#6b7a76"; META = "#8a978f"
ACC = "#2a9d7c"         # accent: quote bar, header line
BG = "#0f1a17"          # film ground
CAP = "#e9f1ee"; CAPM = "#9db8ae"
AMBER = "#f2b84b"

EN = "Helvetica Neue"
HE = "Arial Hebrew"

LANG = _os.environ.get("DEMO_LANG", "he").lower()
if LANG not in ("he", "en"):
    raise SystemExit(f"DEMO_LANG must be 'he' or 'en', not {LANG!r}")
RTL = LANG == "he"
NEAR = RIGHT if RTL else LEFT      # where a line starts: the reading edge
FAR = LEFT if RTL else RIGHT       # the other one

# ---------------------------------------------------------------- every on-screen string
# he first, en second. A film in a second language is a translation here, not a second file.
STRINGS = {
 "typing":        ("{who} מקליד/ה…", "{who} is typing…"),
 "film_title":    ("בוט תמיכה לקבוצות וואטסאפ ולצ'אט פרטי", "A support bot for WhatsApp groups and private chats"),
 "film_sub":      ("עונה רק ממה שבן אדם אימת. אחרת שותק.", "It answers only from what a person has verified. Otherwise it stays quiet."),
 "grp_name":      ("תמיכה בפלטפורמת הפיתוח", "Dev Platform Support"),
 "grp_sub":       ("דנה, יואב, אתם ועוד 41", "Dana, Yoav, you and 41 others"),
 "grp_initials":  ("פת", "DP"),
 "yoav":          ("יואב", "Yoav"),
 "dana":          ("דנה", "Dana"),
 "bot":           ("בוט תמיכה", "Support bot"),
 "bot_sub":       ("מחובר", "online"),
 "bot_initials":  ("בת", "SB"),
 "you":           ("את/ה", "You"),
 "auto":          ("תשובה אוטומטית", "automatic answer"),
 "photo":         ("[תמונה]", "[photo]"),

 "cap1_step":     ("1 · קבוצה", "1 · GROUP"),
 "cap1_title":    ("יש תשובה מאומתת", "A verified answer exists"),
 "cap1_body":     (["חבר שואל בקבוצה.", "הבוט מוצא רשומה שבן אדם אימת", "ועונה כציטוט על ההודעה,", "מסומן כתשובה אוטומטית."],
                   ["A member asks in the group.", "The bot finds an entry a person verified", "and replies quoting the question,", "marked as an automatic answer."]),
 "q1":            (["ה-VPN לא מתחבר לי מהבית,", "נתקע על connecting. רעיונות?"],
                   ["The VPN will not connect from home,", "it hangs on connecting. Any ideas?"]),
 "a1":            (["VPN לא מתחבר — לפי הסדר:",
                    "1. לסגור לגמרי את תוכנת ה-VPN (Quit) ולפתוח מחדש.",
                    "2. לוודא שהפרופיל הוא Corp-Remote, לא Corp-Guest.",
                    "3. עדיין לא? לכבות ולהדליק Wi-Fi,",
                    "או לנסות hotspot מהטלפון."],
                   ["VPN will not connect — in order:",
                    "1. Quit the VPN client fully, then reopen it.",
                    "2. Use the Corp-Remote profile, not Corp-Guest.",
                    "3. Still stuck? Turn Wi-Fi off and on,",
                    "or try your phone's hotspot."]),

 "cap2_step":     ("2 · קבוצה", "2 · GROUP"),
 "cap2_title":    ("אין תשובה מאומתת", "Nothing verified matches"),
 "cap2_body":     (["שום רשומה לא מתאימה.", "הבוט לא אומר כלום.", "בלי ניחושים, בלי רעש של", "\"לא יודע\" בקבוצה עמוסה."],
                   ["No entry fits the question.", "The bot says nothing at all.", "No guessing, and no \"I don't know\"", "noise in a busy group."]),
 "q2":            (["מישהו יודע למה ה-IDE מאבד", "את ה-theme אחרי כל עדכון?"],
                   ["Anyone know why the IDE loses", "its theme after every update?"]),
 "silence":       ("אין תשובה מאומתת  ←  שתיקה", "nothing verified  →  silence"),

 "cap3_step":     ("3 · קבוצה", "3 · GROUP"),
 "cap3_title":    ("גם צילומי מסך", "Screenshots too"),
 "cap3_body":     (["חבר שולח תמונה של השגיאה.", "הבוט קורא את הטקסט שבתמונה", "ומשיב מאותו מאגר —", "ורק ממנו."],
                   ["A member sends a picture of the error.", "The bot reads the text in the image", "and answers from the same KB —", "and only from it."]),
 "q3":            ("זה מה שאני מקבל ב-IDE", "This is what my IDE shows"),
 "a3":            (["החיבור ל-127.0.0.1:3128 נדחה: סוכן הפרוקסי לא רץ.",
                    "1. devctl doctor צריך להדפיס proxy agent: running.",
                    "2. אם לא — להריץ devctl agent start.",
                    "3. ב-IDE, הפרוקסי צריך להיות http://127.0.0.1:3128.",
                    "לא להקליד סיסמה בחלון הזה."],
                   ["Connection to 127.0.0.1:3128 refused —",
                    "the proxy agent is not running.",
                    "1. devctl doctor must print proxy agent: running.",
                    "2. If not, run devctl agent start.",
                    "3. In the IDE, proxy = http://127.0.0.1:3128",
                    "Never type your password in that dialog."]),

 "cap4_step":     ("4 · צ'אט פרטי", "4 · PRIVATE CHAT"),
 "cap4_title":    ("שיחה ישירה עם הבוט", "A direct chat with the bot"),
 "cap4_body":     (["הבוט משרת יותר מקבוצה אחת,", "לכן פעם אחת בשיחה הוא שואל", "לאיזה צוות שייכים.", "ואז עונה בדיוק באותה דרך."],
                   ["The bot serves more than one group,", "so once per chat it asks", "which team you are on.", "Then it answers exactly as before."]),
 "dm_hi":         (["היי, יש לי שאלה"], ["Hi, I have a question"]),
 "dm_which":      (["היי! לאיזה צוות את/ה שייך/ת? השב/י 1 או 2", "1 · צוות פלטפורמה", "2 · צוות דאטה"],
                   ["Hi! Which team are you on? Reply 1 or 2", "1 · Platform team", "2 · Data team"]),
 "dm_thanks":     (["תודה. אפשר לשאול."], ["Thanks. Go ahead and ask."]),
 "q4":            (["git push מבקש ממני סיסמה,", "הטוקן הפסיק לעבוד"],
                   ["git push is asking me for a password,", "the token stopped working"]),
 "a4":            (["שגיאת Authentication failed ב-git push:",
                    "גיט שולח סיסמה במקום טוקן אישי (PAT).",
                    "1. ליצור PAT: תמונת פרופיל > Personal access tokens",
                    "> Generate, scope repo, תוקף 90 יום.",
                    "2. לשמור פעם אחת: devctl git login מבקש את הטוקן",
                    "ושומר אותו במאגר ההרשאות של המערכת.",
                    "3. לנסות שוב את ה-push."],
                   ["Authentication failed on git push:",
                    "git sends a password, not a personal token.",
                    "1. Create a PAT: profile > Personal access",
                    "tokens > Generate, scope repo, 90 days.",
                    "2. devctl git login asks for the token once",
                    "and stores it in the system keychain.",
                    "3. Try the push again."]),

 "cap5_step":     ("5 · צ'אט פרטי", "5 · PRIVATE CHAT"),
 "cap5_title":    ("אין תשובה, בשיחה פרטית", "No answer, in a private chat"),
 "cap5_body":     (["שתיקה כאן תרגיש כמו התעלמות,", "אז הבוט אומר זאת בפשטות —", "ולא ממציא תשובה."],
                   ["Silence here would feel like being ignored,", "so the bot says so plainly —", "and never invents an answer."]),
 "q5":            (["ואיך מגדירים את הפרוקסי", "בתוך Docker?"],
                   ["And how do I set the proxy", "inside Docker?"]),
 "a5":            (["אין לי תשובה מאומתת לזה.", "כדאי לשאול בקבוצה, כדי שבן אדם יעזור."],
                   ["I have no verified answer for that.", "Ask in the group, so a person can help."]),

 "end1":          ("תשובות שבן אדם אימת — או שתיקה.", "Answers a person verified — or silence."),
 "end2":          ("בחשבון ה-AWS שלכם.", "In your own AWS account."),
}


def T(key, **kw):
    v = STRINGS[key][0 if RTL else 1]
    return [x.format(**kw) for x in v] if isinstance(v, list) else v.format(**kw)


# Per language: the beat timings differ between translations, and the Hebrew file is what the
# recorded narration is cut against. One shared marks.json silently retimed the other film.
MARKS = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                      "marks.json" if RTL else f"marks-{LANG}.json")

import html as _html, types as _types, sys as _sys
import manim.mobject.text.text_mobject as _tm
_orig_t2s = _tm.MarkupUtils.text2svg
def _t2s(*a, **kw):
    # MarkupText hardcodes a 600x400 cairo surface and pango_width=500: long lines wrap at 4x size,
    # and RTL lines (right-aligned to pango_width) get clipped off the surface. Widen both together.
    a = list(a); a[10] = 12800; a[11] = 1500; kw["pango_width"] = 12000
    return _orig_t2s(*a, **kw)
_tm.MarkupUtils = _types.SimpleNamespace(text2svg=_t2s, validate=_tm.MarkupUtils.validate)

class Text(MarkupText):
    """MarkupText (Pango layout, correct bidi for Hebrew; plain Text drops RTL glyphs),
    rendered at 4x and scaled down so glyph spacing stays true at small sizes."""
    def __init__(self, text, font_size=DEFAULT_FONT_SIZE, weight=NORMAL, **kw):
        self.plain = text; kw.setdefault("font", EN)
        super().__init__(_html.escape(text), font_size=font_size * 4, weight=weight, **kw); self.scale(0.25)

def is_he(s):
    return any("֐" <= ch <= "׿" for ch in s)

def line(s, fs=21, color=INK, weight=NORMAL):
    if is_he(s): s = "‏" + s      # RLM: keep an RTL base even when the line starts with Latin ("git push ...")
    return Text(s, font_size=fs, color=color, weight=weight, font=HE if is_he(s) else EN)

def para(lines, fs=21, color=INK, buff=0.10):
    """Lines of one bubble. Hebrew paragraphs align right, English left."""
    rtl = is_he(lines[0])
    g = VGroup(*[line(s, fs, color) for s in lines])
    return g.arrange(DOWN, aligned_edge=RIGHT if rtl else LEFT, buff=buff), rtl


# ---------------------------------------------------------------- chat widgets
class Chat:
    """A phone-like chat panel: header, wallpaper, and a growing column of bubbles (RTL layout)."""
    W, H = 7.2, 7.7
    PAD = 0.28

    def __init__(self, scene, title, sub, initials, x=2.7):
        self.s = scene
        self.frame = RoundedRectangle(corner_radius=0.25, width=self.W, height=self.H,
                                      fill_color=WALL, fill_opacity=1, stroke_color="#3a4a45", stroke_width=2
                                      ).move_to(RIGHT * x)
        hdr = Rectangle(width=self.W, height=0.95, fill_color=BAR, fill_opacity=1, stroke_width=0
                        ).align_to(self.frame, UP).align_to(self.frame, LEFT)
        top_mask = RoundedRectangle(corner_radius=0.25, width=self.W, height=0.6, fill_color=BAR,
                                    fill_opacity=1, stroke_width=0).align_to(self.frame, UP).align_to(self.frame, LEFT)
        av = Circle(radius=0.3, fill_color="#8fd3bd", fill_opacity=1, stroke_width=0)
        av_t = Text(initials, font_size=17, color=BAR, weight=BOLD).move_to(av)
        avatar = VGroup(av, av_t).move_to(
            (hdr.get_right() + LEFT * 0.6) if RTL else (hdr.get_left() + RIGHT * 0.6))
        self.title = line(title, 22, "white", BOLD)
        self.sub = line(sub, 15, "#bfe3d6")
        tt = VGroup(self.title, self.sub).arrange(DOWN, aligned_edge=NEAR, buff=0.05
                                                  ).next_to(avatar, FAR, buff=0.25)
        dots = VGroup(*[Dot(radius=0.035, color="white") for _ in range(3)]).arrange(DOWN, buff=0.08
                       ).move_to((hdr.get_left() + RIGHT * 0.45) if RTL else (hdr.get_right() + LEFT * 0.45))
        self.header = VGroup(top_mask, hdr, avatar, tt, dots).set_z_index(5)   # above scrolled bubbles
        cover = Rectangle(width=self.W + 0.3, height=3, fill_color=BG, fill_opacity=1, stroke_width=0
                          ).set_z_index(4).next_to(self.frame, UP, buff=-0.01)   # hides bubbles scrolled past the top
        self.group = VGroup(self.frame, self.header, cover)
        self.bubbles = []
        self.y = hdr.get_bottom()[1] - 0.35      # next bubble's top edge
        self.left = self.frame.get_left()[0] + self.PAD
        self.right = self.frame.get_right()[0] - self.PAD

    def _wrap(self, content, rtl, side, when, mine, quote=False, header=False, name=False):
        # Callers name the side in READING terms: "R" is the far side (other people) in an RTL
        # app. Flip both for a left-to-right one, or incoming messages land on the wrong edge.
        if not RTL:
            side = "L" if side == "R" else "R"
        stamp = Text(when, font_size=13, color=META)
        # A bubble wider than the panel is silently CLIPPED by the frame, and it only shows up
        # when you look at a frame. Translations change line lengths, so this is checked every
        # build: shrink to fit, and say so loudly enough to go and shorten the line instead.
        room = self.W - 2 * self.PAD - 0.42
        if content.width > room:
            print(f"  ! bubble {content.width:.2f} > {room:.2f} units, scaled to fit — shorten: "
                  f"{getattr(content[-1][0], 'plain', '?')[:60]}")
            content.scale(room / content.width)
        w = max(content.width, 1.2) + 0.42
        h = content.height + 0.5
        box = RoundedRectangle(corner_radius=0.16, width=w, height=h,
                               fill_color=BUB_OUT if mine else BUB_IN, fill_opacity=1, stroke_width=0)
        content.move_to(box.get_center() + UP * 0.08)
        if rtl: content.align_to(box, RIGHT).shift(LEFT * 0.21)
        else: content.align_to(box, LEFT).shift(RIGHT * 0.21)
        # The timestamp sits on the trailing edge: bottom-left in RTL, bottom-right in LTR.
        stamp.align_to(box, DOWN).shift(UP * 0.1)
        if RTL: stamp.align_to(box, LEFT).shift(RIGHT * 0.16)
        else: stamp.align_to(box, RIGHT).shift(LEFT * 0.16)
        b = VGroup(box, content, stamp)
        b.align_to([0, self.y, 0], UP)
        if side == "R": b.align_to([self.right, 0, 0], RIGHT)
        else: b.align_to([self.left, 0, 0], LEFT)
        return b

    def bubble(self, lines, side, name=None, quote=None, header=None, when="10:42", fs=21, mine=False):
        body, rtl = para(lines, fs=fs)
        parts = []
        if name:
            parts.append(line(name, 16, ACC, BOLD))
        if header:   # "● תשובה אוטומטית" — dot on the right for RTL
            hp = [Text(header, font_size=15, color=MUTED, font=HE if is_he(header) else EN), Dot(radius=0.045, color=ACC)]
            if not is_he(header): hp.reverse()
            parts.append(VGroup(*hp).arrange(RIGHT, buff=0.1))
        if quote:
            qn, ql = quote
            qtxt = VGroup(line(qn, 15, ACC, BOLD), line(ql, 16, MUTED)).arrange(
                DOWN, aligned_edge=RIGHT if is_he(ql) else LEFT, buff=0.04)
            qbox = RoundedRectangle(corner_radius=0.08, width=max(qtxt.width, body.width) + 0.35,
                                    height=qtxt.height + 0.2, fill_color="#f0f4f2", fill_opacity=1, stroke_width=0)
            bar = Rectangle(width=0.06, height=qbox.height, fill_color=ACC, fill_opacity=1, stroke_width=0
                            ).align_to(qbox, RIGHT if rtl else LEFT).align_to(qbox, UP)
            if is_he(ql): qtxt.align_to(qbox, RIGHT).shift(LEFT * 0.18)
            else: qtxt.align_to(qbox, LEFT).shift(RIGHT * 0.18)
            parts.append(VGroup(qbox, bar, qtxt))
        parts.append(body)
        content = VGroup(*parts).arrange(DOWN, aligned_edge=RIGHT if rtl else LEFT, buff=0.1)
        return self._wrap(content, rtl, side, when, mine)

    def image_bubble(self, mock, side, name=None, caption_line=None, when="10:42", mine=False):
        """A bubble carrying a picture (the `mock` mobject) and an optional one-line Hebrew caption."""
        parts = []
        if name: parts.append(line(name, 16, ACC, BOLD))
        parts.append(mock)
        if caption_line: parts.append(line(caption_line, 20))
        content = VGroup(*parts).arrange(DOWN, aligned_edge=NEAR, buff=0.12)
        return self._wrap(content, RTL, side, when, mine)

    def push(self, b, run_time=0.45):
        """Add a bubble; scroll the column up if it would leave the panel."""
        overflow = (self.frame.get_bottom()[1] + self.PAD) - b.get_bottom()[1]
        if overflow > 0 and self.bubbles:
            self.s.play(*[x.animate.shift(UP * overflow) for x in self.bubbles], run_time=0.35)
            b.shift(UP * overflow); self.y += overflow
        self.s.play(FadeIn(b, shift=UP * 0.15, scale=0.97), run_time=run_time)
        self.bubbles.append(b)
        self.y = b.get_bottom()[1] - 0.18

    def ensure_room(self, mob):
        """Scroll the column up so `mob` (placed under the last bubble) sits inside the panel."""
        overflow = (self.frame.get_bottom()[1] + self.PAD) - mob.get_bottom()[1]
        if overflow > 0:
            self.s.play(*[x.animate.shift(UP * overflow) for x in self.bubbles], run_time=0.35)
            mob.shift(UP * overflow); self.y += overflow

    def typing(self, who, seconds):
        typ = line(T("typing", who=who), 15, "#bfe3d6").move_to(self.sub, aligned_edge=NEAR).set_z_index(6)
        self.sub.set_opacity(0); self.s.add(typ)
        self.s.wait(seconds)
        self.s.remove(typ); self.sub.set_opacity(1)


def screenshot_mock():
    """A generic error dialog, as a member's screenshot would show it. No real product UI."""
    win = RoundedRectangle(corner_radius=0.08, width=4.6, height=1.8, fill_color="#f4f4f6", fill_opacity=1,
                           stroke_color="#b9bec4", stroke_width=1.5)
    tb = Rectangle(width=4.6, height=0.38, fill_color="#dfe3e8", fill_opacity=1, stroke_width=0
                   ).align_to(win, UP).align_to(win, LEFT)
    lights = VGroup(*[Dot(radius=0.05, color=c) for c in ("#e5615c", "#e9b64a", "#5cc46a")]).arrange(RIGHT, buff=0.08
                    ).move_to(tb.get_left() + RIGHT * 0.4)
    title = Text("Connection error", font_size=14, color="#4a5560", weight=BOLD).move_to(tb)
    icon = Circle(radius=0.22, fill_color="#d9534f", fill_opacity=1, stroke_width=0)
    icon_t = Text("!", font_size=24, color="white", weight=BOLD).move_to(icon)
    ic = VGroup(icon, icon_t).move_to(win.get_left() + RIGHT * 0.55 + DOWN * 0.08)
    msg = VGroup(Text("The connection was refused", font_size=16, color="#2b333a", weight=BOLD),
                 Text("(ECONNREFUSED 127.0.0.1:3128)", font_size=14, color="#7a1f1f"),
                 Text("Check your proxy settings and try again.", font_size=13, color="#5d6771")
                 ).arrange(DOWN, aligned_edge=LEFT, buff=0.07).next_to(ic, RIGHT, buff=0.3).shift(UP * 0.06)
    ok = RoundedRectangle(corner_radius=0.06, width=0.9, height=0.34, fill_color="#3b7ddd", fill_opacity=1, stroke_width=0)
    ok_t = Text("OK", font_size=14, color="white", weight=BOLD).move_to(ok)
    okb = VGroup(ok, ok_t).align_to(win, RIGHT).shift(LEFT * 0.2).align_to(win, DOWN).shift(UP * 0.12)
    return VGroup(win, tb, lights, title, ic, msg, okb)


# ---------------------------------------------------------------- captions (left column, Hebrew, right-aligned)
CAP_EDGE = -1.35    # the caption column's inner edge (the chat frame starts at -0.9)
CAP_OUT = -7.0      # its outer edge, for left-to-right text

def caption(step, title, lines, sub_en=None):
    chip = VGroup(RoundedRectangle(corner_radius=0.1, width=2.1, height=0.5, fill_color=ACC, fill_opacity=1,
                                   stroke_width=0), line(step, 17, "white", BOLD))
    chip[1].move_to(chip[0])
    t = line(title, 30, CAP, BOLD)
    body = VGroup(*[line(l, 21, CAPM) for l in lines]).arrange(DOWN, aligned_edge=NEAR, buff=0.14)
    parts = [chip, t, body]
    # The English gloss under a Hebrew caption is for a mixed audience; in the English film the
    # caption IS English, so repeating it would just be the same sentence twice.
    if sub_en and RTL:
        parts.append(VGroup(*[Text(l, font_size=15, color="#6f8a80") for l in sub_en]
                            ).arrange(DOWN, aligned_edge=RIGHT, buff=0.08))
    g = VGroup(*parts).arrange(DOWN, aligned_edge=NEAR, buff=0.3)
    g.move_to([-4.0, 0, 0])
    return g.align_to([CAP_EDGE if RTL else CAP_OUT, 0, 0], NEAR)


class Demo(Scene):
    marks = []; _cur = None

    def beat(self, name):
        """Open a narration beat: closes the previous one at the current time."""
        t = round(self.renderer.time, 2)
        if self._cur is not None: self._cur["end"] = t
        self._cur = {"name": name, "start": t, "t": None, "end": None}
        self.marks.append(self._cur); self._save()

    def mark(self, name=None):
        """Record the frame moment of the open beat (used for frames/*.png)."""
        self._cur["t"] = round(self.renderer.time, 2); self._save()

    def _save(self):
        with open(MARKS, "w") as f: _json.dump(self.marks, f, indent=1, ensure_ascii=False)

    def construct(self):
        self.camera.background_color = BG

        # ---- title beat (~3 s)
        self.beat("title")
        t = line(T("film_title"), 40 if RTL else 34, CAP, BOLD)
        s = line(T("film_sub"), 24 if RTL else 21, CAPM).next_to(t, DOWN, buff=0.35)
        bits = [t, s]
        if RTL:   # a one-line English gloss, for a Hebrew film shown to a mixed audience
            bits.append(Text(STRINGS["film_sub"][1], font_size=16, color="#6f8a80").next_to(s, DOWN, buff=0.3))
        self.play(FadeIn(t, shift=UP * 0.2), run_time=0.7)
        self.play(*[FadeIn(b) for b in bits[1:]], run_time=0.5)
        self.wait(1.4); self.mark()
        self.play(*[FadeOut(b) for b in bits], run_time=0.4)

        # ---- beat 1: group, match -> curated answer
        self.beat("group_answer")
        chat = Chat(self, T("grp_name"), T("grp_sub"), T("grp_initials"))
        cap1 = caption(T("cap1_step"), T("cap1_title"), T("cap1_body"),
                       ["Group: a verified KB entry matches,", "the bot replies quoted and marked automatic."])
        self.play(FadeIn(chat.group), FadeIn(cap1, shift=RIGHT * 0.2), run_time=0.6)
        chat.typing(T("yoav"), 0.8)
        q1 = T("q1")
        chat.push(chat.bubble(q1, "R", name=T("yoav"), when="10:42"))
        self.wait(0.8)
        a1 = chat.bubble(T("a1"), "R", name=T("bot"), header=T("auto"),
                         quote=(T("yoav"), q1[0]), when="10:42", fs=19)
        chat.push(a1, run_time=0.5)
        hl = SurroundingRectangle(a1[1][1], color=AMBER, buff=0.08, corner_radius=0.08, stroke_width=3)
        self.play(Create(hl), run_time=0.4); self.wait(1.5); self.mark()
        self.play(FadeOut(hl), run_time=0.3)

        # ---- beat 2: group, no match -> silence
        self.beat("group_silence")
        cap2 = caption(T("cap2_step"), T("cap2_title"), T("cap2_body"),
                       ["Group: nothing verified matches,", "so the bot stays silent."])
        self.play(FadeOut(cap1, shift=LEFT * 0.2), FadeIn(cap2, shift=RIGHT * 0.2), run_time=0.5)
        chat.typing(T("dana"), 0.7)
        chat.push(chat.bubble(T("q2"), "R", name=T("dana"), when="10:47"))
        self.wait(0.7)
        dots = VGroup(*[Dot(radius=0.06, color=META) for _ in range(3)]).arrange(RIGHT, buff=0.12)
        sil = line(T("silence"), 19, AMBER, BOLD)
        sil.next_to(chat.bubbles[-1], DOWN, buff=0.35).align_to(chat.bubbles[-1], NEAR).shift(FAR * 0.3)
        chat.ensure_room(sil)
        dots.next_to(chat.bubbles[-1], DOWN, buff=0.3).align_to(chat.bubbles[-1], NEAR).shift(FAR * 0.3)
        self.play(FadeIn(dots), run_time=0.3); self.wait(0.6)
        self.play(FadeOut(dots), run_time=0.4)
        self.play(FadeIn(sil), run_time=0.4); self.wait(1.5); self.mark()

        # ---- beat 3: group, a screenshot -> the bot reads it (vision) and answers from the KB
        self.beat("group_screenshot")
        cap3 = caption(T("cap3_step"), T("cap3_title"), T("cap3_body"),
                       ["Group: the bot reads screenshots too (vision)", "and answers from the same KB."])
        self.play(FadeOut(cap2, shift=LEFT * 0.2), FadeOut(sil), *[FadeOut(b) for b in chat.bubbles], run_time=0.5)
        chat.bubbles = []; chat.y = chat.header[1].get_bottom()[1] - 0.35
        self.play(FadeIn(cap3, shift=RIGHT * 0.2), run_time=0.4)
        img = chat.image_bubble(screenshot_mock(), "R", name=T("yoav"), caption_line=T("q3"), when="10:53")
        chat.push(img, run_time=0.5)
        self.wait(0.9)
        a3 = chat.bubble(T("a3"), "R", name=T("bot"), header=T("auto"),
                         quote=(T("yoav"), T("photo")), when="10:53", fs=19)
        chat.push(a3, run_time=0.5)
        hl3 = SurroundingRectangle(a3[1][1], color=AMBER, buff=0.08, corner_radius=0.08, stroke_width=3)
        self.play(Create(hl3), run_time=0.4); self.wait(1.7); self.mark()
        self.play(FadeOut(hl3), run_time=0.3)

        # ---- beat 4: direct chat
        self.beat("dm_answer")
        cap4 = caption(T("cap4_step"), T("cap4_title"), T("cap4_body"),
                       ["Direct chat: asks once which team,", "then answers the same way."])
        self.play(FadeOut(cap3, shift=LEFT * 0.2), FadeOut(chat.group), *[FadeOut(b) for b in chat.bubbles],
                  run_time=0.5)
        dm = Chat(self, T("bot"), T("bot_sub"), T("bot_initials"))
        self.play(FadeIn(dm.group), FadeIn(cap4, shift=RIGHT * 0.2), run_time=0.5)
        dm.push(dm.bubble(T("dm_hi"), "L", when="11:05", mine=True))
        self.wait(0.4)
        dm.push(dm.bubble(T("dm_which"), "R", when="11:05", fs=19))
        self.wait(0.7)
        dm.push(dm.bubble(["2"], "L", when="11:05", mine=True))
        self.wait(0.4)
        dm.push(dm.bubble(T("dm_thanks"), "R", when="11:05", fs=19))
        self.wait(0.4)
        q4 = T("q4")
        dm.push(dm.bubble(q4, "L", when="11:06", mine=True))
        self.wait(0.7)
        dm.push(dm.bubble(T("a4"), "R", header=T("auto"), quote=(T("you"), q4[0]), when="11:06", fs=19))
        self.wait(1.7); self.mark()

        # ---- beat 5: direct chat, no match -> honest text
        self.beat("dm_nomatch")
        cap5 = caption(T("cap5_step"), T("cap5_title"), T("cap5_body"),
                       ["Direct chat, no match: says so plainly,", "never invents an answer."])
        self.play(FadeOut(cap4, shift=LEFT * 0.2), FadeIn(cap5, shift=RIGHT * 0.2), run_time=0.5)
        dm.push(dm.bubble(T("q5"), "L", when="11:08", mine=True))
        self.wait(0.8)
        nm = dm.bubble(T("a5"), "R", when="11:08", fs=19)
        dm.push(nm)
        hl2 = SurroundingRectangle(nm[0], color=AMBER, buff=0.06, corner_radius=0.16, stroke_width=3)
        self.play(Create(hl2), run_time=0.4); self.wait(1.7); self.mark()

        # ---- end card
        self.beat("end_card")
        self.play(FadeOut(hl2), FadeOut(cap5), FadeOut(dm.group), *[FadeOut(b) for b in dm.bubbles], run_time=0.5)
        e1 = line(T("end1"), 44 if RTL else 38, CAP, BOLD)
        e2 = line(T("end2"), 30 if RTL else 26, CAPM)
        e3 = Text("github.com/kobyal/whatsapp-kb-bot", font_size=26, color=ACC)
        card = VGroup(e1, e2, e3).arrange(DOWN, buff=0.45)
        self.play(FadeIn(e1, shift=UP * 0.2), run_time=0.6); self.play(FadeIn(e2), FadeIn(e3), run_time=0.5)
        self.wait(2.0); self.mark()
        self.wait(0.3)
        self._cur["end"] = round(self.renderer.time + 1 / config.frame_rate, 2); self._save()
