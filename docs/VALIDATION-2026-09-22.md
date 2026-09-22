# Validation record, 2026-09-22

What was run against this repo after it was brought level with the production bot (multi-
tenant, conversation awareness, 1:1 mode, bounded Bedrock client, kbcheck R14/R15, the curator,
the new example KBs). Every number below was produced by the command shown, on this tree,
on this date. Nothing here was assumed.

Environment: macOS, Python 3, Node v22.22.0, Terraform v1.10.5, AWS CLI, cfn-lint, Graphviz
`dot`; AWS profile `aws-sandbox-personal-36`, region `eu-west-1`, Bedrock Haiku 4.5 and
Sonnet 4.6 via the `eu.` inference profiles.

## Offline

| Check | Command | Result |
|---|---|---|
| KB, default tenant | `KB_TENANT=dev-platform python3 kb/kbcheck.py --warnings` | **17 entries, 0 errors, 0 warnings** |
| KB, second tenant | `KB_TENANT=office-it python3 kb/kbcheck.py --warnings` | **4 entries, 0 errors, 0 warnings** |
| R15 fires | same, on a copy with 8 triggers on one entry | `warn [R15] vpn_not_connecting: triggers at position 7+ are invisible ... ['seventh phrasing', 'eighth phrasing']` |
| R14 fires | via the curator gate test, `ב*שורת המשימות*` | `ERROR [R14]`, draft refused |
| tenants.json | `brain/build.sh` | `default=dev-platform; dev-platform (17 entries, 2 groups), office-it (4 entries, 2 groups)` |
| Brain tests | `python3 -m pytest brain/tests -q` | **37 passed** (16 conversation awareness, 11 direct message, 10 tenants) |
| Curator tests | `python3 -m pytest curator/tests -q` | **12 passed** |
| Listener syntax | `node --check listener/listener.js && node --check listener/qrserve.js` | pass |
| Listener deps | `cd listener && npm ci --omit=dev` | pass, 128 packages from the lockfile |
| Terraform | `terraform init -backend=false && terraform fmt -check && terraform validate` | init ok, fmt clean, **"Success! The configuration is valid."** |
| Terraform plan | `terraform plan` (sandbox profile, local tfvars) | **Plan: 19 to add, 0 to change, 0 to destroy**, incl. `aws_dynamodb_table.kb["dev-platform"]`, `aws_dynamodb_table.kb["office-it"]`, `aws_dynamodb_table.convo`. **Not applied** (see below) |
| CloudFormation | `aws cloudformation validate-template --template-body file://infra/cloudformation/template.yaml` | accepted |
| CloudFormation lint | `cfn-lint infra/cloudformation/template.yaml` | exit 0 |
| Diagram | `python3 docs/diagrams/architecture.py` | `docs/diagrams/architecture.png` rendered (tenants, 1:1 roster, conversation state, curator) |

## The real classifier against the new example KB

`python3 tools/probe.py --suite tools/probe-suite.json`: the brain module imported unchanged,
KB from the snapshot, no conversation table, Bedrock live. **19/19 as expected on the first
run; no trigger or gloss needed changing.**

| Tenant | Message | Result | Screen |
|---|---|---|---|
| dev-platform | my vpn keeps disconnecting every 10 minutes since this morning, anyone else? | **answer** `vpn_not_connecting` 0.95 | request, on, outage |
| dev-platform | git push gives me: remote: Authentication failed for 'https://git.example.internal/' | **answer** `git_pat_auth_failed` 0.95 | skipped: verbatim KB error string |
| dev-platform | מישהו יודע איך מתקינים את devctl על ווינדוס? לא מוצא את ההוראות | **answer** `cli_install_windows` 0.95 | request, on, specific |
| dev-platform | docker says Cannot connect to the Docker daemon at unix:///var/run/docker.sock, what does this mean?? | **answer** `docker_daemon_not_running` 0.99 | request, on, specific |
| dev-platform | every morning I have to run devctl login again before anything works, is that normal? | **answer** `api_token_expires_overnight` 0.95 | request, on, specific |
| dev-platform | the portal bounces me straight back to the login page after I sign in, it says AADSTS70043 | **answer** `sso_login_loop_stale_session` 0.95 | request, on, specific |
| dev-platform | where does devctl keep its logs on a mac? need to attach them to a ticket | **answer** `where_are_the_logs` 0.95 | request, on, specific |
| dev-platform | the IDE keeps popping up a proxy username/password dialog every minute, super annoying | **answer** `proxy_auth_dialog_407` 0.95 | request, on, specific |
| dev-platform | getting SSL certificate problem: unable to get local issuer certificate when I clone on my new linux vm | **answer** `git_ssl_certificate_problem` 0.95 | skipped: verbatim KB error string |
| dev-platform | how do I get platform access for a new team member who joined yesterday? | **answer** `request_platform_access` 0.95 | request, on, specific |
| dev-platform | thanks all, the vpn thing sorted itself out after a reboot 🙏 | **silent** (not a request, no classify call) | not a request |
| dev-platform | Heads up everyone: devctl 2.16 is rolling out today, run devctl update when you get a chance | **silent** (not a request, no classify call) | not a request |
| dev-platform | how do I connect the CLI to our Snowflake warehouse? | **silent** (off-domain, no classify call) | request, **off** |
| dev-platform | docker builds are super slow on my laptop today, like 10x slower than usual | **silent** (classifier: none 0.00) | request, on, underspecified |
| dev-platform | is the proxy down for everyone right now? | **silent** (classifier: none 0.00) | request, on, outage |
| office-it | אאוטלוק מבקש ממני סיסמה כל פעם שאני פותחת אותו, מה עושים? | **answer** `outlook_keeps_asking_to_sign_in` 0.95 | request, on, specific |
| office-it | לא רואים אותי בטימס, המסך שלי שחור | **answer** `teams_camera_black_screen` 0.95 | request, on, specific |
| office-it | לאיזה wifi אני אמורה לחבר את הלפטופ במשרד? | **answer** `wifi_guest_vs_corp` 0.95 | request, on, specific |
| office-it | מישהו יודע אם המדפסת בקומה 3 עובדת עכשיו? | **silent** (classifier: none 0.00) | request, on, outage |

