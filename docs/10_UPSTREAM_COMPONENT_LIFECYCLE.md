# Cloudeo v2 — Upstream Component Lifecycle

**Status:** Development and operations contract  
**Date:** 2026-09-22

## 1. Purpose

Cloudeo deliberately depends on upstream components that will evolve faster than Cloudeo itself.

Examples:

- LongHorizon-Harness;
- UHP;
- HarnessRouter;
- Jev/jev-ultrafast and the external Jev policy API;
- Codex;
- Claude Code;
- Hermes;
- OpenCode/DeepSeek Harness when enabled;
- Treg.

Cloudeo benefits from those improvements only if updates are evaluated without turning production into an upstream test environment.

## 2. Core rule

> **Detect upstream changes continuously; adopt them deliberately.**

A detected update is not a production update.

## 3. Environment separation

```text
UPSTREAM
   |
   v
Watcher
   |
   v
candidate record
   |
   v
DEVELOPMENT / INTEGRATION ENVIRONMENT
   |
   +--> install/pin candidate
   +--> contract tests
   +--> compatibility tests
   +--> Cloudeo workload benchmark
   +--> regression analysis
   |
   v
promotion decision
  / \
 no  yes
 |    |
 v    v
reject/quarantine    update approved pin
                          |
                          v
                    MAIN / PRODUCTION
```

The upstream watcher must never directly alter the production runtime.

## 4. "Development repo, not PR repo" rule

Candidate upstream versions are evaluated in a dedicated development/integration checkout or environment.

They should **not** be mixed into an unrelated product feature PR.

A promotion into main should be a small, auditable change containing only what is required to adopt the already-tested candidate, for example:

- image digest;
- package lock entry;
- CLI version pin;
- protocol version;
- submodule/commit pin;
- compatibility shim proven in development.

This preserves clean causal evidence: if production regresses, the component promotion is identifiable and reversible.

## 5. Component manifest

Maintain one machine-readable source of truth, for example:

```text
config/upstreams.lock.yaml
```

Proposed shape:

```yaml
uhp:
  source: https://unifiedharnessprotocol.org/
  protocol_version: "2026-09-12"
  status: approved

harnessrouter:
  source: https://github.com/HarnessRouter/harnessrouter
  ref: "<exact tag-or-commit>"
  image_digest: "<sha256:...>"
  status: approved

longhorizon:
  source: https://github.com/AMAP-ML/LongHorizon-Harness
  working_fork: https://github.com/rokorobot/LongHorizon-Harness
  ref: "<exact commit>"
  status: approved

jev_ultrafast:
  source: https://github.com/browser-use/jev-ultrafast
  working_fork: https://github.com/rokorobot/jev-ultrafast
  ref: "<exact commit>"
  status: approved
```

Do not put secrets in this file.

## 6. Watch sources

### UHP

Watch:

- current protocol version;
- changelog;
- schema changes;
- conformance suite changes.

A UHP date-version change is treated like an API compatibility event, not a routine dependency patch.

### HarnessRouter

Watch:

- releases/tags;
- container image;
- protocol support;
- workspace/session behavior;
- migration/backup notes;
- security advisories.

### LongHorizon

Watch:

- releases/tags;
- `AgentAdapter`/Environment protocol changes;
- Manager/Executor/Auditor semantics;
- checkpoint/resume behavior;
- verification hardening.

### Jev

Watch:

- jev-ultrafast code;
- action-space contract;
- API/client changes;
- policy response schema;
- latency/reliability changes;
- version identifiers exposed by the hosted service.

The open-source Jev agent/client and the hosted policy service are separate lifecycle concerns.

### Agent harnesses

For Codex, Claude Code, Hermes, etc. watch:

- CLI version;
- command-line contract;
- authentication behavior;
- available models;
- permissions/sandbox changes;
- MCP/tool behavior;
- output/event behavior relevant to HarnessRouter.

### Treg

