from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

UHP_VERSION = "2026-09-12"
UHPStatus = Literal["in_progress", "completed", "failed", "incomplete", "cancelled"]


class UHPObject(BaseModel):
    """Preserve additive wire fields; record the actual HTTP protocol version."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)
    protocol_version: str | None = Field(default=None, exclude=True)


class UHPDiscovery(UHPObject):
    object: Literal["uhp.discovery"]
    protocol: Literal["uhp"]
    versions: list[str] = Field(min_length=1)
    default_version: str
    conformance_class: Literal["core", "extended", "full"]
    capabilities: dict[str, bool]
    implementation: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_default(self) -> UHPDiscovery:
        if self.default_version not in self.versions:
            raise ValueError("default_version must be advertised in versions")
        return self

    def supports(self, capability: str) -> bool:
        return self.capabilities.get(capability, False)


class UHPHarness(UHPObject):
    id: str
    name: str
    base: str
    default_model: str | None = Field(default=None, alias="defaultModel")
    max_step: int | None = Field(default=None, alias="maxStep")
    timeout_seconds: int | None = Field(default=None, alias="timeoutSeconds")
    # Extra configuration (skills, plugins, MCP, etc.) is retained, not interpreted.


class UHPHarnessList(UHPObject):
    harnesses: list[UHPHarness]


class UHPModel(UHPObject):
    id: str
    available: bool
    label: str | None = None
    backend: str | None = None
    default: bool | None = None


class UHPBackendModels(UHPObject):
    default: str
    models: list[UHPModel]


class UHPModelCatalog(UHPObject):
    backends: dict[str, UHPBackendModels]


class UHPHarnessModels(UHPObject):
    harness_id: str | None = None
    backend: str | None = None
    default: str | None = None
    fallback: str | None = None
    models: list[UHPModel]


class UHPTaskRequest(BaseModel):
    """UHP-native input; configured harness selection goes inside wire metadata."""

    model_config = ConfigDict(extra="forbid")
    input: str | list[dict[str, Any]]
    harness_id: str | None = Field(default=None, min_length=1)
    model: str | None = None
    instructions: str | None = None
    previous_response_id: str | None = None
    max_step: int | None = Field(default=None, gt=0, strict=True)
    timeout_seconds: int | None = Field(default=None, gt=0, strict=True)
    max_output_tokens: int | None = Field(default=None, gt=0, strict=True)
    store: bool = True

    def to_wire(self) -> dict[str, Any]:
        payload = self.model_dump(exclude={"harness_id"}, exclude_none=True)
        payload["stream"] = False
        if self.harness_id is not None:
            payload["metadata"] = {"harness_id": self.harness_id}
        return payload


class UHPErrorDetail(UHPObject):
    type: str
    code: str
    message: str
    param: str | None = None
    detail: dict[str, Any] | None = None


class UHPTaskResult(UHPObject):
    response_id: str = Field(alias="id")
    object: Literal["response"]
    created_at: int
    status: UHPStatus
    model: str
    # Keep future output item types and all partial evidence unchanged.
    output: list[dict[str, Any]]
    error: UHPErrorDetail | None = None
    incomplete_details: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    previous_response_id: str | None = None
    store: bool | None = None

    @property
    def session_id(self) -> str | None:
        value = self.metadata.get("session_id")
        return value if isinstance(value, str) else None


class UHPFile(UHPObject):
    """A UHP file object (upload result or session artifact). Extra fields are kept."""

    id: str = Field(min_length=1)
    filename: str
    object: Literal["file"] | None = None
    container_id: str | None = None
    size: int | None = Field(default=None, ge=0, alias="bytes")
    created_at: int | None = None


class UHPFileList(UHPObject):
    files: list[UHPFile]


@dataclass(frozen=True)
class UHPFileContent:
    """Raw artifact bytes exactly as served; never decoded."""

    content: bytes
    media_type: str | None
    content_disposition: str | None
    protocol_version: str | None
