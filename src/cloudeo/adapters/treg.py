from __future__ import annotations

import asyncio
import json
import re
import shlex
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from cloudeo.config import Settings
from cloudeo.models import RunRequest, ToolCandidate


class TregError(RuntimeError):
    pass


class TregClient(ABC):
    last_discovery_query: str | None = None
    last_discovery_evidence: dict[str, Any] | None = None
    last_execution_economics: dict[str, Any] | None = None

    @abstractmethod
    async def execute(
        self,
        candidate: ToolCandidate,
        dry_run: bool = False,
    ) -> str:
        raise NotImplementedError

    async def discover(self, request: RunRequest) -> list[ToolCandidate]:
        return []


class MockTregClient(TregClient):
    async def execute(
        self,
        candidate: ToolCandidate,
        dry_run: bool = False,
    ) -> str:
        self.last_execution_economics = {
            "quoted_cost_usd": candidate.quoted_cost_usd,
            "reserved_cost_usd": None,
            "settled_cost_usd": None,
            "latency_ms": 0,
            "call_id": None,
            "provider_requested": candidate.provider,
            "provider_served": candidate.provider,
            "idempotent_replay": False,
        }
        return json.dumps(
            {
                "backend": "mock",
                "tool": candidate.treg_tool_id,
                "method": candidate.method,
                "query": candidate.query,
                "body": candidate.body,
                "dry_run": dry_run,
                "result": f"Mock successful result from {candidate.id}",
            },
            sort_keys=True,
        )


