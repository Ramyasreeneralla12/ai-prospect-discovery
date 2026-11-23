import httpx
import pytest
from starlette.requests import Request

from app.config import Settings
from app.main import app
from app.schemas import SearchResult
from app.services.prospect_service import ProspectService


class FakeLLM:
    def configured(self):
        return True

    async def understand(self, query):
        from app.services.query_service import deterministic_intent, deterministic_queries
        intent = deterministic_intent(query)
        return intent, deterministic_queries(intent)

    async def score_candidates(self, query, intent, candidates):
        return {row["id"]: {
            "score": 0.92, "entity_type": "individual", "is_profile": True,
            "name": "Jordan Lee", "role_evidence": "Football coach in Washington DC",
            "location": {"city": "Washington DC", "state": "District of Columbia", "country": "United States"},
            "rationale": "Named individual profile and football role are present in the source text.",
        } for row in candidates}


class FakeSearch:
    async def search(self, query):
        if "football" in query.casefold() and "linkedin.com/in" in query:
            return [SearchResult(title="Jordan Lee | Football Coach", url="https://www.linkedin.com/in/jordan-lee", snippet="Football coach in Washington DC")]
        return []


class GeminiUnavailable:
    name = "Tavily Search"

    def configured(self):
        return True

    async def understand(self, query):
        raise AssertionError("simple queries should not spend a Gemini call on parsing")

    async def score_candidates(self, query, intent, candidates):
        from app.services.llm_service import LLMError
        raise LLMError("Gemini provider unavailable (HTTP 503): temporary overload")


class GeminiDisabled:
    def configured(self):
        return False

    async def understand(self, query):
        raise AssertionError("Gemini must not be called when disabled")

    async def score_candidates(self, query, intent, candidates):
        raise AssertionError("Gemini must not be called when disabled")


class EvidenceSearch:
    name = "Tavily Search"

    async def search(self, query):
        return [SearchResult(
            title="Asha Patel - Co-founder at Northstar | LinkedIn",
            url="https://www.linkedin.com/in/asha-patel",
            snippet="Asha Patel is co-founder of Northstar, a London startup.",
        )]


class StaticSearch:
    name = "Tavily Search"

    def __init__(self, results):
        self.results = results

    async def search(self, query):
        return self.results


class FailedSearch:
    name = "Tavily Search"

    async def search(self, query):
        from app.services.search_service import SearchUnavailable
        raise SearchUnavailable("Tavily Search temporarily unavailable")


def _finish_without_io(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("test coroutine unexpectedly waited for external I/O")


def _post_with_immediate_async(monkeypatch, service, query):
    from app.main import prospect_discovery
    from app.schemas import DiscoveryRequest

    app.state.prospect_service = service

    async def gather_immediate(*tasks, return_exceptions=False):
        results = []
        for task in tasks:
            try:
                task.send(None)
            except StopIteration as completed:
                results.append(completed.value)
            except Exception as exc:
                if not return_exceptions:
                    raise
                results.append(exc)
        return results

    monkeypatch.setattr("app.services.prospect_service.asyncio.gather", gather_immediate)
    request = Request({
        "type": "http", "app": app, "method": "POST", "path": "/prospect-discovery",
        "headers": [], "query_string": b"",
    })
    return _finish_without_io(prospect_discovery(DiscoveryRequest(query=query), request))


def test_mocked_tavily_response_flows_through_post_endpoint_without_gemini(monkeypatch, caplog):
    import logging

    caplog.set_level(logging.INFO)
    from app.main import prospect_discovery
    from app.schemas import DiscoveryRequest
    from app.services.search_service import TavilySearchService

    tavily_request = {}

    class MockResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{
                "title": "Asha Patel - Co-founder at Northstar | LinkedIn",
                "url": "https://www.linkedin.com/in/asha-patel/details/experience/",
                "content": "Asha Patel is co-founder of Northstar, a London startup.",
            }]}

    class MockTavilyClient:
        async def post(self, url, **kwargs):
            tavily_request["url"] = url
            tavily_request.update(kwargs)
            return MockResponse()

    app.state.prospect_service = ProspectService(
        Settings(_env_file=None, tavily_api_key="test-only", max_search_queries=1),
        TavilySearchService(Settings(_env_file=None, tavily_api_key="test-only"), MockTavilyClient()),
        GeminiDisabled(),
    )
    async def gather_immediate(*tasks, return_exceptions=False):
        results = []
        for task in tasks:
            try:
                task.send(None)
            except StopIteration as completed:
                results.append(completed.value)
            except Exception as exc:
                if not return_exceptions:
                    raise
                results.append(exc)
        return results

    monkeypatch.setattr("app.services.prospect_service.asyncio.gather", gather_immediate)
    request = Request({
        "type": "http", "app": app, "method": "POST", "path": "/prospect-discovery",
        "headers": [], "query_string": b"",
    })
    response = _finish_without_io(prospect_discovery(
        DiscoveryRequest(query="Startup founders in London UK"), request
    ))

    assert tavily_request["url"] == "https://api.tavily.com/search"
    assert tavily_request["json"]["query"].startswith("site:linkedin.com/in")
    assert response.total_prospects == 1
    assert response.prospects[0].name == "Asha Patel"
    assert response.prospects[0].social_link[0].link == "https://www.linkedin.com/in/asha-patel/details/experience/"
    assert any("deterministic relevance scoring and evidence-based prospect extraction were used" in warning for warning in response.warnings)
    assert "Tavily Search" in response.sources_checked
    assert "Tavily raw_result_count=1" in caplog.text
    assert "Asha Patel - Co-founder at Northstar | LinkedIn" in caplog.text
    assert "raw_results=1" in caplog.text and "prospects_extracted=1" in caplog.text


