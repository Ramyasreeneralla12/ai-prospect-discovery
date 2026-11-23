# AI-Powered Multi-Platform Prospect Discovery API

FastAPI service that turns a natural-language prospect request into public web searches, then returns only profile URLs and contact details supported by those search results. It uses Tavily Search as an authorized search API and can use Gemini, OpenAI, or Anthropic for intent extraction and relevance assessment.

This project is a discovery aid, not a verification of someone's identity, availability, or consent to be contacted. It never logs into social networks, bypasses access controls, or invents profiles. Search-index snippets can be stale; review the evidence links before acting on a result.

## Current implementation status

- Live discovery requires a Tavily API key. Tavily offers 1,000 free API credits each month without a credit card; basic searches cost one credit.
- LLM intent extraction and candidate assessment require one configured model key. If no LLM key exists, deterministic query understanding and relevance scoring are used and the response includes a warning.
- If search is not configured or fails, the API returns a valid empty result with a warning. It never substitutes sample data.
- Supported social profile discovery is public-index search for LinkedIn, Instagram, YouTube, X, Facebook, and Threads. Platform adapters only accept result URLs on those sites.
- Public email, international phone numbers, and `wa.me` links may be included only when present in a search result title/snippet and valid. They are not guessed.
- Google is not the search backend. Google Custom Search JSON API is closed to new customers, so Tavily is the configured provider here. WhatsApp has no public prospect directory/search API; this project only recognizes public contact links. Email is evidence extraction, not an email-finding service.
- No direct platform APIs are implemented. The modules are isolated search-result adapters; APIs with restricted access or no public search interface are honestly unsupported.

## Stack

Python 3.11, FastAPI, Pydantic v2, HTTPX, python-dotenv, BeautifulSoup4 (available for future authorized HTML parsing; the current implementation uses search API snippets only), `phonenumbers`, `email-validator`, pytest, and Uvicorn.

## Architecture

```text
app/
  main.py                       FastAPI routes and lifecycle
  config.py                     Environment-based settings
  schemas.py                    Request, response, evidence models
  services/
    llm_service.py              Gemini/OpenAI/Anthropic JSON calls
    query_service.py             Deterministic intent/query fallback
    search_service.py            Tavily Search client
    prospect_service.py          Discovery orchestration and graceful failures
    profile_extractor.py         Evidence-backed profile/contact extraction
    deduplication_service.py     Conservative identity merging
    relevance_service.py         Deterministic relevance scoring
  platforms/                     Independent domain adapters
  utils/                         URL, phone, email and normalization helpers
tests/                           Mocked automated tests; no external keys needed
```

## Setup

```powershell
cd ai-prospect-discovery
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set credentials in `.env` (or in the hosting provider's environment settings):

```dotenv
TAVILY_API_KEY=your_tavily_key
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-3.8-flash
GEMINI_QUOTA_COOLDOWN_SECONDS=86400
```

You can select `LLM_PROVIDER=openai` with `OPENAI_API_KEY` and `OPENAI_MODEL=gpt-5-mini`, or `LLM_PROVIDER=anthropic` with `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL=claude-sonnet-5-5`. Only the selected provider is called. Keep `.env` private; it is ignored by Git.

Create a Tavily account and API key from its [official dashboard](https://app.tavily.com/home). Its free tier currently includes 1,000 credits per month, needs no credit card, and stops requests when the credits run out. This project makes up to six basic searches per discovery call (about six credits), or roughly 166 full discovery calls within the monthly free allowance. [Official plan details](https://www.tavily.com/pricing) and [search API docs](https://docs.tavily.com/documentation/api-reference/endpoint/search).

## Run

```powershell
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for interactive Swagger docs. `GET /health` reports search configuration, LLM key configuration, and Gemini's last known availability (`not_checked` until a real Gemini request succeeds or fails). The health check does not make a provider request or use quota.

## Endpoint

`POST /prospect-discovery`

Request:

```json
{"query":"Restaurant owners in Dubai UAE"}
```

Response shape (the sample is an empty response, not a claimed search result):

```json
{
  "success": true,
  "query": "Restaurant owners in Dubai UAE",
  "total_prospects": 0,
  "prospects": [],
  "sources_checked": ["LinkedIn", "Instagram", "YouTube", "X", "Facebook", "Threads"],
  "warnings": ["TAVILY_API_KEY is not configured"]
}
```

Successful profile records include `name`, `location` only when supported by public evidence, and a `social_link` array. Every profile link comes from a returned platform-domain search result and is also checked against profile-like URL paths. Evidence URLs, scores, and rationale remain available internally on the discovery service's `last_evidence` field; they are not currently returned in the public response schema. For an evaluated deployment, consider adding an `evidence` field to the public API response so consumers can audit each result directly.

Empty query bodies and malformed request bodies receive standard FastAPI `422` JSON validation responses. An individual platform search failure adds a warning and does not stop the other searches.

## Query understanding and discovery

With an LLM configured, the service requests structured JSON for the interest, audience, location, target type, keywords, and search phrases. Search adapters add and enforce their own allowed platform domains; model output cannot choose a profile URL. LinkedIn results must be individual `/in/` or business `/company/` profile routes; posts, activity, pulse/article, feed, and search routes are rejected. Other social URLs are restricted to profile-like path shapes. Relevance assessment uses only result title, snippet, and URL. A candidate must have a named entity that appears verbatim in the title/snippet, the expected person/business type, a profile-like URL, and (for founder searches) explicit founder-to-company evidence. Location components are included only when each is supported by the title/snippet. The original profile URL is preserved in `social_link`; public contacts are validated locally.

