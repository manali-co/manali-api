"""Azure Functions entry point: the FastAPI app served through the ASGI adapter."""
import sys
from pathlib import Path

# The package lives in src/; the Functions worker only puts wwwroot and .python_packages on the
# path, and an editable install from the remote build does not survive into the runtime image.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import azure.functions as func  # noqa: E402

from manali_api.app import app as fastapi_app  # noqa: E402

app = func.AsgiFunctionApp(app=fastapi_app, http_auth_level=func.AuthLevel.ANONYMOUS)