def test_post_endpoint_keeps_prospect_extraction_when_gemini_503s(monkeypatch):
    from app.main import prospect_discovery
    from app.schemas import DiscoveryRequest

    app.state.prospect_service = ProspectService(
        Settings(_env_file=None, tavily_api_key="test-only", max_search_queries=1),
        EvidenceSearch(),
        GeminiUnavailable(),
    )

    async def gather_immediate(*tasks, return_exceptions=False):
        results = []
        for task in tasks:
            try:
                task.send(None)
            except StopIteration as completed:
                results.append(completed.value)
            except Exception as exc:
                if not return_exceptions:
                    raise
                results.append(exc)
        return results

    monkeypatch.setattr("app.services.prospect_service.asyncio.gather", gather_immediate)
    request = Request({"type": "http", "app": app, "method": "POST", "path": "/prospect-discovery", "headers": [], "query_string": b""})
    response = _finish_without_io(prospect_discovery(
        DiscoveryRequest(query="Startup founders in London UK"), request
    ))

    assert response.total_prospects == 1
    assert response.prospects[0].name == "Asha Patel"
    assert any("HTTP 503" in warning and "deterministic relevance scoring and evidence-based prospect extraction was used" in warning for warning in response.warnings)


def test_gemini_retries_only_transient_responses_twice(monkeypatch):
    from types import SimpleNamespace

    from app.services.llm_service import LLMService

    calls = []
    delays = []

    class Temporary503(RuntimeError):
        code = 503

    class Interactions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) < 3:
                raise Temporary503("temporary service overload")
            return "ok"

    async def no_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr("app.services.llm_service.asyncio.sleep", no_sleep)
    service = LLMService(Settings(_env_file=None, gemini_api_key="test-only"))
    service._gemini_client = SimpleNamespace(aio=SimpleNamespace(interactions=Interactions()))

    pending = service._create_gemini_interaction("prompt", {})
    try:
        pending.send(None)
    except StopIteration as result:
        assert result.value == "ok"
    else:
        raise AssertionError("mocked retries unexpectedly waited for external I/O")
    assert len(calls) == 3  # original attempt plus at most two retries
    assert len(delays) == 2
    assert delays[1] > delays[0]


def test_gemini_429_quota_error_is_not_retried_and_enters_cooldown():
    from types import SimpleNamespace

    from app.services.llm_service import LLMError, LLMService

    calls = []

    class Quota429(RuntimeError):
        code = 429

    class Interactions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            raise Quota429("daily free-tier quota exhausted")

    service = LLMService(Settings(_env_file=None, gemini_api_key="test-only"))
    service._gemini_client = SimpleNamespace(aio=SimpleNamespace(interactions=Interactions()))
    with pytest.raises(LLMError, match="quota exhausted"):
        _finish_without_io(service._generate_gemini_json("prompt", {"type": "object"}))

    assert len(calls) == 1
    assert service.gemini_availability == "quota_exhausted"
    with pytest.raises(LLMError, match="provider calls paused"):
        _finish_without_io(service._generate_gemini_json("different prompt", {"type": "object"}))
    assert len(calls) == 1