Without the LLM, query fallback expands common country aliases (`UK`, `USA`, `UAE`) and recognizes Washington DC's state name. Candidate extraction remains fail-closed when a person/business type and name cannot be verified; a heuristic search match alone is not enough to return a prospect. For location-based searches, the source must support at least one requested location component to pass the relevance threshold.

If the LLM is missing or unavailable, deterministic extraction and scoring keep discovery available. The fallback is intentionally conservative and may return no results for less direct queries.

## Platform support

| Platform/source | Status |
|---|---|
| Tavily Search | Implemented authorized search source; basic search returns URL, title and snippet; free tier is 1,000 monthly credits |
| LinkedIn | Publicly indexed profile URLs only; no LinkedIn login or private search |
| Instagram | Publicly indexed profile URLs only; no restricted page scraping |
| YouTube | Publicly indexed channel/profile URLs only |
| X | Publicly indexed profile URLs only |
| Facebook | Publicly indexed page/profile URLs only |
| Threads | Publicly indexed profile URLs only |
| WhatsApp | Public `wa.me` contact links only; no directory/search API |
| Email / phone | Validation and literal extraction from returned public snippets only |
| Google | Not used as a search backend. Google Custom Search JSON API is closed to new customers; no Google search-result URL is returned as a prospect |

Platform search visibility depends on each site's indexing rules, search provider coverage, and public page settings. Search indexing is not proof that the page owner matches the requested audience.

## Conservative duplicate and relevance handling

Identical profile URLs are consolidated. Different profiles are merged only when normalized names and known locations are exactly equal. Similar names alone or missing location data do not merge. This avoids aggressive false merges; it can leave duplicates when pages use different names or locations.

The LLM's scores are clamped to `0..1` and compared with `MIN_RELEVANCE_SCORE`. Without an LLM, title/snippet term and location matches produce a deterministic heuristic score. The threshold is configurable. Neither scoring path confirms identity.

## Provider comparison (checked 2026-11-23)

Current public provider documentation was checked on the date above. Prices are USD per million text tokens for standard API use. Model names and pricing change; use each linked official page before budgeting. Latency and task accuracy are not benchmarked by this project.

| Provider / candidate | Input / output | Context | Structured JSON | Speed / query-accuracy assessment |
|---|---:|---:|---|---|
| Google Gemini 3.8 Flash | $0.75 / $3.75 through 2026-12-31; then $1.50 / $7.50 from 2027-01-01 | 1M | Supported through JSON response format | Expected low latency for extraction; estimated fit is good. Not measured here. |
| OpenAI GPT-5 mini | $0.25 / $2.00 | 400K | Supported | Expected fast for bounded extraction; estimated fit is good. Not measured here. |
| Anthropic Claude Sonnet 5.5 | $2.00 / $10.00 | 1M | Supported | Expected strong instruction following, but likely higher cost than GPT-5 mini. Not measured here. |

**Recommendation:** Gemini 3.8 Flash as the primary model for structured extraction and classification; OpenAI GPT-5 mini as the cost-focused alternate provider. This is based on documented features/pricing and expected task fit, not measured comparative accuracy or latency. Configure the alternate by changing `LLM_PROVIDER`; automatic cross-provider failover is not enabled, to avoid sending prospect query/result data to a second provider without an explicit configuration choice.

Estimated per-request token cost assumes one intent call (about 300 input / 250 output tokens) plus one batch relevance call for up to 40 results (about 6,000 input / 1,200 output tokens). Actual token use depends on search snippets and candidate count.

| Model | Estimated LLM tokens cost/request |
|---|---:|
| Gemini 3.8 Flash through 2026-12-31 | about $0.0102 |
| Gemini 3.8 Flash from 2027-01-01 | about $0.0203 |
| OpenAI GPT-5 mini | about $0.0045 |
| Claude Sonnet 5.5 | about $0.0271 |

Search is within Tavily's free 1,000-credit monthly allowance for about 166 full six-query discoveries; requests stop when the credits run out unless the account owner upgrades. The estimated LLM portion remains about $0.010/request with Gemini through 2026-12-31 and $0.020 from 2027-01-01 under the token assumptions above. Most no-result or smaller-result requests should use fewer LLM tokens.

Official sources: [Tavily pricing](https://www.tavily.com/pricing) and [Search API docs](https://docs.tavily.com/documentation/api-reference/endpoint/search); [Gemini pricing and structured-output guide](https://ai.google.dev/gemini-api/docs/pricing), [OpenAI GPT-5 mini model and pricing](https://developers.openai.com/api/docs/models/gpt-5-mini), [Anthropic model overview](https://platform.claude.com/docs/en/models/overview), and [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

## Tests

```powershell
pytest -q
```

The automated suite mocks the search/LLM boundaries and includes all five assessment queries, location normalization, the Tavily request contract, response shape, profile URL filtering, founder evidence, conservative duplicate merging, and request validation. It does not make live API calls or claim real-world prospect results. To verify live discovery, run the server and submit a query in `/docs`; inspect warnings and independently review the returned public profile URLs before use.

## Render deployment

The included `render.yaml` installs dependencies and starts the app with Uvicorn. Create a Render Web Service from this project directory, then add `TAVILY_API_KEY` and one selected LLM provider key in Render's environment settings. Keep secret values out of the repository. Render's `PORT` is used by the start command; health checks use `/health`. After deploy, verify `/health`, `/docs`, and `POST /prospect-discovery` with a real query. A public service should also add authentication, rate limiting, abuse controls, and a documented retention policy before accepting untrusted traffic.