class TregCLIClient(TregClient):
    def __init__(self, settings: Settings):
        self.timeout = settings.treg_timeout_seconds
        self.discovery_limit = max(1, min(settings.treg_discovery_limit, 100))
        self.candidate_limit = max(1, min(settings.treg_candidate_limit, 10))
        self.last_discovery_query = None
        self.last_discovery_evidence = None
        self.last_execution_economics = None

        if settings.treg_repo:
            repo = Path(settings.treg_repo).expanduser()
            if not repo.exists():
                raise TregError(f"CLOUDEO_TREG_REPO does not exist: {repo}")
            self.prefix = ["uv", "run", "--project", str(repo), "treg"]
        else:
            self.prefix = ["treg"]

    async def execute(
        self,
        candidate: ToolCandidate,
        dry_run: bool = False,
    ) -> str:
        command = [*self.prefix, "call", candidate.treg_tool_id]

        if candidate.method != "GET":
            command.extend(["--method", candidate.method])

        for key, value in candidate.query.items():
            command.extend(["--query", f"{key}={_cli_scalar(value)}"])

        if candidate.body:
            command.extend(
                ["--data", json.dumps(candidate.body, separators=(",", ":"))]
            )

        requested_provider = candidate.provider or _provider_from_endpoint(
            candidate.treg_tool_id
        )

        if dry_run:
            self.last_execution_economics = {
                "quoted_cost_usd": candidate.quoted_cost_usd,
                "reserved_cost_usd": None,
                "settled_cost_usd": None,
                "latency_ms": 0,
                "call_id": None,
                "provider_requested": requested_provider,
                "provider_served": None,
                "idempotent_replay": False,
            }
            return "DRY RUN: " + shlex.join(command)

        # Snapshot ledger before the call so a reservation can be identified
        # without confusing it with an older call to the same endpoint.
        before_balance = await self._balance_json_best_effort()

        started = time.perf_counter()
        stdout, stderr = await self._run_capture(command)
        latency_ms = round((time.perf_counter() - started) * 1000)

        after_balance = await self._balance_json_best_effort()
        new_entries = _new_ledger_entries(before_balance, after_balance)

        parsed = _parse_treg_stderr(stderr)
        reserved_micro = _find_new_ledger_amount(
            new_entries,
            candidate.treg_tool_id,
            "reserve",
        )
        settled_micro = _find_new_ledger_amount(
            new_entries,
            candidate.treg_tool_id,
            "settle",
        )

        settled_usd = parsed["settled_cost_usd"]
        if settled_usd is None and settled_micro is not None:
            settled_usd = settled_micro / 1_000_000

        served_provider = _served_provider_from_output(stdout) or requested_provider

        self.last_execution_economics = {
            "quoted_cost_usd": candidate.quoted_cost_usd,
            "reserved_cost_usd": (
                reserved_micro / 1_000_000
                if reserved_micro is not None
                else None
            ),
            "settled_cost_usd": settled_usd,
            "latency_ms": latency_ms,
            "call_id": parsed["call_id"],
            "provider_requested": requested_provider,
            "provider_served": served_provider,
            "idempotent_replay": parsed["idempotent_replay"],
        }

        return stdout

    async def discover(self, request: RunRequest) -> list[ToolCandidate]:
        self.last_discovery_query = None
        evidence: dict[str, Any] = {
            "selected_query": None,
            "capability_anchor": None,
            "queries": [],
            "endpoints": [],
        }
        rows: list[dict[str, Any]] = []

        for query in discovery_queries(request):
            search = await self._catalog_search(query)
            raw_rows = search.get("results") or []
            rows = [row for row in raw_rows if isinstance(row, dict)]
            evidence["queries"].append(
                {
                    "query": query,
                    "count": int(search.get("count") or len(rows)),
                    "total": int(search.get("total") or len(rows)),
                    "outcome": "matched" if rows else "empty",
                }
            )

            if rows:
                self.last_discovery_query = query
                evidence["selected_query"] = query
                break

            adaptive = _near_miss_retry_query(query, search)
            if adaptive and adaptive != query:
                search = await self._catalog_search(adaptive)
                raw_rows = search.get("results") or []
                rows = [row for row in raw_rows if isinstance(row, dict)]
                evidence["queries"].append(
                    {
                        "query": adaptive,
                        "count": int(search.get("count") or len(rows)),
                        "total": int(search.get("total") or len(rows)),
                        "outcome": "matched" if rows else "empty",
                    }
                )
                if rows:
                    self.last_discovery_query = adaptive
                    evidence["selected_query"] = adaptive
                    break

        if not rows:
            self.last_discovery_evidence = evidence
            return []

        endpoint_ids, capability_anchor = _candidate_endpoint_ids(
            rows,
            self.discovery_limit,
        )
        evidence["capability_anchor"] = capability_anchor

        candidates: list[ToolCandidate] = []

        for endpoint_id in endpoint_ids:
            detail = await self._run_json(
                [*self.prefix, "--json", "catalog", "get", endpoint_id]
            )

            candidate, rejection_reason, endpoint_evidence = (
                _candidate_from_catalog_detail_with_reason(request, detail)
            )

            if candidate is None:
                evidence["endpoints"].append(
                    {
                        **endpoint_evidence,
                        "decision": "rejected",
                        "reason": rejection_reason or "Incompatible endpoint.",
                    }
                )
                continue

            evidence["endpoints"].append(
                {
                    **endpoint_evidence,
                    "decision": "accepted",
                    "reason": "Required inputs can be populated from request state.",
                }
            )
            candidates.append(candidate)

            if len(candidates) >= self.candidate_limit:
                break

        self.last_discovery_evidence = evidence
        return candidates

    async def _catalog_search(self, query: str) -> dict[str, Any]:
        return await self._run_json(
            [
                *self.prefix,
                "--json",
                "catalog",
                "search",
                query,
                "--limit",
                str(self.discovery_limit),
            ]
        )

    async def _balance_json_best_effort(self) -> dict[str, Any] | None:
        try:
            return await self._run_json(
                [*self.prefix, "--json", "balance", "--limit", "30"]
            )
        except Exception:
            # Economics enrichment must not convert a successful provider call
            # into a Cloudeo failure.
            return None

    async def _run_capture(self, command: list[str]) -> tuple[str, str]:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout,
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise TregError(f"Treg timed out after {self.timeout}s") from exc

        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()

        if process.returncode != 0:
            raise TregError(
                f"Treg exited {process.returncode}. "
                f"stdout={out[:1000]!r} stderr={err[:1000]!r}"
            )

        return out, err

    async def _run_text(self, command: list[str]) -> str:
        out, _ = await self._run_capture(command)
        return out

    async def _run_json(self, command: list[str]) -> dict[str, Any]:
        out = await self._run_text(command)
        try:
            body = json.loads(out)
        except json.JSONDecodeError as exc:
            raise TregError(
                f"Treg machine-readable command returned non-JSON stdout: {out[:1000]!r}"
            ) from exc

        if not isinstance(body, dict):
            raise TregError(
                "Treg machine-readable command returned a non-object JSON value."
            )
        return body


