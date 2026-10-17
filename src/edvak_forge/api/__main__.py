"""Start the web API (and the built dashboard, if frontend/dist exists).

    python -m edvak_forge.api            # http://localhost:8000
    PORT=10000 python -m edvak_forge.api # hosting platforms set PORT
"""

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run("edvak_forge.api.app:app", host=os.getenv("HOST", "0.0.0.0"),
                port=int(os.getenv("PORT", "8000")), log_level="info")


if __name__ == "__main__":
    main()
