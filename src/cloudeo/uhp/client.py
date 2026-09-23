from __future__ import annotations

import json
from typing import Any, Self, TypeVar
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from cloudeo.uhp.models import (
    UHP_VERSION,
    UHPDiscovery,
    UHPFile,
    UHPFileContent,
    UHPFileList,
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

    def _headers(self, *, authenticated: bool, idempotency_key: str | None = None) -> dict:
        headers = {"UHP-Version": UHP_VERSION}
        if authenticated and self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if idempotency_key is not None:
            if not 1 <= len(idempotency_key) <= 255:
                raise ValueError("Idempotency-Key must have 1 to 255 characters")
            headers["Idempotency-Key"] = idempotency_key
        return headers

    @staticmethod
    def _transport_error(exc: httpx.RequestError) -> UHPTransportError:
        return UHPTransportError(
            "UHP transport failed; task execution may still be running.",
            code="transport_error",
            detail={"exception_type": type(exc).__name__},
        )

    @staticmethod
    def _http_error(status: int, version: str | None, body: Any) -> UHPHTTPError:
        # Version rejection can legitimately return another version. Keep the
        # server's structured error and the actual header, not a replacement.
        error = body.get("error") if isinstance(body, dict) else None
        error = error if isinstance(error, dict) else {}
        return UHPHTTPError(
            error.get("message") or "UHP request failed without a structured error message.",
            code=error.get("code") or "http_error",
            detail=error.get("detail"),
            error_type=error.get("type"),
            param=error.get("param"),
            http_status=status,
            protocol_version=version,
            body=body,
        )

    async def _request(
        self,
        method: str,
        path: str,
        result_type: type[T],
        *,
        authenticated: bool = True,
        payload: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        form: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        idempotency_key: str | None = None,
    ) -> T:
        headers = self._headers(authenticated=authenticated, idempotency_key=idempotency_key)
        kwargs: dict[str, Any] = {"headers": headers}
        if payload is not None:
            kwargs["json"] = payload
        if files is not None:
            kwargs["files"] = files
        if form is not None:
            kwargs["data"] = form
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise self._transport_error(exc) from exc

        version = response.headers.get("UHP-Version")
        try:
            body = response.json()
        except ValueError:
            body = response.text
        context = {"http_status": response.status_code, "protocol_version": version, "body": body}
        if not response.is_success:
            raise self._http_error(response.status_code, version, body)
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

    # --- Files (UHP Files, conformance class Extended) ---

    async def upload_file(
        self,
        filename: str,
        content: bytes,
        *,
        media_type: str = "application/octet-stream",
        purpose: str = "user_data",
    ) -> UHPFile:
        """POST /v1/files as multipart/form-data; reference the result as input_file."""
        if not filename:
            raise ValueError("A filename is required")
        return await self._request(
            "POST",
            "v1/files",
            UHPFile,
            files={"file": (filename, content, media_type)},
            form={"purpose": purpose},
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    async def list_session_files(self, session_id: str) -> UHPFileList:
        """GET /v1/sessions/{session_id}/files: the session's artifacts."""
        return await self._request(
            "GET", f"v1/sessions/{_identifier(session_id)}/files", UHPFileList
        )

    async def download_container_file(
        self,
        container_id: str,
        file_id: str,
        *,
        max_bytes: int | None = None,
    ) -> UHPFileContent:
        """GET the raw bytes of one artifact. A successful body is never decoded as JSON.

        max_bytes bounds the download; a larger artifact is refused while streaming.
        """
        path = f"v1/containers/{_identifier(container_id)}/files/{_identifier(file_id)}/content"
        headers = self._headers(authenticated=True)
        try:
            async with self._http.stream("GET", path, headers=headers) as response:
                version = response.headers.get("UHP-Version")
                if not response.is_success:
                    raw = await _read_capped(response, _ERROR_BODY_MAX_BYTES)
                    raise self._http_error(response.status_code, version, _decode_error(raw))
                context = {"http_status": response.status_code, "protocol_version": version}
                media_type = response.headers.get("Content-Type")
                if version != UHP_VERSION:
                    raise UHPProtocolError(
                        "Missing or unexpected UHP-Version response header.",
                        code="protocol_version_mismatch",
                        detail={"content_type": media_type},
                        **context,
                    )
                declared = response.headers.get("Content-Length")
                if (
                    max_bytes is not None
                    and declared is not None
                    and declared.isdigit()
                    and int(declared) > max_bytes
                ):
                    raise UHPProtocolError(
                        "Artifact exceeds the download limit.",
                        code="content_too_large",
                        detail={"limit": max_bytes, "declared": int(declared)},
                        **context,
                    )
                content = await _read_capped(response, max_bytes, strict=True)
        except httpx.RequestError as exc:
            raise self._transport_error(exc) from exc
        return UHPFileContent(
            content=content,
            media_type=media_type,
            content_disposition=response.headers.get("Content-Disposition"),
            protocol_version=version,
        )


_ERROR_BODY_MAX_BYTES = 64 * 1024


async def _read_capped(
    response: httpx.Response, limit: int | None, *, strict: bool = False
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if limit is not None and total > limit:
            if strict:
                raise UHPProtocolError(
                    "Artifact exceeds the download limit.",
                    code="content_too_large",
                    http_status=response.status_code,
                    protocol_version=response.headers.get("UHP-Version"),
                    detail={"limit": limit},
                )
            chunks.append(chunk[: len(chunk) - (total - limit)])
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_error(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", errors="replace")
