from __future__ import annotations

import uvicorn

from cloudeo.config import settings


def run() -> None:
    uvicorn.run("cloudeo.api.app:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