def test_any_gemini_429_enters_quota_cooldown_without_retry():
    from types import SimpleNamespace

    from app.services.llm_service import LLMError, LLMService

    calls = []

    class RateLimit429(RuntimeError):
        code = 429

    class Interactions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            raise RateLimit429("too many requests")

    service = LLMService(Settings(_env_file=None, gemini_api_key="test-only"))
    service._gemini_client = SimpleNamespace(aio=SimpleNamespace(interactions=Interactions()))
    with pytest.raises(LLMError, match="quota exhausted"):
        _finish_without_io(service._generate_gemini_json("prompt", {"type": "object"}))
    assert service.gemini_availability == "quota_exhausted"
    with pytest.raises(LLMError, match="provider calls paused"):
        _finish_without_io(service._generate_gemini_json("different prompt", {"type": "object"}))
    assert len(calls) == 1


@pytest.mark.parametrize(("query", "title", "snippet", "url", "expected_name", "expected_location"), [
    ("Startup founders in London UK", "Asha Patel - Co-founder at Northstar | LinkedIn",
     "Asha Patel is co-founder of Northstar, a London startup.", "https://www.linkedin.com/in/asha-patel", "Asha Patel", "London"),
    ("Restaurant owners in Dubai UAE", "Maria Chen - Restaurant Owner | LinkedIn",
     "Maria Chen is a restaurant owner based in Dubai, UAE.", "https://www.linkedin.com/in/maria-chen", "Maria Chen", "Dubai"),
    ("Digital marketing agency owners in New York USA", "Sam Patel - Digital Marketing Agency Owner | LinkedIn",
     "Sam Patel owns a digital marketing agency in New York, USA.", "https://www.linkedin.com/in/sam-patel", "Sam Patel", "New York"),
    ("Cricket enthusiasts in Ahmedabad India", "Arjun Shah - Cricket Enthusiast | LinkedIn",
     "Arjun Shah is a cricket enthusiast based in Ahmedabad, India.", "https://www.linkedin.com/in/arjun-shah", "Arjun Shah", "Ahmedabad"),
])
def test_deterministic_fallback_finds_evidence_backed_profiles_without_gemini(
    monkeypatch, query, title, snippet, url, expected_name, expected_location,
):
    result = SearchResult(title=title, url=url, snippet=snippet)
    service = ProspectService(
        Settings(_env_file=None, tavily_api_key="test-only", max_search_queries=1),
        StaticSearch([result]),
        GeminiDisabled(),
    )
    response = _post_with_immediate_async(monkeypatch, service, query)

    assert response.success is True
    assert response.total_prospects == 1
    assert response.prospects[0].name == expected_name
    assert response.prospects[0].location.startswith(expected_location)
    assert str(response.prospects[0].social_link[0].link) == url
    assert any("deterministic relevance scoring and evidence-based prospect extraction were used" in warning for warning in response.warnings)


def test_empty_tavily_results_are_successful_and_report_zero_results(monkeypatch):
    service = ProspectService(
        Settings(_env_file=None, tavily_api_key="test-only", max_search_queries=1),
        StaticSearch([]), GeminiDisabled(),
    )
    response = _post_with_immediate_async(monkeypatch, service, "Startup founders in London UK")
    assert response.success is True
    assert response.total_prospects == 0
    assert response.prospects == []
    assert any("returned zero search results" in warning for warning in response.warnings)


def test_tavily_failure_is_distinct_from_successful_empty_search(monkeypatch):
    service = ProspectService(
        Settings(_env_file=None, tavily_api_key="test-only", max_search_queries=1),
        FailedSearch(), GeminiDisabled(),
    )
    response = _post_with_immediate_async(monkeypatch, service, "Startup founders in London UK")
    assert response.success is True
    assert response.total_prospects == 0
    assert any("discovery failed" in warning for warning in response.warnings)
    assert any("Search failed:" in warning for warning in response.warnings)


