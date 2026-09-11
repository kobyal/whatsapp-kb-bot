# Live test, 2026-09-11

Fresh deploy of this repo (Terraform flavour) into a sandbox account, phone linked, a private
group "KB Bot Test" created from the bot account with one human in it. The sample `kb/kb.json`
(8 English entries) was the knowledge base. Floor 0.85, `verbatim` mode.

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

Reply latency was 3 to 5 seconds for text (1.5–4 s of that is the deliberate jitter) and about
17 seconds for the screenshot (Sonnet vision pass plus the classifier). Every reply was sent as
a quoted reply to the triggering message. Bedrock cost for the nine messages: under one cent.

Things the test found that were not in the code:

- Case 1 landed exactly on the 0.85 floor. With a bigger KB and more paraphrases in
  `triggers`, confidence on paraphrases goes up; with the sample KB it is borderline by design.
- The Hebrew question got an English answer because the sample KB is English. Write `answer`
  in the language your group uses; the bot does not translate.
- The account's instance scheduler stopped the listener on the first night. See the README
  section on schedulers; `disable_api_stop` fixed it.