Watch:

- catalog schema;
- adapter/API contract;
- provider behavior that affects Cloudeo's direct-capability lane.

## 7. Candidate states

```text
detected
staged
compatible
benchmarking
approved
rejected
quarantined
promoted
rolled_back
```

State transitions are explicit and logged.

## 8. Validation gates

### Gate A — installability

- candidate installs/starts;
- version identity captured;
- configuration loads;
- no unexpected migration destroys current data.

### Gate B — protocol/contract

- UHP conformance expected by Cloudeo still works;
- Cloudeo client contract tests pass;
- LongHorizon adapter tests pass;
- Treg/direct-tool contract tests pass if relevant.

### Gate C — representative workload

Run fixed Cloudeo scenarios:

```text
simple CLI inspection
code modification + tests
audit failure + recovery
harness switch
artifact retrieval
cancellation
budget incomplete
direct Treg capability
```

### Gate D — performance comparison

Compare current approved version vs candidate:

- verified success;
- latency;
- cost;
- incomplete rate;
- failure classes;
- recovery burden.

A candidate does not have to improve every metric. The promotion decision records trade-offs.

### Gate E — rollback

Demonstrate that the previous approved pin can be restored without losing accepted Cloudeo state.

## 9. Promotion policy

Promote only when:

- compatibility gates pass;
- no blocking regression exists for supported WorkOrders;
- any intentional behavior change is documented;
- Performance Memory can distinguish old and new fingerprints;
- rollback is known;
- approval is recorded.

## 10. Parallel versions

Do not assume a new version immediately replaces the old version for every task.

Cloudeo may temporarily expose:

```text
ClaudeCode-vA/profile-1
ClaudeCode-vB/profile-1
```

as separate `ExecutionProfile`s if both are operationally safe.

Performance Memory may then reveal task-specific differences.

Retire the older version when evidence supports it or maintenance cost no longer justifies parallel operation.

## 11. Security and supply-chain rules

- pin immutable commits/digests where practical;
- verify release provenance where available;
- review new privileges, mounts, network access, and secrets requirements;
- do not let an update silently broaden agent permissions;
- do not allow upstream install scripts to modify unrelated production configuration;
- keep provider keys outside repositories;
- retain license/NOTICE obligations for bundled or redistributed code.

## 12. Failure handling

If a candidate fails:

```text
candidate -> rejected/quarantined
approved version -> unchanged
Performance Memory -> candidate test evidence retained
production -> unchanged
```

If a promoted component regresses:

```text
stop new routing to affected profile
  ->
restore previous pin
  ->
retain failed version fingerprint
  ->
record incident
  ->
re-run verification
```

## 13. Automation stages

### Stage 1

Manual watch + documented update checklist.

### Stage 2

Automated detection and candidate report; manual staging.

### Stage 3

Automated dev staging + test execution; manual promotion.

### Stage 4

Automated recommendation based on gates and benchmarks; still explicit promotion for production.

Do not jump directly to unattended production upgrades.

## 14. Upstream change report

Each candidate should produce a compact report:

```text
component
current approved version
candidate version
detected_at
source
change summary
contract test result
compatibility result
benchmark delta
security/permission delta
migration requirement
rollback ref
recommendation: promote | reject | investigate
```

This report becomes part of Cloudeo's engineering evidence.

## 15. Relationship to Performance Memory

These are two different loops.

### Runtime routing loop

Chooses the best execution profile for one task.

### Upstream lifecycle loop

Determines whether a new component version is safe/useful enough to become an eligible execution profile.

They share evidence but have separate authority.

## 16. Initial implementation recommendation

Do not build a large update service first.

Start with:

1. `upstreams.lock.yaml`;
2. one read-only status command;
3. one candidate comparison command;
4. fixed compatibility test suite;
5. fixed benchmark manifest;
6. explicit `promote` operation requiring operator approval.

That is enough to make the update process reproducible.
