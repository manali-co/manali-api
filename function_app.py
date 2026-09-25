"""Azure Functions entry point: the FastAPI app served through the ASGI adapter."""
import azure.functions as func

from manali_api.app import app as fastapi_app

app = func.AsgiFunctionApp(app=fastapi_app, http_auth_level=func.AuthLevel.ANONYMOUS)
