from __future__ import annotations

from typing import Any, Self, TypeVar
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from cloudeo.uhp.models import (
    UHP_VERSION,
    UHPDiscovery,
    UHPHarness,
    UHPHarnessList,
    UHPHarnessModels,
    UHPModelCatalog,
    UHPObject,
    UHPTaskRequest,
    UHPTaskResult,
)

T = TypeVar("T", bound=UHPObject)


class UHPError(RuntimeError):
    """Request/client failure; task failure remains a UHPTaskResult."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        http_status: int | None = None,
        protocol_version: str | None = None,
        body: Any = None,
        detail: Any = None,
        error_type: str | None = None,
        param: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status
        self.protocol_version = protocol_version
        self.requested_version = UHP_VERSION
        self.version_matches = protocol_version == UHP_VERSION
        self.body = body
        self.detail = detail
        self.error_type = error_type
        self.param = param


class UHPHTTPError(UHPError):
    pass


class UHPProtocolError(UHPError):
    pass


class UHPTransportError(UHPError):
    pass


def _identifier(value: str) -> str:
    if not value or value in {".", ".."}:
        raise ValueError("A non-empty resource identifier is required")
    return quote(value, safe="")


class UHPClient:
    """Pinned non-streaming UHP client with no automatic task retries.

    base_url includes the deployment prefix, e.g. /api/harness for CE.
    Discovery sends no credential. A transport timeout does not stop a task.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        url = httpx.URL(base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
        ):
            raise ValueError("base_url must be an HTTP(S) origin with an optional path prefix")
        self._api_key = api_key
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            transport=transport,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=False,
            trust_env=False,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        result_type: type[T],
        *,
        authenticated: bool = True,
        payload: dict[str, Any] | None = None,
        timeout: httpx.Timeout | None = None,
        idempotency_key: str | None = None,
    ) -> T:
        headers = {"UHP-Version": UHP_VERSION}
        if authenticated and self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if idempotency_key is not None:
            if not 1 <= len(idempotency_key) <= 255:
                raise ValueError("Idempotency-Key must have 1 to 255 characters")
            headers["Idempotency-Key"] = idempotency_key
        kwargs: dict[str, Any] = {"headers": headers}
        if payload is not None:
            kwargs["json"] = payload
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise UHPTransportError(
                "UHP transport failed; task execution may still be running.",
                code="transport_error",
                detail={"exception_type": type(exc).__name__},
            ) from exc

        version = response.headers.get("UHP-Version")
        try:
            body = response.json()
        except ValueError:
            body = response.text
        context = {"http_status": response.status_code, "protocol_version": version, "body": body}
        if not response.is_success:
            # Version rejection can legitimately return another version. Keep the
            # server's structured error and the actual header, not a replacement.
            error = body.get("error") if isinstance(body, dict) else None
            error = error if isinstance(error, dict) else {}
            raise UHPHTTPError(
                error.get("message") or "UHP request failed without a structured error message.",
                code=error.get("code") or "http_error",
                detail=error.get("detail"),
                error_type=error.get("type"),
                param=error.get("param"),
                **context,
            )
        if version != UHP_VERSION:
            raise UHPProtocolError(
                "Missing or unexpected UHP-Version response header.",
                code="protocol_version_mismatch",
                **context,
            )
        if not isinstance(body, dict):
            raise UHPProtocolError("Expected a JSON object.", code="invalid_response", **context)
        try:
            result = result_type.model_validate({**body, "protocol_version": version})
        except ValidationError as exc:
            raise UHPProtocolError(
                "Response does not match the UHP schema.",
                code="invalid_response",
                **context,
            ) from exc
        return result

    async def discover(self) -> UHPDiscovery:
        result = await self._request("GET", "v1/uhp", UHPDiscovery, authenticated=False)
        if UHP_VERSION not in result.versions:
            raise UHPProtocolError(
                "Server does not advertise the pinned UHP version.",
                code="unsupported_protocol_version",
                http_status=200,
                protocol_version=result.protocol_version,
                body=result.model_dump(),
                detail={"supported": result.versions},
            )
        return result

    async def list_harnesses(self) -> UHPHarnessList:
        return await self._request("GET", "v1/harnesses", UHPHarnessList)

    async def get_harness(self, harness_id: str) -> UHPHarness:
        return await self._request("GET", f"v1/harnesses/{_identifier(harness_id)}", UHPHarness)

    async def list_models(self) -> UHPModelCatalog:
        return await self._request("GET", "v1/models", UHPModelCatalog)

    async def list_harness_models(self, harness_id: str) -> UHPHarnessModels:
        return await self._request(
            "GET",
            f"v1/harnesses/{_identifier(harness_id)}/models",
            UHPHarnessModels,
        )

    async def run_task(
        self,
        request: UHPTaskRequest,
        *,
        idempotency_key: str | None = None,
    ) -> UHPTaskResult:
        # An absent task budget leaves the server default unknown. Avoid imposing
        # a short read timeout; an explicit budget gets an additional 30s margin.
        read_timeout = request.timeout_seconds + 30.0 if request.timeout_seconds else None
        return await self._request(
            "POST",
            "v1/responses",
            UHPTaskResult,
            payload=request.to_wire(),
            timeout=httpx.Timeout(30.0, connect=10.0, read=read_timeout),
            idempotency_key=idempotency_key,
        )

    async def get_response(self, response_id: str) -> UHPTaskResult:
        return await self._request("GET", f"v1/responses/{_identifier(response_id)}", UHPTaskResult)

    async def cancel_response(self, response_id: str) -> UHPTaskResult:
        return await self._request(
            "POST",
            f"v1/responses/{_identifier(response_id)}/cancel",
            UHPTaskResult,
        )
