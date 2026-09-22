from __future__ import annotations

import uuid
from typing import Any

from cloudeo.adapters.jev import JevClient
from cloudeo.adapters.treg import TregClient
from cloudeo.config import Settings
from cloudeo.core.validators import validate_tool_output
from cloudeo.db.models import RunRecord
from cloudeo.db.session import Database
from cloudeo.execution.base import ExecutionBackend
from cloudeo.execution.contracts import DirectToolExecution
from cloudeo.execution.dispatch import ExecutionDispatcher
from cloudeo.execution.treg_backend import (
    LegacyDirectToolBackend,
    TregDirectToolBackend,
)
from cloudeo.models import (
    AttemptResult,
    ExecutionEconomics,
    RunRequest,
    RunResponse,
    ToolCandidate,
)


class Controller:
    def __init__(
        self,
        settings: Settings,
        jev: JevClient,
        treg: TregClient,
        database: Database,
        *,
        execution_backend: ExecutionBackend | None = None,
        execution_dispatcher: ExecutionDispatcher | None = None,
    ):
        self.settings = settings
        self.jev = jev
        self.treg = treg
        self.database = database
        if execution_backend is not None and execution_dispatcher is not None:
            raise ValueError(
                "Pass execution_backend or execution_dispatcher, not both."
            )
        if execution_dispatcher is None:
            # Treg-only: no harness-task backend is configured here.
            direct_tool = (
                LegacyDirectToolBackend(execution_backend)
                if execution_backend is not None
                else TregDirectToolBackend(treg)
            )
            execution_dispatcher = ExecutionDispatcher(direct_tool=direct_tool)
        self.execution_dispatcher = execution_dispatcher

    async def run(self, request: RunRequest) -> RunResponse:
        run_id = str(uuid.uuid4())

        route_threshold = (
            request.route_confidence
            if request.route_confidence is not None
            else self.settings.route_confidence
        )
        verify_threshold = (
            request.verify_probability
            if request.verify_probability is not None
            else self.settings.verify_probability
        )
        max_attempts = (
            request.max_attempts
            if request.max_attempts is not None
            else self.settings.max_attempts
        )

        candidates = list(request.candidates)
        discovery_used = not candidates
        discovery_query = None
        discovery_evidence = None

        if discovery_used:
            candidates = await self.treg.discover(request)
            discovery_query = (
                getattr(self.treg, "last_discovery_query", None)
                or request.objective
            )
            discovery_evidence = getattr(
                self.treg,
                "last_discovery_evidence",
                None,
            )

        discovered_ids = [candidate.id for candidate in candidates]

        if not candidates:
            response = RunResponse(
                run_id=run_id,
                status="escalate",
                selected_tool=None,
                route_confidence=0.0,
                routing_probabilities={},
                attempts=[],
                reason=(
                    "Automatic Treg discovery found no compatible concrete "
                    "provider whose required inputs could be satisfied from "
                    "the supplied state."
                    if discovery_used
                    else "No tool candidates were supplied."
                ),
                discovery_used=discovery_used,
                discovery_query=discovery_query,
                discovered_candidates=discovered_ids,
                discovery_evidence=discovery_evidence,
            )
            await self._record(request, response)
            return response

        criteria = {
            candidate.id: (
                f"Use Treg tool {candidate.treg_tool_id}. "
                f"{candidate.description} "
                f"Method: {candidate.method}. "
                f"Query parameters: {candidate.query}. "
                f"JSON body: {candidate.body}"
            )
            for candidate in candidates
        }
        criteria["escalate"] = (
            "None of the candidate tools is appropriate or there is not "
            "enough information to choose safely."
        )

        route = await self.jev.decide(
            {
                "objective": request.objective,
                "state": request.state,
                "success_criteria": request.success_criteria,
                "discovery_used": discovery_used,
                "candidate_count": len(candidates),
            },
            {
                "tool_route": {
                    "type": "choice",
                    "instructions": (
                        "Choose the single best next tool for the objective. "
                        "All listed tools passed deterministic input-compatibility "
                        "filtering. Weigh task fit, observed reliability/hit rate, "
                        "price and latency from the option descriptions. Prefer a "
                        "tool that can directly satisfy the objective. Choose "
                        "escalate only if none is suitable."
                    ),
                    "criteria": criteria,
                }
            },
        )

        route_answer = route["answers"]["tool_route"]
        probabilities = {
            str(k): float(v)
            for k, v in (route_answer.get("probabilities") or {}).items()
        }
        choice = str(route_answer.get("choice", "escalate"))
        confidence = float(route_answer.get("confidence") or 0.0)

        if choice == "escalate" or confidence < route_threshold:
            response = RunResponse(
                run_id=run_id,
                status="escalate",
                selected_tool=None,
                route_confidence=confidence,
                routing_probabilities=probabilities,
                attempts=[],
                reason=(
                    "Jev requested escalation."
                    if choice == "escalate"
                    else (
                        f"Routing confidence {confidence:.3f} is below "
                        f"threshold {route_threshold:.3f}."
                    )
                ),
                discovery_used=discovery_used,
                discovery_query=discovery_query,
                discovered_candidates=discovered_ids,
                discovery_evidence=discovery_evidence,
            )
            await self._record(request, response)
            return response

        by_id = {candidate.id: candidate for candidate in candidates}

        ranked = [
            tool_id
            for tool_id, _ in sorted(
                probabilities.items(),
                key=lambda item: item[1],
                reverse=True,
            )
            if tool_id in by_id
        ]

        if choice in by_id and choice not in ranked[:1]:
            ranked.insert(0, choice)

        if not ranked and choice in by_id:
            ranked = [choice]

        # v0.1.2.2: dry-run ends after routing and command construction.
        # It intentionally does not call the verifier or fallback providers.
        if request.dry_run:
            candidate = by_id[choice]
            output, economics = await self._execute_direct_tool(
                candidate,
                dry_run=True,
            )
            attempt = AttemptResult(
                tool_id=choice,
                route_probability=float(probabilities.get(choice, 0.0)),
                output=output,
                deterministic_status="inconclusive",
                deterministic_evidence=[
                    "Dry run: command constructed; provider execution and "
                    "result verification intentionally skipped."
                ],
                verification_source="dry_run",
                verification_probability=0.0,
                passed=False,
                economics=economics,
            )
            response = RunResponse(
                run_id=run_id,
                status="dry_run",
                selected_tool=choice,
                route_confidence=confidence,
                routing_probabilities=probabilities,
                attempts=[attempt],
                reason=(
                    "Dry run completed after discovery, routing, and command "
                    "construction. No provider or verification call was made."
                ),
                discovery_used=discovery_used,
                discovery_query=discovery_query,
                discovered_candidates=discovered_ids,
                discovery_evidence=discovery_evidence,
            )
            await self._record(request, response)
            return response

        attempts: list[AttemptResult] = []

        for tool_id in ranked[:max_attempts]:
            candidate = by_id[tool_id]

            output, economics = await self._execute_direct_tool(
                candidate,
                dry_run=False,
            )

            deterministic = validate_tool_output(
                request,
                candidate,
                output,
            )

            verification_source = "deterministic"

            if deterministic.status == "pass":
                probability = 1.0
                passed = True
            elif deterministic.status == "fail":
                probability = 0.0
                passed = False
            else:
                verification_source = "jev"
                verification = await self.jev.decide(
                    {
                        "objective": request.objective,
                        "success_criteria": request.success_criteria,
                        "original_state": request.state,
                        "selected_tool": candidate.model_dump(),
                        "deterministic_evidence": list(
                            deterministic.evidence
                        ),
                        "tool_output": output[:20000],
                    },
                    {
                        "sufficient": {
                            "type": "noul",
                            "instructions": (
                                "Judge whether tool_output provides enough "
                                "trustworthy evidence to satisfy the objective "
                                "and success_criteria. Use deterministic_evidence "
                                "as additional facts. Do not invent missing "
                                "evidence. Exact identifier matches and explicit "
                                "provider validation signals are strong positive "
                                "evidence when relevant. Return low probability "
                                "for errors, misses, mismatches, contradictions, "
                                "or genuinely insufficient data."
                            ),
                            "criteria": {
                                "true": (
                                    "The requested result is directly supported, "
                                    "relevant identifiers match, and available "
                                    "validation evidence supports completion."
                                ),
                                "false": (
                                    "The result is erroneous, missing, mismatched, "
                                    "contradicted, or insufficient."
                                ),
                            },
                        }
                    },
                )
                probability = float(
                    verification["answers"]["sufficient"].get("noul") or 0.0
                )
                passed = probability >= verify_threshold

            attempts.append(
                AttemptResult(
                    tool_id=tool_id,
                    route_probability=float(
                        probabilities.get(tool_id, 0.0)
                    ),
                    output=output,
                    deterministic_status=deterministic.status,
                    deterministic_evidence=list(
                        deterministic.evidence
                    ),
                    verification_source=verification_source,
                    verification_probability=probability,
                    passed=passed,
                    economics=economics,
                )
            )

            if passed:
                reason = (
                    "Tool result passed deterministic validation; "
                    "Jev verification was unnecessary."
                    if verification_source == "deterministic"
                    else (
                        f"Tool result verified by Jev at {probability:.3f}, "
                        f"meeting threshold {verify_threshold:.3f}."
                    )
                )
                response = RunResponse(
                    run_id=run_id,
                    status="passed",
                    selected_tool=tool_id,
                    route_confidence=confidence,
                    routing_probabilities=probabilities,
                    attempts=attempts,
                    reason=reason,
                    discovery_used=discovery_used,
                    discovery_query=discovery_query,
                    discovered_candidates=discovered_ids,
                    discovery_evidence=discovery_evidence,
                )
                await self._record(request, response)
                return response

        response = RunResponse(
            run_id=run_id,
            status="escalate",
            selected_tool=choice if choice in by_id else None,
            route_confidence=confidence,
            routing_probabilities=probabilities,
            attempts=attempts,
            reason=(
                "No attempted tool produced a result above the "
                "verification threshold."
            ),
            discovery_used=discovery_used,
            discovery_query=discovery_query,
            discovered_candidates=discovered_ids,
            discovery_evidence=discovery_evidence,
        )
        await self._record(request, response)
        return response

    async def _execute_direct_tool(
        self,
        candidate: ToolCandidate,
        *,
        dry_run: bool,
    ) -> tuple[str, ExecutionEconomics | dict[str, Any] | None]:
        outcome = await self.execution_dispatcher.execute(
            DirectToolExecution(candidate=candidate, dry_run=dry_run)
        )
        # The validators keep sole ownership of TREG_ERROR interpretation, so
        # outcome.status is deliberately not consulted here. Runtime status is
        # not verification.
        if outcome.kind != "direct_tool" or outcome.output_text is None:
            raise TypeError("Direct-tool execution returned no output_text.")
        return outcome.output_text, outcome.cost.direct_tool_economics

    async def _record(
        self,
        request: RunRequest,
        response: RunResponse,
    ) -> None:
        record = RunRecord(
            id=response.run_id,
            objective=request.objective,
            status=response.status,
            selected_tool=response.selected_tool,
            route_confidence=response.route_confidence,
            payload_json=request.model_dump_json(),
            result_json=response.model_dump_json(),
        )

        async with self.database.session() as session:
            session.add(record)
            await session.commit()
