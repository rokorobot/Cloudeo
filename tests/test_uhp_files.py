"""UHPClient standard file operations (UHP 2026-09-12 Files, Extended class)."""

from email.parser import BytesParser
from email.policy import HTTP

import httpx
import pytest

from cloudeo.uhp.client import UHPClient, UHPHTTPError, UHPProtocolError, UHPTransportError
from cloudeo.uhp.models import UHP_VERSION, UHPFile, UHPFileContent, UHPFileList

HEADERS = {"UHP-Version": UHP_VERSION}


def parse_multipart(request: httpx.Request) -> dict:
    raw = f"Content-Type: {request.headers['Content-Type']}\r\n\r\n".encode() + request.read()
    message = BytesParser(policy=HTTP).parsebytes(raw)
    parts = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        parts[name] = {
            "filename": part.get_filename(),
            "content_type": part.get_content_type(),
            "payload": part.get_payload(decode=True),
        }
    return parts


def client(handler, api_key="test-not-a-real-key"):
    return UHPClient("http://uhp.test/api/harness", api_key, transport=httpx.MockTransport(handler))


# --- Upload ---


async def test_upload_is_multipart_with_version_auth_and_typed_result():
    seen = []
    payload = bytes(range(256)) * 3

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "file_1",
                "object": "file",
                "bytes": len(payload),
                "created_at": 1786400000,
                "filename": ".cloudeo-bridge-input-x.tar.gz",
                "purpose": "user_data",
            },
            headers=HEADERS,
        )

    async with client(handler) as uhp:
        result = await uhp.upload_file(
            ".cloudeo-bridge-input-x.tar.gz", payload, media_type="application/gzip"
        )
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/api/harness/v1/files"
    assert request.headers["UHP-Version"] == UHP_VERSION
    assert request.headers["Authorization"] == "Bearer test-not-a-real-key"
    assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    parts = parse_multipart(request)
    assert parts["file"]["filename"] == ".cloudeo-bridge-input-x.tar.gz"
    assert parts["file"]["content_type"] == "application/gzip"
    assert parts["file"]["payload"] == payload
    assert parts["purpose"]["payload"] == b"user_data"
    assert isinstance(result, UHPFile)
    assert (result.id, result.size, result.object) == ("file_1", len(payload), "file")
    assert result.model_extra["purpose"] == "user_data"
    assert result.protocol_version == UHP_VERSION


async def test_upload_preserves_structured_413():
    body = {
        "error": {
            "type": "invalid_request_error",
            "code": "file_too_large",
            "message": "File exceeds the 25 MiB upload limit.",
            "param": "file",
            "detail": None,
        }
    }
    async with client(lambda r: httpx.Response(413, json=body, headers=HEADERS)) as uhp:
        with pytest.raises(UHPHTTPError) as caught:
            await uhp.upload_file("x.bin", b"x")
    assert (caught.value.http_status, caught.value.code) == (413, "file_too_large")
    assert caught.value.body == body


@pytest.mark.parametrize("headers", [{}, {"UHP-Version": "2026-08-11"}])
async def test_upload_rejects_missing_or_wrong_version(headers):
    reply = httpx.Response(200, json={"id": "file_1", "filename": "x"}, headers=headers)
    async with client(lambda r: reply) as uhp:
        with pytest.raises(UHPProtocolError, match="UHP-Version"):
            await uhp.upload_file("x", b"x")


async def test_upload_requires_filename():
    calls = []
    async with client(lambda r: calls.append(r) or httpx.Response(500)) as uhp:
        with pytest.raises(ValueError):
            await uhp.upload_file("", b"x")
    assert calls == []


# --- Session listing ---


async def test_session_listing_is_typed_and_keeps_extra_fields():
    def handler(request):
        assert request.url.path == "/api/harness/v1/sessions/hsess_1/files"
        assert request.headers["UHP-Version"] == UHP_VERSION
        return httpx.Response(
            200,
            json={
                "session_id": "hsess_1",
                "count": 1,
                "files": [
                    {
                        "object": "file",
                        "id": "wf_abc",
                        "container_id": "hsess_1",
                        "filename": "out.tar.gz",
                        "path": "out.tar.gz",
                        "bytes": 10,
                        "download_url": "https://elsewhere.invalid/x",
                    }
                ],
            },
            headers=HEADERS,
        )

    async with client(handler) as uhp:
        listing = await uhp.list_session_files("hsess_1")
    assert isinstance(listing, UHPFileList)
    item = listing.files[0]
    assert (item.id, item.container_id, item.filename, item.size) == (
        "wf_abc",
        "hsess_1",
        "out.tar.gz",
        10,
    )
    assert item.model_extra["path"] == "out.tar.gz"
    assert listing.model_extra["count"] == 1


