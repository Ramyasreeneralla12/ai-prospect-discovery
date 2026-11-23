import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.config import get_settings
from app.schemas import DiscoveryRequest, DiscoveryResponse
from app.services.llm_service import LLMService
from app.services.prospect_service import ProspectService
from app.services.search_service import build_search_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    search = build_search_service(settings)
    llm = LLMService(settings)
    app.state.search_service = search
    app.state.llm_service = llm
    app.state.prospect_service = ProspectService(settings, search, llm)
    yield
    await search.close()
    await llm.close()


app = FastAPI(
    title="AI-Powered Multi-Platform Prospect Discovery API",
    description="Discover publicly indexed, evidence-backed prospect profiles using an authorized search API.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    settings = get_settings()
    search_configured = settings.search_provider.casefold() == "tavily" and bool(settings.tavily_api_key)
    llm_configured = bool({
        "gemini": settings.gemini_api_key,
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
    }.get(settings.llm_provider.casefold(), ""))
    llm_service = getattr(app.state, "llm_service", None)
    search_service = getattr(app.state, "search_service", None)
    search_availability = getattr(
        search_service,
        "availability",
        "not_checked" if search_configured else "not_configured",
    )
    if settings.llm_provider.casefold() == "gemini":
        # Health checks never consume Gemini quota. Availability reflects the
        # latest real provider result, or remains not_checked before first use.
        llm_availability = getattr(
            llm_service,
            "gemini_availability",
            "not_checked" if settings.gemini_api_key else "not_configured",
        )
    else:
        llm_availability = "not_checked" if llm_configured else "not_configured"
    result = {
        "status": "ok",
        "search_provider": settings.search_provider,
        "search": "configured" if search_configured else "not_configured",
        "search_availability": search_availability,
        "llm": "configured" if llm_configured else "not_configured",
        "llm_availability": llm_availability,
    }
    if settings.llm_provider.casefold() == "gemini":
        result["llm_model"] = settings.gemini_model
        if llm_service is not None and getattr(llm_service, "gemini_last_error", None):
            result["llm_last_error"] = str(llm_service.gemini_last_error)[:300]
    if search_service is not None and getattr(search_service, "last_error", None):
        result["search_last_error"] = str(search_service.last_error)[:300]
    return result


@app.post("/prospect-discovery", response_model=DiscoveryResponse, tags=["prospects"])
async def prospect_discovery(payload: DiscoveryRequest, request: Request) -> DiscoveryResponse:
    service: ProspectService = request.app.state.prospect_service
    return await service.discover(payload.query)