_MISSING = object()


def discovery_queries(request: RunRequest) -> list[str]:
    objective = request.objective.strip()
    literals: list[str] = []

    for value in request.state.values():
        if isinstance(value, str) and len(value.strip()) >= 2:
            literals.append(value.strip())

    query = objective
    for literal in sorted(set(literals), key=len, reverse=True):
        query = re.sub(re.escape(literal), " ", query, flags=re.IGNORECASE)

    query = _normalize_discovery_language(query)
    query = _clean_query(query)
    queries: list[str] = []

    def add(value: str) -> None:
        value = _clean_query(value)
        value = re.sub(
            r"^(?:the|a|an)\s+",
            "",
            value,
            flags=re.IGNORECASE,
        )
        if len(value) >= 3 and value not in queries:
            queries.append(value)

    add(query)

    if re.search(
        r"\b(work|professional|business)\s+email\b",
        query,
        flags=re.IGNORECASE,
    ):
        add(
            re.sub(
                r"\b(find|get|retrieve|return|lookup|look\s+up)\b",
                " ",
                query,
                flags=re.IGNORECASE,
            )
        )
        add("work email")

    add(
        re.sub(
            r"\b(verified|valid|validated|professional)\b",
            " ",
            query,
            flags=re.IGNORECASE,
        )
    )

    return queries


def _normalize_discovery_language(value: str) -> str:
    replacements = (
        (r"\bprofessional\s+email\s+address\b", "work email"),
        (r"\bprofessional\s+email\b", "work email"),
        (r"\bbusiness\s+email\s+address\b", "work email"),
        (r"\bbusiness\s+email\b", "work email"),
        (r"\bemail\s+address\b", "email"),
    )

    out = value
    for pattern, replacement in replacements:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    return out