def test_gemini_503_retries_then_success_caches_response(monkeypatch):
    from types import SimpleNamespace

    from app.services.llm_service import LLMService

    calls = []
    delays = []

    class Temporary503(RuntimeError):
        code = 503

    class Interactions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) <= 2:
                raise Temporary503("temporarily unavailable")
            return SimpleNamespace(output_text='{"intent":"founder"}')

    async def no_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr("app.services.llm_service.asyncio.sleep", no_sleep)
    service = LLMService(Settings(_env_file=None, gemini_api_key="test-only"))
    service._gemini_client = SimpleNamespace(aio=SimpleNamespace(interactions=Interactions()))
    first = _finish_without_io(service._generate_gemini_json("same prompt", {"type": "object"}))
    second = _finish_without_io(service._generate_gemini_json("same prompt", {"type": "object"}))

    assert first == second == {"intent": "founder"}
    assert len(calls) == 3
    assert len(delays) == 2
    assert service.gemini_availability == "available"


def test_gemini_503_exhaustion_records_unavailability_after_two_retries(monkeypatch):
    from types import SimpleNamespace

    from app.services.llm_service import LLMError, LLMService

    calls = []

    class Temporary503(RuntimeError):
        code = 503

    class Interactions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            raise Temporary503("service temporarily unavailable")

    async def no_sleep(delay):
        return None

    monkeypatch.setattr("app.services.llm_service.asyncio.sleep", no_sleep)
    service = LLMService(Settings(_env_file=None, gemini_api_key="test-only"))
    service._gemini_client = SimpleNamespace(aio=SimpleNamespace(interactions=Interactions()))
    with pytest.raises(LLMError, match="temporary service unavailable"):
        _finish_without_io(service._generate_gemini_json("prompt", {"type": "object"}))

    assert len(calls) == 3
    assert service.gemini_availability == "temporary_service_unavailable"


def test_gemini_invalid_api_key_is_reported_without_retry():
    from types import SimpleNamespace

    from app.services.llm_service import LLMError, LLMService

    calls = []

    class Unauthorized401(RuntimeError):
        code = 401

    class Interactions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            raise Unauthorized401("API key not valid")

    service = LLMService(Settings(_env_file=None, gemini_api_key="test-only"))
    service._gemini_client = SimpleNamespace(aio=SimpleNamespace(interactions=Interactions()))
    with pytest.raises(LLMError, match="invalid api key"):
        _finish_without_io(service._generate_gemini_json("prompt", {"type": "object"}))
    assert len(calls) == 1
    assert service.gemini_availability == "invalid_api_key"


@pytest.mark.parametrize("query", [
    "Football lovers in Washington DC in USA",
    "Digital marketing agency owners in New York USA",
    "Startup founders in London UK",
    "Cricket lovers in Ahmedabad India",
    "Restaurant owners in Dubai UAE",
])
def test_endpoint_returns_schema_for_assessment_queries(query, monkeypatch):
    service = ProspectService(Settings(_env_file=None, tavily_api_key="test"), FakeSearch(), FakeLLM())
    response = _post_with_immediate_async(monkeypatch, service, query)
    body = response.model_dump()
    assert body["success"] is True
    assert body["query"] == query
    assert body["total_prospects"] == len(body["prospects"])
    assert isinstance(body["warnings"], list)


def test_discovers_profile_only_from_search_result_evidence(monkeypatch):
    service = ProspectService(Settings(_env_file=None, tavily_api_key="test"), FakeSearch(), FakeLLM())
    body = _post_with_immediate_async(monkeypatch, service, "Football lovers in Washington DC in USA").model_dump()
    assert body["total_prospects"] == 1
    prospect = body["prospects"][0]
    assert prospect["name"] == "Jordan Lee"
    assert prospect["social_link"][0]["link"] == "https://www.linkedin.com/in/jordan-lee"


def test_empty_query_is_rejected():
    from pydantic import ValidationError
    from app.schemas import DiscoveryRequest
    with pytest.raises(ValidationError):
        DiscoveryRequest(query="  ")


def test_untrusted_or_non_profile_url_is_rejected():
    from app.utils.validators import is_valid_profile_url
    assert not is_valid_profile_url("https://linkedin.com/search/results")
    assert not is_valid_profile_url("https://notlinkedin.com/in/person")
    assert not is_valid_profile_url("https://youtu.be/abc123")
    assert not is_valid_profile_url("https://instagram.com/p/abc123")


def test_health_reports_tavily_and_gemini_configuration(monkeypatch):
    from app import main

    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(
            search_provider="tavily",
            tavily_api_key="test-only",
            llm_provider="gemini",
            gemini_api_key="test-only",
        ),
    )
    pending = main.health()
    try:
        pending.send(None)
    except StopIteration as result:
        assert result.value == {
            "status": "ok",
            "search_provider": "tavily",
            "search": "configured",
            "search_availability": "not_checked",
            "llm": "configured",
            "llm_availability": "not_checked",
            "llm_model": "gemini-3.8-flash",
        }
    else:
        raise AssertionError("health endpoint should not suspend")


