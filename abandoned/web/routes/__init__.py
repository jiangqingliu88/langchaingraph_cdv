"""
Route modules for SignOffAI Web API.
Each module defines a FastAPI APIRouter that is registered in api.py.
"""
from .docs import router as docs_router
from .ppa import router as ppa_router
from .signoff import router as signoff_router
from .pipeline import router as pipeline_router

__all__ = ["docs_router", "ppa_router", "signoff_router", "pipeline_router"]
