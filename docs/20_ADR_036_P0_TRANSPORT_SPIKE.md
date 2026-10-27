# ADR-036 P0 spike report: gh-aw workflow-run transport

**Status:** Evidence for ADR-036 (Proposed), recorded 2026-10-27 against the
ADR draft at e10ed16. ADR-036 was revised afterwards to take in these
findings, and it governs where the two differ. The runner repository named
below is private.

Date: 2026-10-27. Scope: unpaid spike. Synthetic candidate only, no AI engine call,
no Anthropic API key, no Cloudeo code or repository touched. Results are judged
separately for **transport**, **isolation**, **integrity** and **agent-sandbox
behavior**, following the P0 section of the ADR-036 draft (rokorobot/Cloudeo#4 @ e10ed16).
**A stub is not an agent.** A deterministic stub run proves the runner-level file
path and the transport. It does not prove what a real agent can do.

## Summary

| Area | Result |
| --- | --- |
| Transport (P0 items 1, 3, 6, 9) | **PASS** on all items |
| Isolation (P0 items 2, 7) | **PASS**; activation checkout stays, as documented and accepted |
| Integrity (P0 item 5 and the integrity check) | **PASS**: digest gate, unchanged-manifest match, tamper detected and run failed closed, `:ro` mount refuses writes (runner level) |
| Agent-sandbox behavior | **UNVERIFIED** (no real agent ran) |
| Engine-dependent facts (usage tokens, model identity) | **UNVERIFIED** (no paid run) |
| Cancellation (P0 item 8) | **PASS**, with ADR consequences |

## Setup

- Runner repo: `rokorobot/cloudeo-gh-aw-runner` (private, created with owner
  confirmation, no project source). Final commit `d57391d`.
- gh-aw CLI pinned `v0.93.5`, `engine.version: "2.1.288"`, AWF `0.28.70`
  (digest-pinned in the lock manifest).
- Synthetic candidate: a generated 299 B tar.gz (`README.txt` + `src/calc.py`),
  sha256 `206aaa5f…cf70d`, published as a release asset.
- All workflows: `workflow_dispatch` only, `permissions: contents: read`,
  `checkout: false`, `network.allowed: []`, `tools.github: false`. Every
  issue-writing safe output and threat detection are disabled, leaving only `noop`.
  `grep -c ": write"` = 0 in every compiled lock. No Work Queue.
- **Stub engine.** With `engine.command` set, the compiler drops the
  `Validate ANTHROPIC_API_KEY` step and the Claude Code installer. gh-aw's
  `claude_harness.cjs` then starts the stub inside the AWF agent container
  (`awf … --container-workdir $GITHUB_WORKSPACE`) in place of Claude Code. No
  inference endpoint is called.

| Workflow | Lock sha256 | Purpose |
| --- | --- | --- |
| `p0-bundle-roundtrip` | `47974166…a38f` | Real Claude engine; refused at activation while no key is set |
| `p0-stub-engine` | `dd9ad917…24f8` | Stub; candidate rw in workspace |
| `p0-stub-readonly` | `87ccf834…de6a` | Stub; candidate mounted `:ro`; token probes; manifest check |
| `p0-stub-tamper` | (commit d57391d) | Stub tampers with a writable candidate; check must catch it |

| Run | Workflow @ sha | run-name | Conclusion |
| --- | --- | --- | --- |
| [40475486261](https://github.com/rokorobot/cloudeo-gh-aw-runner/actions/runs/40475486261) | roundtrip @ c49dd7a | `cloudeo-p0 …-a` | failure (no key, activation) |
| [40475508486](https://github.com/rokorobot/cloudeo-gh-aw-runner/actions/runs/40475508486) | roundtrip @ c49dd7a | `cloudeo-p0 …-cancel` | cancelled (while queued) |
| [40476511716](https://github.com/rokorobot/cloudeo-gh-aw-runner/actions/runs/40476511716) | stub-engine @ ac83057 | `cloudeo-p0-stub …-stub1` | success |
| [40476542522](https://github.com/rokorobot/cloudeo-gh-aw-runner/actions/runs/40476542522) | stub-engine @ ac83057 | `cloudeo-p0-stub …-hold` | cancelled (mid-run) |
| [40476867854](https://github.com/rokorobot/cloudeo-gh-aw-runner/actions/runs/40476867854) | stub-readonly @ 872d4bd | `cloudeo-p0-ro …-ro1` | success |
| [40477906745](https://github.com/rokorobot/cloudeo-gh-aw-runner/actions/runs/40477906745) | stub-tamper @ d57391d | `cloudeo-p0-tamper …-1` | failure (intended: tamper detected) |

## 1. Transport

| P0 item | Verdict | Evidence |
| --- | --- | --- |
| 1. Asset created, read back, digest-verified via API before dispatch, with a credential no job sees | **PASS** | Release asset API returns `digest: sha256:206aaa5f…cf70d`, equal to the local hash. Uploads used the owner's `gh` credential, outside any run |
| 3. Dispatch returns `workflow_run_id`, else `run-name` correlation | **PASS** | See below |
| 6. Delta artifact downloads and hashes; API digest | **PASS** | See below |
| 9. Release and tag deleted after the run | **PASS** | `gh release delete … --cleanup-tag`; release, tag ref and asset all return `404` afterwards |
| `pre-agent-steps` fetch under the network policy | **PASS** | See below |

**Fetch in `pre-agent-steps`.** Custom steps run on the host runner outside the AWF
firewall. Only the engine step is wrapped by `awf`. Under `network.allowed: []`,
run 40476511716 logged:

```
cloudeo-p0 bridge_run_id=p0-20261027T084259Z-stub1 run_id=40476511716 run_attempt=1
runner ImageOS=ubuntu24 ImageVersion=20261023.334.3
input bundle sha256 expected=206aaa5f…cf70d actual=206aaa5f…cf70d
```

**Dispatch.** `POST …/actions/workflows/{id}/dispatches` with
`return_run_details=true` returned `200` with
`{"workflow_run_id":40475486261,"run_url":…,"html_url":…}` on every dispatch.
`run-name` correlation also works (`display_title` = `cloudeo-p0 <bridge_run_id>`).
While a run is `queued`, the title can briefly show the workflow name instead.
`bridge_run_id` stays the primary key. It appears in `run-name`, in the pre-agent
log and in the output `manifest.json`. The response carried
`Deprecation: Tue, 10 Mar 2026` / `Sunset: Fri, 10 Mar 2028` for the default
REST API version.

**Artifact digest.** `GET …/runs/{id}/artifacts` returns `digest`, and it equals
the sha256 of the zip from `…/artifacts/{id}/zip`. Examples:
`cloudeo-output-…-stub1` gave `ef70b14f…cebc` from both, and `usage` gave
`cdc746fa…442a` from both. The digest covers the zip, not the inner
`output-bundle.tar.gz`, so the adapter's own sha256 of the inner bundle governs.

## 2. Isolation

| P0 item | Verdict | Evidence |
| --- | --- | --- |
| 2. Job token stays `contents: read` | **PASS** | Agent `Set up job`: `Contents: read, Metadata: read` |
| Job token cannot write | **PASS** | `POST git/refs` with the job token returned `403 Resource not accessible by integration`; no probe ref exists |
| Job token and draft releases | **Cannot see drafts** | The list showed only the published release; `GET releases/425215951` (draft) returned `403` |
| 7. `checkout: false` removes the agent checkout; the activation checkout stays | **PASS** (as documented) | Activation: `actions/checkout`, `repository: rokorobot/cloudeo-gh-aw-runner`, `sparse-checkout: .github`, `persist-credentials: false`. Runner repo only |
| No write path in compiled jobs | **PASS** | gh-aw's default issue paths had to be disabled explicitly (see reopen item 1); `: write` count 0 in every lock |
| Network from inside the AWF container | Observed | Direct HTTPS from the stub returned `000` for github.com, api.github.com, release-assets, api.anthropic.com and example.com. This shows only that a non-agent process has no direct egress. It does not tell firewall refusal apart from missing proxy config |

## 3. Integrity

| Check | Verdict | Evidence |
| --- | --- | --- |
| Input bundle digest enforced before materializing | **PASS** | `expected=…cf70d actual=…cf70d`; a mismatch exits 1 |
| Before/after manifest unchanged when nothing writes | **PASS** | Run 40476867854: `pre=e03927b5…fac9 post=e03927b5…fac9`, `candidate_changed:false` |
| Before/after check detects a deliberate write by the stub | **PASS** | Run 40477906745: the stub appended to `README.txt`, created `src/planted.py` and ran `chmod 600 src/calc.py`. Post-step: `pre=e03927b5…fac9 post=b54669b3…8d66`, manifest shows `f 600 32 ./src/calc.py`, `f 644 129 ./README.txt`, `f 644 8 ./src/planted.py`, then `##[error]candidate changed during the run; refusing (fail closed)`. Agent job conclusion: failure |
| Read-only mount configurable; refuses writes from a process in the AWF container | **PASS** (runner level) | `sandbox.agent.mounts: ["/srv/cloudeo-candidate:/srv/cloudeo-candidate:ro"]` compiles to `--mount …:ro`. In the container: `/dev/root /srv/cloudeo-candidate ext4 ro,…`. The stub's `touch`, append and `rm` all failed with `Read-only file system`. A separate rw output dir worked |

The manifest covers paths, file types, modes, sizes and sha256. The pre-agent
digest travels as a step output, which the agent cannot change after that step
finishes. The agent step can, however, reach its own `$GITHUB_ENV` and
`$GITHUB_PATH`: they sit under the rw `/home/runner/work/_temp`, and AWF's
`--exclude-env` list doesn't drop them. It could prepend to `PATH` for later
steps. `p0-stub-tamper` therefore calls `/usr/bin/…` absolutely (`/usr` is ro in
the container). Anything a post-step prints is transport, not evidence. The
adapter's hash after download governs. The `$GITHUB_PATH` reachability is
inferred from the mount table and the lock; it was not probed.

## 4. Agent-sandbox behavior: UNVERIFIED

No real agent ran. These properties are therefore **UNVERIFIED**, even though the
stub runs passed:

- what Claude Code inside AWF can actually read and write, including its own
  tool-permission layer (compiled argv: `Edit`, `Write`, `Edit(//tmp/**)`,
  `--permission-mode dontAsk`, cwd = workspace);
- whether the `:ro` candidate mount holds against the agent itself, through its
  own tools;
- the agent's network reach through the AWF api-proxy.

What the stub runs do show, as runner-level facts only: a process started by
gh-aw's harness inside the AWF container runs as `uid=1001(runner)` with the
same mounts the agent gets. It can write `$GITHUB_WORKSPACE`, `/tmp` and `$HOME`
(rw bind mounts of the host, so `post-steps` see those writes). The kernel
refuses its writes to the `:ro` mount. The raw downloaded bundle in
`/tmp/cloudeo-dl` was visible to it.

**Possible engine-free follow-up (not done, scope unchanged):** `engine.command`
is already an engine-free way to run an arbitrary process inside the AWF agent
container under gh-aw's harness. The owner can decide whether a more thorough
probe that way counts as the ADR's "engine-free sandbox test". For example: run
the real `claude` binary's tool layer offline against a local mock endpoint
through `ANTHROPIC_BASE_URL`, or test `$GITHUB_PATH` writes and remount attempts.
Otherwise these items wait for an approved paid run.

## 5. Engine-dependent facts: UNVERIFIED

- **`usage` token data for Claude.** The `usage` artifact exists with the
  expected slots: `agent/token_usage.jsonl` (0 B with the stub),
  `activity/summary.json` (`working_set.measurement_state: "unavailable"`) and
  `aw_session.jsonl`. Whether Claude fills them needs a paid run.
- **Model identity.** Without `engine.model`, the harness argv carried
  `--model claude-sonnet-5`. The model actually served was not observed.

## 6. Cancellation (P0 item 8): PASS

- Mid-run (40476542522): cancel sent while `pre-agent-steps` was holding.
  `POST /cancel` returned `202`. Status went `in_progress` → `queued` →
  `in_progress` → `completed/cancelled` after **100 s**. Jobs: activation
  success, agent cancelled, conclusion failure. The gh-aw `conclusion` job
  (`always()`) runs after the cancel.
- **The cancelled run still uploaded `cloudeo-output-…-hold`**, plus `agent` and
  `usage`, because `always()` post-steps run on cancellation.
- While queued (40475508486), `POST /cancel` returned **`409 Conflict`**. A retry
  seconds later returned `202`, and the run ended `cancelled` with no jobs.

## ADR-036 parts to reopen

1. **Runner isolation.** gh-aw turns on `create-issue`, failure, no-op and
   incomplete issue reporting and a GitHub MCP server by default. They must be
   disabled explicitly with `create-issue: false`, `report-failure-as-issue: false`,
   `report-failed-jobs: false`, `report-missing-tool: false`,
   `report-missing-data: false`, `report-incomplete: false`,
   `noop.report-as-issue: false` and `tools.github: false`. WR-03 should check that
   no compiled job holds a `write` permission.
2. **Cancellation.** A cancelled run can still upload an output artifact, so apply
   only when `conclusion == success` and the `run_attempt` matches. Expect `409`
   on cancel while queued, and up to ~100 s to reach a terminal state.
3. **Inbound transport.** Publish the release before dispatch, because the job
   token cannot see drafts.
4. **Auditor role.** Materialize the candidate outside agent-writable paths and
   mount it `:ro` through `sandbox.agent.mounts`, with a separate rw output dir.
   Keep the manifest check as defense in depth. Whether the mount holds against
   the real agent stays UNVERIFIED (section 4) and blocks binding any role, as
   the ADR already says.
5. **Outbound transport and remote helper.** `post-steps` run as the agent's uid,
   on paths the agent can write, after a step that can reach `$GITHUB_PATH` and
   `$GITHUB_ENV`. Post-steps must use absolute binaries, and the pinned helper
   must come from outside agent-writable paths or be re-hashed before it runs.
   Hashes printed in the run are transport only.
6. **Pinning.** Pin `engine.model`, since the default is a moving alias. Record
   the AWF version and container digests from the lock manifest as part of workflow identity.
7. **Correlation.** Use the dispatch response for the run id, with `run-name` as
   the fallback, tolerating the `queued` title lag. Send an explicit
   `X-GitHub-Api-Version`.

Transport needs no fallback; the orphan transport branch is not needed.

## Cleanup state

All test releases, their tags and the draft are deleted. `p0-tamper-20261027`
and its tag were removed afterwards; the release list is empty and the tag ref
returns 404. The runner repo, its four
workflows and the run logs and artifacts (3-day retention for `cloudeo-output-*`)
remain. `ANTHROPIC_API_KEY` is not set (repo secrets `total_count: 0` at report
time), so `p0-bundle-roundtrip` cannot reach inference.