def test_health_does_not_report_missing_keys_as_configured(monkeypatch):
    from app import main

    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(_env_file=None, search_provider="tavily", llm_provider="gemini"),
    )
    pending = main.health()
    try:
        pending.send(None)
    except StopIteration as result:
        assert result.value["search"] == "not_configured"
        assert result.value["search_availability"] == "not_configured"
        assert result.value["llm"] == "not_configured"
        assert result.value["llm_availability"] == "not_configured"
    else:
        raise AssertionError("health endpoint should not suspend")


def test_health_reports_last_known_gemini_failure_without_network_call(monkeypatch):
    from types import SimpleNamespace

    from app import main

    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(_env_file=None, gemini_api_key="test-only", gemini_model="gemini-3.8-flash"),
    )
    monkeypatch.setattr(
        main.app.state,
        "llm_service",
        SimpleNamespace(gemini_availability="quota_exhausted", gemini_last_error="daily quota exceeded"),
        raising=False,
    )
    monkeypatch.setattr(
        main.app.state,
        "search_service",
        SimpleNamespace(availability="temporarily_unavailable", last_error="Tavily Search HTTP 503"),
        raising=False,
    )
    pending = main.health()
    try:
        pending.send(None)
    except StopIteration as result:
        assert result.value["llm_availability"] == "quota_exhausted"
        assert result.value["llm_last_error"] == "daily quota exceeded"
        assert result.value["search_availability"] == "temporarily_unavailable"
        assert result.value["search_last_error"] == "Tavily Search HTTP 503"
    else:
        raise AssertionError("health endpoint should not suspend or call Gemini")


def test_duplicate_merging_requires_strong_identity_signal():
    from app.schemas import Prospect, SocialLink
    from app.services.deduplication_service import deduplicate
    same_a = Prospect(name="Alex Rivera", location="Boston, USA", social_link=[SocialLink(platform="LinkedIn", link="https://linkedin.com/in/alex")])
    same_b = Prospect(name="Alex Rivera", location="Boston, USA", social_link=[SocialLink(platform="Instagram", link="https://instagram.com/alex")])
    diff = Prospect(name="Alex Rivera", location="London, UK", social_link=[SocialLink(platform="X", link="https://x.com/alex2")])
    result = deduplicate([(same_a, ["u1"]), (same_b, ["u2"]), (diff, ["u3"])])
    assert len(result) == 2
    assert {item.platform for item in result[0][0].social_link} == {"LinkedIn", "Instagram"}


@pytest.mark.parametrize(("query", "city", "state", "country", "target"), [
    ("Football lovers in Washington DC in USA", "Washington DC", "District of Columbia", "United States", "individual"),
    ("Digital marketing agency owners in New York USA", "New York", None, "United States", "individual"),
    ("Startup founders in London UK", "London", None, "United Kingdom", "individual"),
    ("Cricket lovers in Ahmedabad India", "Ahmedabad", None, "India", "individual"),
    ("Restaurant owners in Dubai UAE", "Dubai", None, "United Arab Emirates", "individual"),
])
def test_deterministic_query_understanding_extracts_location_and_target(query, city, state, country, target):
    from app.services.query_service import deterministic_intent
    intent = deterministic_intent(query)
    assert intent.location.city == city
    assert intent.location.state == state
    assert intent.location.country == country
    assert intent.target_type == target


def test_business_queries_generate_company_profile_queries():
    from app.schemas import Location, QueryIntent
    from app.services.query_service import deterministic_queries
    intent = QueryIntent(interest="Restaurants", audience="restaurant businesses", location=Location(city="Dubai", country="United Arab Emirates"), target_type="business")
    queries = deterministic_queries(intent)
    assert "site:linkedin.com/company" in queries[0]


def test_linkedin_profile_paths_are_target_specific():
    from app.utils.validators import is_valid_profile_url
    assert is_valid_profile_url("https://www.linkedin.com/in/jane-doe", "individual")
    assert not is_valid_profile_url("https://www.linkedin.com/posts/jane-doe_activity-123", "individual")
    assert not is_valid_profile_url("https://www.linkedin.com/pulse/startup-report", "individual")
    assert not is_valid_profile_url("https://www.linkedin.com/feed/", "individual")
    assert is_valid_profile_url("https://www.linkedin.com/company/acme", "business")
    assert not is_valid_profile_url("https://www.linkedin.com/company/acme", "individual")


