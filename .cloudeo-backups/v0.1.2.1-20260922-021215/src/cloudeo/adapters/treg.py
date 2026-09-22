from __future__ import annotations

import asyncio
import json
import re
import shlex
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from cloudeo.config import Settings
from cloudeo.models import RunRequest, ToolCandidate


class TregError(RuntimeError):
    pass


class TregClient(ABC):
    last_discovery_query: str | None = None

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
        return json.dumps(
            {
                "backend": "mock",
                "tool": candidate.treg_tool_id,
                "method": candidate.method,
                "query": candidate.query,
                "body": candidate.body,
                "dry_run": dry_run,
                "result": (
                    f"Mock successful result from {candidate.id}"
                ),
            },
            sort_keys=True,
        )


class TregCLIClient(TregClient):
    """Use the user's Treg CLI as Cloudeo's tool/data plane.

    v0.1.2 also uses Treg's machine-readable catalog:
      treg --json catalog search ...
      treg --json catalog get <endpoint>

    Human-formatted CLI output is never parsed.
    """

    def __init__(self, settings: Settings):
        self.timeout = settings.treg_timeout_seconds
        self.discovery_limit = max(
            1,
            min(settings.treg_discovery_limit, 100),
        )
        self.candidate_limit = max(
            1,
            min(settings.treg_candidate_limit, 10),
        )
        self.last_discovery_query = None

        if settings.treg_repo:
            repo = Path(settings.treg_repo).expanduser()
            if not repo.exists():
                raise TregError(
                    f"CLOUDEO_TREG_REPO does not exist: {repo}"
                )
            self.prefix = [
                "uv",
                "run",
                "--project",
                str(repo),
                "treg",
            ]
        else:
            self.prefix = ["treg"]

    async def execute(
        self,
        candidate: ToolCandidate,
        dry_run: bool = False,
    ) -> str:
        command = [
            *self.prefix,
            "call",
            candidate.treg_tool_id,
        ]

        if candidate.method != "GET":
            command.extend(
                ["--method", candidate.method]
            )

        for key, value in candidate.query.items():
            command.extend(
                ["--query", f"{key}={_cli_scalar(value)}"]
            )

        if candidate.body:
            command.extend(
                [
                    "--data",
                    json.dumps(
                        candidate.body,
                        separators=(",", ":"),
                    ),
                ]
            )

        if dry_run:
            return "DRY RUN: " + shlex.join(command)

        return await self._run_text(command)

    async def discover(
        self,
        request: RunRequest,
    ) -> list[ToolCandidate]:
        self.last_discovery_query = None
        rows: list[dict[str, Any]] = []

        for query in discovery_queries(request):
            search = await self._run_json(
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
            raw_rows = search.get("results") or []
            rows = [row for row in raw_rows if isinstance(row, dict)]
            if rows:
                self.last_discovery_query = query
                break

        if not rows:
            return []

        endpoint_ids = candidate_endpoint_ids(rows, self.discovery_limit)
        candidates: list[ToolCandidate] = []

        for endpoint_id in endpoint_ids:
            detail = await self._run_json(
                [
                    *self.prefix,
                    "--json",
                    "catalog",
                    "get",
                    endpoint_id,
                ]
            )
            candidate = candidate_from_catalog_detail(request, detail)
            if candidate is None:
                continue
            candidates.append(candidate)
            if len(candidates) >= self.candidate_limit:
                break

        return candidates

    async def _run_text(
        self,
        command: list[str],
    ) -> str:
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
            raise TregError(
                f"Treg timed out after {self.timeout}s"
            ) from exc

        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()

        if process.returncode != 0:
            raise TregError(
                f"Treg exited {process.returncode}. "
                f"stdout={out[:1000]!r} "
                f"stderr={err[:1000]!r}"
            )

        return out

    async def _run_json(
        self,
        command: list[str],
    ) -> dict[str, Any]:
        out = await self._run_text(command)

        try:
            body = json.loads(out)
        except json.JSONDecodeError as exc:
            raise TregError(
                "Treg machine-readable command returned "
                f"non-JSON stdout: {out[:1000]!r}"
            ) from exc

        if not isinstance(body, dict):
            raise TregError(
                "Treg machine-readable command returned "
                "a non-object JSON value."
            )

        return body



def discovery_queries(request: RunRequest) -> list[str]:
    # Capability discovery must not include runtime entity values.
    objective = request.objective.strip()
    query = objective

    literals = sorted(
        {
            value.strip()
            for value in request.state.values()
            if isinstance(value, str) and len(value.strip()) >= 2
        },
        key=len,
        reverse=True,
    )

    for literal in literals:
        query = re.sub(re.escape(literal), ' ', query, flags=re.IGNORECASE)

    query = re.sub(
        r'\bprofessional\s+email(?:\s+address)?\b',
        'work email',
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r'\bbusiness\s+email(?:\s+address)?\b',
        'work email',
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(r'\s+', ' ', query).strip(' ,.;:-')
    query = re.sub(r'\b(?:for|at|of)\s*$', '', query, flags=re.IGNORECASE).strip()

    out: list[str] = []
    if query:
        out.append(query)

    # Small generic fallback for the capability demonstrated by the live test.
    if re.search(r'\bemail\b', query, flags=re.IGNORECASE):
        if 'work email' not in out:
            out.append('work email')

    return out


def candidate_endpoint_ids(
    rows: list[dict[str, Any]],
    discovery_limit: int,
) -> list[str]:
    # Prefer a routed row as the semantic capability anchor. Cloudeo still
    # executes concrete children itself, so Treg does not make the final route.
    routed = [
        row for row in rows
        if row.get('kind') == 'routed' and row.get('capability')
    ]

    if routed:
        routed.sort(key=lambda row: float(row.get('score') or 0.0), reverse=True)
        anchor = routed[0]
        capability = anchor.get('capability')
        ids: list[str] = []

        for row in rows:
            if (
                row.get('kind') != 'routed'
                and row.get('capability') == capability
                and row.get('id')
                and row['id'] not in ids
            ):
                ids.append(str(row['id']))

        children = anchor.get('routed_children') or []
        if isinstance(children, list):
            for endpoint_id in children:
                endpoint_id = str(endpoint_id)
                if endpoint_id and endpoint_id not in ids:
                    ids.append(endpoint_id)

        return ids[: max(discovery_limit * 3, discovery_limit)]

    return [
        str(row['id'])
        for row in rows
        if row.get('kind') != 'routed' and row.get('id')
    ][: max(discovery_limit * 2, discovery_limit)]


_MISSING = object()


def candidate_from_catalog_detail(
    request: RunRequest,
    detail: dict[str, Any],
) -> ToolCandidate | None:
    """Turn one Treg catalog endpoint into an executable candidate.

    v0.1.2 intentionally supports the safe/common subset:
    - concrete endpoint, not routed parent
    - query params
    - JSON request bodies
    - no required path/header parameters

    A provider whose required inputs cannot be satisfied from request.state
    is discarded before Jev sees it.
    """

    endpoint = detail.get("endpoint")
    if not isinstance(endpoint, dict):
        return None

    if endpoint.get("kind") == "routed":
        return None

    endpoint_id = endpoint.get("id")
    method = str(endpoint.get("method") or "GET").upper()

    if not endpoint_id:
        return None

    if method not in {
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    }:
        return None

    input_schema = endpoint.get("input") or {}
    if not isinstance(input_schema, dict):
        input_schema = {}

    body_spec = input_schema.get("body") or {}
    query_spec = (
        input_schema.get("queryParams")
        or input_schema.get("query")
        or {}
    )
    path_spec = input_schema.get("pathParams") or {}
    header_spec = input_schema.get("headers") or {}

    if not isinstance(body_spec, dict):
        body_spec = {}
    if not isinstance(query_spec, dict):
        query_spec = {}
    if not isinstance(path_spec, dict):
        path_spec = {}
    if not isinstance(header_spec, dict):
        header_spec = {}

    # v0.1.2 execution adapter does not bind required path/header fields.
    if _has_required(path_spec) or _has_required(header_spec):
        return None

    body_type = input_schema.get("bodyType")
    if body_spec and body_type not in (None, "json"):
        return None

    query = _bind_param_group(
        query_spec,
        request.state,
    )
    if query is None:
        return None

    body = _bind_param_group(
        body_spec,
        request.state,
    )
    if body is None:
        return None

    # Optional-only schemas can still mean "one of these fields is required".
    # Do not create an empty provider call.
    if (query_spec or body_spec) and not query and not body:
        return None

    query = _normalize_bound_alternatives(query)
    body = _normalize_bound_alternatives(body)

    provider = detail.get("provider") or {}
    provider_name = (
        provider.get("display_name")
        if isinstance(provider, dict)
        else None
    )

    description = _candidate_description(
        endpoint,
        provider_name,
    )

    return ToolCandidate(
        id=str(endpoint_id),
        description=description,
        treg_tool_id=str(endpoint_id),
        method=method,
        query=query,
        body=body,
    )


def _bind_param_group(
    specs: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any] | None:
    bound: dict[str, Any] = {}

    for name, raw_spec in specs.items():
        spec = raw_spec if isinstance(raw_spec, dict) else {}
        value = _resolve_param(
            name,
            spec,
            state,
        )

        required = bool(spec.get("required"))

        if value is _MISSING:
            if required:
                return None
            continue

        bound[name] = value

    return bound



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
        # Safe provider-mandated constant, e.g. TryKitt realtime=true.
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


def _person_value(
    state: dict[str, Any],
) -> str | None:
    for key in (
        "person",
        "full_name",
        "fullName",
        "name",
        "person_name",
    ):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _has_required(specs: dict[str, Any]) -> bool:
    return any(
        isinstance(spec, dict)
        and bool(spec.get("required"))
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

    cost = endpoint.get("cost")
    if isinstance(cost, dict):
        usd = cost.get("usd")
        if usd is None and cost.get("currency") == "USD":
            usd = cost.get("value")

        if isinstance(usd, (int, float)):
            cost_type = str(
                cost.get("type") or "call"
            ).replace("_", " ")
            pieces.append(
                f"Approx cost: ${float(usd):g} ({cost_type})."
            )

    observed = endpoint.get("observed")
    if isinstance(observed, dict):
        ok_rate = observed.get("ok_rate")
        hit_rate = observed.get("hit_rate")
        p50_ms = observed.get("p50_ms")

        if isinstance(ok_rate, (int, float)):
            pieces.append(
                f"Observed request success: "
                f"{_percent(ok_rate)}."
            )

        if isinstance(hit_rate, (int, float)):
            pieces.append(
                f"Observed hit rate: "
                f"{_percent(hit_rate)}."
            )

        if isinstance(p50_ms, (int, float)):
            if p50_ms >= 1000:
                speed = f"{p50_ms / 1000:.1f}s"
            else:
                speed = f"{p50_ms:.0f}ms"
            pieces.append(
                f"Observed median latency: {speed}."
            )

    return " ".join(pieces) or str(endpoint.get("id"))


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

    raise TregError(
        f"Unsupported Treg backend: {settings.treg_backend}"
    )