async def test_session_listing_rejects_wrong_version_and_keeps_errors():
    async with client(lambda r: httpx.Response(200, json={"files": []})) as uhp:
        with pytest.raises(UHPProtocolError):
            await uhp.list_session_files("hsess_1")
    body = {
        "error": {
            "type": "invalid_request_error",
            "code": "session_not_found",
            "message": "No such session",
        }
    }
    async with client(lambda r: httpx.Response(404, json=body, headers=HEADERS)) as uhp:
        with pytest.raises(UHPHTTPError) as caught:
            await uhp.list_session_files("hsess_x")
    assert caught.value.code == "session_not_found"


# --- Raw download ---


@pytest.mark.parametrize(
    "content",
    [bytes(range(256)) * 4, b'{"looks": "like json"}', b"\xff\xfe\x00not utf8", b""],
)
async def test_download_returns_exact_bytes_never_json_decoded(content):
    def handler(request):
        assert request.url.path == "/api/harness/v1/containers/hsess_1/files/wf_abc/content"
        assert request.headers["UHP-Version"] == UHP_VERSION
        assert request.headers["Authorization"] == "Bearer test-not-a-real-key"
        return httpx.Response(
            200,
            content=content,
            headers={
                **HEADERS,
                "Content-Type": "application/json",
                "Content-Disposition": 'attachment; filename="out.tar.gz"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    async with client(handler) as uhp:
        result = await uhp.download_container_file("hsess_1", "wf_abc")
    assert isinstance(result, UHPFileContent)
    assert type(result.content) is bytes
    assert result.content == content
    assert result.media_type == "application/json"
    assert result.content_disposition == 'attachment; filename="out.tar.gz"'
    assert result.protocol_version == UHP_VERSION


@pytest.mark.parametrize("headers", [{}, {"UHP-Version": "2026-08-11"}])
async def test_download_rejects_missing_or_wrong_version(headers):
    async with client(lambda r: httpx.Response(200, content=b"x", headers=headers)) as uhp:
        with pytest.raises(UHPProtocolError) as caught:
            await uhp.download_container_file("c", "f")
    assert caught.value.code == "protocol_version_mismatch"


async def test_download_preserves_structured_error():
    body = {"error": {"type": "invalid_request_error", "code": "file_not_found", "message": "gone"}}
    async with client(lambda r: httpx.Response(404, json=body, headers=HEADERS)) as uhp:
        with pytest.raises(UHPHTTPError) as caught:
            await uhp.download_container_file("c", "f")
    assert (caught.value.http_status, caught.value.code, caught.value.body) == (
        404,
        "file_not_found",
        body,
    )


async def test_download_enforces_size_limit_while_streaming():
    async with client(lambda r: httpx.Response(200, content=b"x" * 5000, headers=HEADERS)) as uhp:
        with pytest.raises(UHPProtocolError) as caught:
            await uhp.download_container_file("c", "f", max_bytes=4096)
    assert caught.value.code == "content_too_large"


@pytest.mark.parametrize("identifier", ["", ".", ".."])
async def test_download_rejects_unsafe_identifiers(identifier):
    async with client(lambda r: httpx.Response(200, headers=HEADERS)) as uhp:
        with pytest.raises(ValueError):
            await uhp.download_container_file(identifier, "f")


# --- No retries ---


@pytest.mark.parametrize(
    "operation",
    [
        lambda uhp: uhp.upload_file("x", b"x"),
        lambda uhp: uhp.list_session_files("s"),
        lambda uhp: uhp.download_container_file("c", "f"),
    ],
)
async def test_file_operations_do_not_retry(operation):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"error": {"code": "harness_unavailable"}}, headers=HEADERS)

    async with client(handler) as uhp:
        with pytest.raises(UHPHTTPError):
            await operation(uhp)
    assert len(calls) == 1


async def test_download_transport_error_is_structured():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    async with client(handler) as uhp:
        with pytest.raises(UHPTransportError):
            await uhp.download_container_file("c", "f")