Token usage per fully classified message: about 3,900 input tokens (screen ~1,030 + classify
~2,870) for the 17-entry tenant, 2,100 for the 4-entry one. `cache_read=0` on every call: the
17-entry catalogue prefix is below Claude Haiku 4.5's prompt-cache minimum, so caching only
starts paying once the KB is roughly twice this size (the production KB, ~40 entries, caches).
The two controls that reached the classifier ("docker builds are slow", "is the proxy down")
would go to the clarify band or silence exactly as intended; the "docker slow" case is
`underspecified`, so a tenant with `clarify_route2` on would ask "where does this happen?".

## The curator, end to end on the fixture log

`curator/tests/fixture-bot.log` is a fictional log in the listener's own format. Run with the
model (Sonnet 4.6 judgements, Haiku re-classification), snapshot KB, test-group mode:

```
KB_TABLE_PREFIX= CONVO_TABLE= python3 curator/curate.py --log curator/tests/fixture-bot.log \
  --days 3 --include-test-groups --apply-triggers --out digest.md
```

- **Tier A, applied.** "vpn drops every time I close the laptop lid, anyone?" re-classified at
  **0.72** on `vpn_not_connecting` (the clarify band). The supporter's reply in the thread was
  judged to give that entry's answer and the asker's "works now, thanks" to accept it. Proposed
  trigger `VPN drops when closing laptop lid`, inserted at position 6, kbcheck clean,
  re-classified at **0.95**, written to `kb.json`. (The authored `kb.json` was then restored;
  the fixture thread is fictional.)
- **Tier B, draft.** The self-answered Teams-microphone thread in the office-it test room became
  `teams_microphone_not_working`, passes kbcheck; only in `--include-test-groups` mode.
- **Order gate.** The trace-viewer thread (question, asker's screenshot, peer's answer, nothing
  after) was declined: "the asker never replied after the answer".
- **Duplicate suppressed.** The first dry run drafted `vpn_drops_on_lid_close` for the same
  thread Tier A had fixed; the curator now declines a thread covered by an applied fix.
- The digest also shows the 1:1 adoption line per tenant, the timeout envelope and `BRAIN ERROR`
  line as 2 brain errors, one review flag and one open gap. Rendered as
  `docs/article/images/09-curator-digest.png`.

Cost of the two curator runs plus the 19-case probe: well under $0.50 of Bedrock.

## Not validated here, and why

- **No deploy, no live WhatsApp test.** `terraform apply` needs a phone to scan a QR and costs
  about $18/month while it runs; it is a decision for the owner. The plan is recorded above; the
  first version of this stack was deployed and tested live on 2026-09-11 (docs/TESTING.md).
- **The 1:1 roster and the conversation-state table against real AWS.** Both are exercised by
  the offline tests with stubs and are ports of code that runs in production; the DynamoDB
  conditional-write rate limit was proven under concurrency there, not re-proven here.
- **Screenshot (vision) path.** No image fixture; the code is unchanged in shape from the version
  tested live on 2026-09-11 (case 9) apart from the fallback model.
- **The CloudFormation flavour was validated and linted, not deployed.**