def _clean_query(value: str) -> str:
    value = re.sub(r"https?://\S+", " ", value, flags=re.IGNORECASE)
    value = re.sub(
        r"^\s*(?:please\s+)?(?:find|get|retrieve|return|lookup|look\s+up|search\s+for)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:for|at|of|from|using|with)\s*$",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ,.;:-")


def _near_miss_retry_query(
    query: str,
    search: dict[str, Any],
) -> str | None:
    near = search.get("near") or []
    if not isinstance(near, list) or not near:
        return None

    missing_sets: list[set[str]] = []
    for row in near[:3]:
        if not isinstance(row, dict):
            continue
        missing = row.get("missing") or []
        if isinstance(missing, list):
            missing_sets.append(
                {
                    str(token).lower()
                    for token in missing
                    if str(token).strip()
                }
            )

    if not missing_sets:
        return None

    blockers = set.intersection(*missing_sets)
    if not blockers:
        return None

    tokens = re.findall(r"[A-Za-z0-9_.-]+", query)
    kept = [token for token in tokens if token.lower() not in blockers]
    return _clean_query(" ".join(kept))


def _candidate_endpoint_ids(
    rows: list[dict[str, Any]],
    discovery_limit: int,
) -> tuple[list[str], str | None]:
    routed = [
        row
        for row in rows
        if row.get("kind") == "routed" and row.get("capability")
    ]

    if routed:
        routed.sort(
            key=lambda row: float(row.get("score") or 0.0),
            reverse=True,
        )
        anchor = routed[0]
        capability = str(anchor.get("capability"))
        ids: list[str] = []

        for row in rows:
            if (
                row.get("kind") != "routed"
                and row.get("capability") == capability
                and row.get("id")
            ):
                _append_unique(ids, str(row["id"]))

        children = anchor.get("routed_children") or []
        if isinstance(children, list):
            for endpoint_id in children:
                if endpoint_id:
                    _append_unique(ids, str(endpoint_id))

        return (
            ids[: max(discovery_limit * 3, discovery_limit)],
            capability,
        )

    ids: list[str] = []
    for row in rows:
        if row.get("kind") != "routed" and row.get("id"):
            _append_unique(ids, str(row["id"]))

    return (
        ids[: max(discovery_limit * 2, discovery_limit)],
        None,
    )

def candidate_endpoint_ids(
    rows: list[dict[str, Any]],
    discovery_limit: int,
) -> list[str]:
    """Backward-compatible v0.1.2.1 public helper."""
    endpoint_ids, _ = _candidate_endpoint_ids(
        rows,
        discovery_limit,
    )
    return endpoint_ids



def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def candidate_from_catalog_detail(
    request: RunRequest,
    detail: dict[str, Any],
) -> ToolCandidate | None:
    candidate, _, _ = _candidate_from_catalog_detail_with_reason(
        request,
        detail,
    )
    return candidate


def _candidate_from_catalog_detail_with_reason(
    request: RunRequest,
    detail: dict[str, Any],
) -> tuple[ToolCandidate | None, str | None, dict[str, Any]]:
    endpoint = detail.get("endpoint")
    if not isinstance(endpoint, dict):
        return None, "Catalog detail has no endpoint object.", {
            "endpoint_id": "unknown",
            "capability": None,
            "provider": None,
            "quoted_cost_usd": None,
        }

    endpoint_id = str(endpoint.get("id") or "unknown")
    provider = str(endpoint.get("provider") or "") or None
    capability = str(endpoint.get("capability") or "") or None
    quoted_cost_usd = _cost_usd(endpoint.get("cost"))
    evidence = {
        "endpoint_id": endpoint_id,
        "capability": capability,
        "provider": provider,
        "quoted_cost_usd": quoted_cost_usd,
    }

    if endpoint.get("kind") == "routed":
        return None, "Routed parent is capability metadata; Cloudeo selects a concrete child.", evidence

    method = str(endpoint.get("method") or "GET").upper()
    if not endpoint.get("id"):
        return None, "Endpoint has no ID.", evidence

    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        return None, f"Unsupported HTTP method {method}.", evidence

    input_schema = endpoint.get("input") or {}
    if not isinstance(input_schema, dict):
        input_schema = {}

    body_spec = input_schema.get("body") or {}
    query_spec = input_schema.get("queryParams") or input_schema.get("query") or {}
    path_spec = input_schema.get("pathParams") or {}
    header_spec = input_schema.get("headers") or {}

    for name, group in (
        ("body", body_spec),
        ("query", query_spec),
        ("path", path_spec),
        ("headers", header_spec),
    ):
        if not isinstance(group, dict):
            return None, f"Unsupported {name} schema shape.", evidence

    if _has_required(path_spec):
        return None, "Requires path parameters; v0.1.2.2 does not auto-bind them.", evidence

    if _has_required(header_spec):
        return None, "Requires caller headers; v0.1.2.2 does not auto-bind them.", evidence

    body_type = input_schema.get("bodyType")
    if body_spec and body_type not in (None, "json"):
        return None, f"Unsupported body type {body_type!r}.", evidence

    query, query_missing = _bind_param_group(query_spec, request.state)
    if query is None:
        return None, f"Missing required query input: {query_missing}.", evidence

    body, body_missing = _bind_param_group(body_spec, request.state)
    if body is None:
        return None, f"Missing required body input: {body_missing}.", evidence

    query = _normalize_bound_alternatives(query)
    body = _normalize_bound_alternatives(body)

    if (query_spec or body_spec) and not query and not body:
        return None, "No usable endpoint input can be populated from request state.", evidence

    provider_block = detail.get("provider") or {}
    provider_name = (
        provider_block.get("display_name")
        if isinstance(provider_block, dict)
        else None
    )

    candidate = ToolCandidate(
        id=endpoint_id,
        description=_candidate_description(endpoint, provider_name),
        treg_tool_id=endpoint_id,
        method=method,
        query=query,
        body=body,
        provider=provider,
        capability=capability,
        quoted_cost_usd=quoted_cost_usd,
    )
    return candidate, None, evidence


def _bind_param_group(
    specs: dict[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    bound: dict[str, Any] = {}

    for name, raw_spec in specs.items():
        spec = raw_spec if isinstance(raw_spec, dict) else {}
        value = _resolve_param(name, spec, state)
        required = bool(spec.get("required"))

        if value is _MISSING:
            if required:
                return None, name
            continue

        bound[name] = value

    return bound, None


def _normalize_bound_alternatives(
    bound: dict[str, Any],
) -> dict[str, Any]:
    out = dict(bound)

    if "full_name" in out:
        out.pop("first_name", None)
        out.pop("last_name", None)

    if "fullName" in out:
        out.pop("firstName", None)
        out.pop("lastName", None)

    return out


def _resolve_param(
    name: str,
    spec: dict[str, Any],
    state: dict[str, Any],
) -> Any:
    enum = spec.get("enum")
    if isinstance(enum, list) and len(enum) == 1:
        return enum[0]

    if name in state and state[name] not in (None, ""):
        return state[name]

    normalized_state = {
        _norm(key): value
        for key, value in state.items()
        if value not in (None, "")
    }

    normalized_name = _norm(name)
    if normalized_name in normalized_state:
        return normalized_state[normalized_name]

    aliases: dict[str, tuple[str, ...]] = {
        "fullname": (
            "person",
            "fullname",
            "full_name",
            "name",
            "person_name",
        ),
        "domain": (
            "company_domain",
            "domain",
            "website_domain",
            "company_website_domain",
        ),
        "companyurl": (
            "company_domain",
            "company_url",
            "domain",
            "website_domain",
        ),
        "email": (
            "email",
            "work_email",
            "professional_email",
        ),
        "linkedinstandardprofileurl": (
            "linkedin_url",
            "linkedin_profile_url",
            "profile_url",
        ),
        "linkedinurl": (
            "linkedin_url",
            "linkedin_profile_url",
            "profile_url",
        ),
        "profile": (
            "linkedin_url",
            "linkedin_profile_url",
            "profile_url",
        ),
        "profileurl": (
            "profile_url",
            "linkedin_url",
            "linkedin_profile_url",
        ),
        "url": (
            "url",
            "linkedin_url",
            "profile_url",
            "article_url",
        ),
        "company": (
            "company",
            "company_name",
        ),
        "companyname": (
            "company_name",
            "company",
        ),
    }

    for alias in aliases.get(normalized_name, ()):
        if alias in state and state[alias] not in (None, ""):
            return state[alias]

        normalized_alias = _norm(alias)
        if normalized_alias in normalized_state:
            return normalized_state[normalized_alias]

    person = _person_value(state)

    if normalized_name == "firstname" and person:
        parts = person.split()
        if parts:
            return parts[0]

    if normalized_name == "lastname" and person:
        parts = person.split()
        if len(parts) >= 2:
            return " ".join(parts[1:])

    return _MISSING


def _person_value(state: dict[str, Any]) -> str | None:
    for key in ("person", "full_name", "fullName", "name", "person_name"):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _has_required(specs: dict[str, Any]) -> bool:
    return any(
        isinstance(spec, dict) and bool(spec.get("required"))
        for spec in specs.values()
    )


def _candidate_description(
    endpoint: dict[str, Any],
    provider_name: str | None,
) -> str:
    pieces: list[str] = []

    if provider_name:
        pieces.append(f"Provider: {provider_name}.")

    summary = endpoint.get("summary")
    if summary:
        pieces.append(str(summary).rstrip(".") + ".")

    capability = endpoint.get("capability_description")
    if capability:
        pieces.append("Capability: " + str(capability).rstrip(".") + ".")

    usd = _cost_usd(endpoint.get("cost"))
    if usd is not None:
        cost = endpoint.get("cost") or {}
        cost_type = str(cost.get("type") or "call").replace("_", " ")
        pieces.append(f"Approx cost: ${usd:g} ({cost_type}).")

    observed = endpoint.get("observed")
    if isinstance(observed, dict):
        ok_rate = observed.get("ok_rate")
        hit_rate = observed.get("hit_rate")
        p50_ms = observed.get("p50_ms")

        if isinstance(ok_rate, (int, float)):
            pieces.append(f"Observed request success: {_percent(ok_rate)}.")

        if isinstance(hit_rate, (int, float)):
            pieces.append(f"Observed hit rate: {_percent(hit_rate)}.")

        if isinstance(p50_ms, (int, float)):
            speed = (
                f"{p50_ms / 1000:.1f}s"
                if p50_ms >= 1000
                else f"{p50_ms:.0f}ms"
            )
            pieces.append(f"Observed median latency: {speed}.")

    return " ".join(pieces) or str(endpoint.get("id"))


def _cost_usd(cost: Any) -> float | None:
    if not isinstance(cost, dict):
        return None

    usd = cost.get("usd")
    if isinstance(usd, (int, float)):
        return float(usd)

    if cost.get("currency") == "USD":
        value = cost.get("value")
        if isinstance(value, (int, float)):
            return float(value)

    return None


def _parse_treg_stderr(stderr: str) -> dict[str, Any]:
    settled = None
    call_id = None

    charged = re.search(
        r"treg:\s+charged\s+\$([0-9]+(?:\.[0-9]+)?)",
        stderr,
        flags=re.IGNORECASE,
    )
    if charged:
        settled = float(charged.group(1))

    call = re.search(
        r"(?:call id|call_id)\s+([A-Za-z0-9_-]+)",
        stderr,
        flags=re.IGNORECASE,
    )
    if call:
        call_id = call.group(1)

    lowered = stderr.lower()

    replay = (
        "this is a replay" in lowered
        or "nothing new charged" in lowered
        or (
            "idempotent" in lowered
            and "replay" in lowered
        )
    )

    # A replay carries the original call's charge metadata but incurs
    # no new incremental settlement for the current Cloudeo attempt.
    if replay:
        settled = 0.0

    return {
        "settled_cost_usd": settled,
        "call_id": call_id,
        "idempotent_replay": replay,
    }


def _new_ledger_entries(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not after:
        return []

    after_items = ((after.get("entries") or {}).get("items") or [])
    if not isinstance(after_items, list):
        return []

    before_items = []
    if before:
        before_items = ((before.get("entries") or {}).get("items") or [])
        if not isinstance(before_items, list):
            before_items = []

    before_counts: dict[str, int] = {}
    for row in before_items:
        if isinstance(row, dict):
            sig = _ledger_signature(row)
            before_counts[sig] = before_counts.get(sig, 0) + 1

    new: list[dict[str, Any]] = []
    for row in after_items:
        if not isinstance(row, dict):
            continue
        sig = _ledger_signature(row)
        if before_counts.get(sig, 0):
            before_counts[sig] -= 1
        else:
            new.append(row)

    return new


def _ledger_signature(row: dict[str, Any]) -> str:
    if row.get("id") is not None:
        return f"id:{row['id']}"

    stable = {
        "kind": row.get("kind"),
        "amount_micro": row.get("amount_micro"),
        "endpoint_id": row.get("endpoint_id"),
        "created_at": row.get("created_at"),
        "meta": row.get("meta"),
    }
    return json.dumps(stable, sort_keys=True, default=str)


def _find_new_ledger_amount(
    entries: list[dict[str, Any]],
    endpoint_id: str,
    kind: str,
) -> int | None:
    for row in entries:
        if row.get("kind") == kind and row.get("endpoint_id") == endpoint_id:
            amount = row.get("amount_micro")
            if isinstance(amount, int):
                return abs(amount)
    return None


def _served_provider_from_output(stdout: str) -> str | None:
    try:
        body = json.loads(stdout)
    except json.JSONDecodeError:
        return None

    if not isinstance(body, dict):
        return None

    treg_meta = body.get("_treg")
    if isinstance(treg_meta, dict):
        served = treg_meta.get("served_by") or treg_meta.get("provider")
        if served:
            return str(served)

    for key in ("served_by", "provider"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value

    return None


def _provider_from_endpoint(endpoint_id: str) -> str | None:
    first, sep, _ = endpoint_id.partition(".")
    return first if sep else None


def _percent(value: float) -> str:
    pct = value * 100 if value <= 1 else value
    return f"{pct:.0f}%"


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _cli_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_treg_client(settings: Settings) -> TregClient:
    backend = settings.treg_backend.lower()

    if backend == "cli":
        return TregCLIClient(settings)

    if backend == "mock":
        return MockTregClient()

    raise TregError(f"Unsupported Treg backend: {settings.treg_backend}")
