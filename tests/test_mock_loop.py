from pathlib import Path

from cloudeo.adapters.jev import MockJevClient
from cloudeo.adapters.treg import MockTregClient
from cloudeo.config import Settings
from cloudeo.core.controller import Controller
from cloudeo.db.session import Database
from cloudeo.models import RunRequest, ToolCandidate


async def test_mock_control_loop_passes(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        jev_backend="mock",
        treg_backend="mock",
        route_confidence=0.0,
        verify_probability=0.8,
    )
    database = Database(settings)
    await database.init()
    try:
        controller = Controller(settings, MockJevClient(), MockTregClient(), database)
        request = RunRequest(
            objective="Find a work email",
            state={"person": "Ada Example", "company": "Example Robotics"},
            candidates=[
                ToolCandidate(
                    id="hunter",
                    description="Finds professional email addresses",
                    treg_tool_id="hunter.people.email.find",
                    query={"domain": "example.com", "full_name": "Ada Example"},
                ),
                ToolCandidate(
                    id="other",
                    description="Alternative enrichment provider",
                    treg_tool_id="other.people.lookup",
                    query={"name": "Ada Example"},
                ),
            ],
        )
        response = await controller.run(request)
        assert response.status == "passed"
        assert response.attempts
        assert response.attempts[0].verification_probability >= 0.8
    finally:
        await database.engine.dispose()