def test_profile_extraction_requires_named_person_role_and_profile_evidence():
    from app.services.profile_extractor import classify_result, extract_candidate
    person = SearchResult(title="Jane Doe | LinkedIn", url="https://www.linkedin.com/in/jane-doe", snippet="Jane Doe is co-founder of Acme, a London startup.")
    assessment = {"entity_type": "individual", "is_profile": True, "name": "Jane Doe",
                  "role_evidence": "Jane Doe is co-founder of Acme", "score": 0.95,
                  "location": {"city": "London", "country": "United Kingdom"}}
    assert classify_result(person, "individual") == "individual_profile"
    prospect, evidence = extract_candidate(person, assessment, "individual", "startup founders")
    assert prospect.name == "Jane Doe"
    assert prospect.location == "London"
    assert evidence == [str(person.url)]
    article = SearchResult(title="UK Startups with International Co-Founders: Closing the Gap", url="https://www.linkedin.com/pulse/startup-report", snippet="Founders discuss startups")
    assert classify_result(article, "individual") == "article"
    assert extract_candidate(article, assessment, "individual", "startup founders") is None


def test_startup_founder_without_explicit_company_relationship_is_rejected():
    from app.services.profile_extractor import extract_candidate
    from app.services.relevance_service import assess_candidate_score
    person = SearchResult(title="Jane Doe | LinkedIn", url="https://www.linkedin.com/in/jane-doe", snippet="Jane Doe shares posts about startups in London.")
    assessment = {"score": 0.99, "entity_type": "individual", "is_profile": True, "name": "Jane Doe",
                  "role_evidence": "posts about startups", "location": {"city": "London"}, "rationale": "high similarity"}
    from app.services.query_service import deterministic_intent
    intent = deterministic_intent("Startup founders in London UK")
    score, _ = assess_candidate_score(intent, person, assessment)
    assert score < 0.58
    assert extract_candidate(person, assessment, "individual", intent.audience) is None


def test_profile_title_identity_and_same_result_founder_snippet_are_combined():
    from app.services.profile_extractor import deterministic_assessment, extract_candidate
    from app.services.query_service import deterministic_intent

    intent = deterministic_intent("Startup founders in London UK")
    result = SearchResult(
        title="Vish Burgul - Founder & Operator | LinkedIn",
        url="https://www.linkedin.com/in/vishburgul",
        snippet="Founder of a London technology company; works with early-stage teams.",
    )
    assessment = deterministic_assessment(result, intent)
    extracted = extract_candidate(result, assessment, intent.target_type, intent.audience)

    assert assessment["name"] == "Vish Burgul"
    assert extracted is not None
    assert extracted[0].name == "Vish Burgul"


def test_tavily_search_uses_basic_authorized_api_and_preserves_result_url():
    from app.services.search_service import TavilySearchService
    seen = {}

    class Response:
        status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return {"results": [{"title": "Jane Doe | LinkedIn", "url": "https://www.linkedin.com/in/jane-doe", "content": "Jane Doe, London."}]}

    class Client:
        async def post(self, url, *, headers, json):
            seen["url"] = url
            seen["auth"] = headers.get("Authorization")
            seen["body"] = json
            return Response()

    client = Client()
    service = TavilySearchService(Settings(tavily_api_key="test-only"), client)
    results = _finish_without_io(service.search('site:linkedin.com/in "startup founder" London UK'))
    assert seen["url"] == "https://api.tavily.com/search"
    assert seen["auth"] == "Bearer test-only"
    assert seen["body"]["search_depth"] == "basic"
    assert str(results[0].url) == "https://www.linkedin.com/in/jane-doe"


def test_tavily_503_updates_actual_search_availability():
    from app.services.search_service import SearchUnavailable, TavilySearchService

    class Client:
        async def post(self, url, **kwargs):
            return httpx.Response(503, request=httpx.Request("POST", url))

    service = TavilySearchService(Settings(_env_file=None, tavily_api_key="test-only"), Client())
    with pytest.raises(SearchUnavailable, match="HTTP 503"):
        _finish_without_io(service.search("founders in London"))
    assert service.availability == "temporarily_unavailable"
    assert "HTTP 503" in service.last_error
