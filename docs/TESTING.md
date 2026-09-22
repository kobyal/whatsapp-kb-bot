# Testing

Three layers, cheapest first. The latest full run is recorded in
[VALIDATION-2026-09-22.md](VALIDATION-2026-09-22.md).

## 1. Offline, no AWS (seconds, free)

```bash
for t in tenants/*/; do KB_TENANT=$(basename "$t") python3 kb/kbcheck.py --warnings; done
brain/build.sh                       # assembles brain/tenants.json
python3 -m pytest brain/tests curator/tests -q
node --check listener/listener.js && node --check listener/qrserve.js
terraform -chdir=infra/terraform init -backend=false && terraform -chdir=infra/terraform validate
cfn-lint infra/cloudformation/template.yaml
```

`brain/tests/` loads `lambda_function.py` unchanged and replaces only the AWS calls with stubs
that *state the situation* (what the screen said, what score the classifier gave, whether a
supporter just spoke), then asserts the decision:

- `test_conversation_awareness.py`: supporters (never asked, explicit call exempt, id variants,
  zero model calls), quoted replies (question withheld, answer kept), the supporter window,
  `clarify_route2` on/off per tenant, the floor, the gate, the verbatim-error-string bypass.
- `test_direct_message.py`: one-tenant DMs are never asked anything, the tenant comes from the
  roster not the default, a no-match says so, DMs skip the screen, asked once / remembered /
  switched, a failed store asks again rather than guessing, and the group path is unchanged.
- `test_tenants.py`: routing by jid, per-tenant header/questions/prompts/snapshot, RTL only
  where Hebrew appears, table-name derivation, the `{KB_COUNT}` substitution.

`curator/tests/` runs the deterministic parts against `fixture-bot.log`, a hand-written log in
the listener's format with fictional ids: both `BRAIN` line generations, a timeout envelope
and a `BRAIN ERROR` line, 1:1 routing turns, a confirmed thread, an unconfirmed thread (the
order gate), a self-answered thread in a test room, an open gap, and the kbcheck gate that
refuses new errors and *added* warnings but ignores pre-existing ones.

CI (`.github/workflows/validate.yml`) runs all of this on every push.

## 2. The real classifier, offline (cents)

```bash
export AWS_PROFILE=... AWS_REGION=eu-west-1
python3 tools/probe.py "my vpn keeps disconnecting" "docker says the daemon is not running"
python3 tools/probe.py --suite tools/probe-suite.json --md
```

`probe.py` imports the brain unchanged with the KB snapshot and no conversation table, so the
only thing that runs for real is Bedrock: the same screen prompt, catalogue and floor as the
Lambda. Use it to tune triggers and glosses until every intended question clears the floor and
every control stays silent. `probe-suite.json` is the labelled set used for the validation
record (19 cases: 13 intended answers across both tenants, 6 controls: a thanks, an
announcement, an out-of-KB question, a same-topic-different-problem, and two outage questions).

The clarify band shows up as `clarify-band <id> <score>` because there is no conversation
table offline; on the deployed Lambda the same input produces a clarifying question.

## 3. Live, in a test group (a deploy, a QR scan, real money)

Deploy, link the phone, create a private group from the bot account with one human in it
(`listener/tools/create-group.js`), and add that group to the tenant's `groups` and
`test_groups`. Then send the probe-suite messages by hand and read `scripts/logs.sh`. To prove
the curator end to end, seed one thread (a question the bot misses, an answer, a confirmation)
and run `curate.py --include-test-groups --apply-triggers --write-drafts`; the test-group mode
lets the single human play all three roles, which is never right in a real group.

### The 2026-09-11 live test of the first version

Fresh deploy of this repo (Terraform flavour) into a sandbox account, phone linked, a private
group "KB Bot Test" created from the bot account with one human in it. The sample KB of the time
(8 English entries) was the knowledge base. Floor 0.85, `verbatim` mode, no clarify yet.

| # | Message (as typed) | Expected | Got | Confidence | Classifier's reason |
|---|---|---|---|---|---|
| 1 | my vpn keeps disconnecting every 10 minutes since this morning, anyone else? | answer `vpn_not_connecting` | **answer** | 0.85 | VPN disconnection matches typical phrasing |
| 2 | git push gives me: remote: Authentication failed for 'https://…' | answer `git_pat_auth_failed` | **answer** | 0.95 | exact error match |
| 3 | how do I connect the CLI to our Snowflake warehouse? | silent (not in KB) | **silent** | none 0.95 | not in knowledge base |
| 4 | thanks all, the vpn thing sorted itself out after a reboot 🙏 | silent (not a request) | **silent** | none 1.00 | user posting a solution |
| 5 | guys it's not working for me, help | silent (too vague) | **silent** | none 0.95 | too vague, no specific problem |
| 6 | מישהו יודע איך מתקינים את הכלי על ווינדוס? לא מוצא את ההוראות | answer `cli_install_windows` | **answer** | 0.95 | asks how to install on Windows |
| 7 | Heads up everyone: version 1.4.3 is rolling out today, run devtool update… | silent (announcement) | **silent** | none 1.00 | announcement, not a request |
| 8 | docker builds are super slow on my laptop today, like 10x slower than usual | silent (same topic, different problem) | **silent** | none 0.95 | performance issue, not a known problem |
| 9 | *screenshot of* `Cannot connect to the Docker daemon…` + caption "what does this mean??" | answer `docker_daemon_not_running` | **answer** | 0.99 | vision transcribed the error verbatim, exact match |

Reply latency was 3 to 5 seconds for text (1.5-4 s of that is the deliberate jitter) and about
17 seconds for the screenshot. Every reply was sent as a quoted reply. Bedrock cost for the nine
messages: under one cent. Case 1 landed exactly on the floor with the 8-entry KB; with the
current 17-entry KB and more paraphrases the same message scores 0.95 (see the validation
record). Case 5 would today become a clarifying question ("what exactly did you run or click?")
in a tenant with `clarify_route2` on.
