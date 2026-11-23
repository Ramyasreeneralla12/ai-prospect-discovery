# AI-Powered Multi-Platform Prospect Discovery API

An AI-powered prospect discovery API that identifies publicly indexed, evidence-backed prospect profiles using natural-language queries and an authorized search API.

**Live API:** https://ai-prospect-discovery.onrender.com  
**Swagger Documentation:** https://ai-prospect-discovery.onrender.com/docs  
**Health Check:** https://ai-prospect-discovery.onrender.com/health  
**GitHub Repository:** https://github.com/Ramyasreeneralla12/ai-prospect-discovery

---

## 1. Project Overview

The AI-Powered Multi-Platform Prospect Discovery API helps users discover potential prospects based on a natural-language query.

Users can search for prospects by specifying:
- Target audience or profession
- Location
- Industry or interests
- Relevant social media platforms

The API searches publicly indexed information, extracts relevant profile details, and returns evidence-backed results in a structured JSON format.

### Example Queries

- Startup founders in London UK
- Digital marketing agency owners in New York USA
- Cricket lovers in Ahmedabad India
- Football lovers in Washington DC USA
- Restaurant owners in Dubai UAE

## 2. Key Features

- Natural-language prospect discovery.
- Publicly indexed profile discovery.
- Tavily Search API integration.
- Multi-platform search support.
- Evidence-based prospect extraction.
- Structured JSON responses.
- Relevance-based filtering.
- LLM-powered extraction when providers are available.
- Fallback mechanisms for improved API availability.
- Input validation and error handling.
- Interactive Swagger API documentation.
- Deployed API using Render.

## 3. Technology Stack

| Category | Technology |
|---|---|
| Programming Language | Python 3.11 |
| Backend Framework | FastAPI |
| Data Validation | Pydantic |
| Search API | Tavily |
| AI Integration | Gemini, OpenAI, Anthropic |
| HTTP Requests | HTTPX |
| Environment Management | python-dotenv |
| Testing | Pytest |
| API Documentation | Swagger / OpenAPI |
| Deployment | Render |
| Version Control | Git and GitHub |

## 4. Supported Platforms

The application searches publicly indexed information associated with platforms such as:

- LinkedIn
- X (Twitter)
- YouTube
- Instagram
- Facebook
- Threads

Publicly available contact information and WhatsApp links may be included when present in search evidence.

**Note:** The API uses authorized search results to discover publicly indexed information. It does not directly access private accounts, restricted profiles, or private platform data. Google and WhatsApp direct platform searches are not implemented as dedicated integrations.

## 5. System Architecture

The application follows this general workflow:

1. User submits a natural-language query.
2. FastAPI receives and validates the request.
3. The search service sends the query to Tavily.
4. Search results are collected from publicly indexed sources.
5. Relevant profile information and supporting evidence are extracted.
6. The configured LLM processes the information when available.
7. A fallback mechanism handles provider unavailability.
8. The API returns structured JSON results.

### LLM Fallback Workflow

The application uses the following fallback approach:

**Primary:** Gemini

**Secondary:** OpenAI, when configured and available.

**Final fallback:** Deterministic extraction and relevance scoring.

This helps the API continue processing requests when an LLM provider is unavailable or its quota is exhausted.

Anthropic integration is available as an alternative provider implementation.

## 6. API Usage

### Base URL

`https://ai-prospect-discovery.onrender.com`

### Endpoint

`POST /prospect-discovery`

### Request Example

```json
{
  "query": "Startup founders in London UK"
}
```

### Response

The API returns a structured JSON response containing:
- Success status
- Original search query
- Discovered prospects
- Profile and platform information
- Supporting evidence and source links
- Relevant warnings, when applicable

### Example Response Structure

```json
{
  "success": true,
  "query": "Startup founders in London UK",
  "prospects": [
    {
      "name": "Example Founder",
      "platform": "LinkedIn",
      "profile_url": "https://www.linkedin.com/",
      "evidence": "Publicly indexed information supporting relevance"
    }
  ],
  "warnings": []
}
```

*The example above illustrates the response structure. Actual results depend on live search results and available evidence.*

## 7. Mandatory Query Testing

All five mandatory assessment queries were executed successfully against the deployed API on November 23, 2026.

| No. | Test Query | HTTP Status | Status |
|---|---|---|---|
| 1 | Startup founders in London UK | 200 | Passed |
| 2 | Digital marketing agency owners in New York USA | 200 | Passed |
| 3 | Cricket lovers in Ahmedabad India | 200 | Passed |
| 4 | Football lovers in Washington DC USA | 200 | Passed |
| 5 | Restaurant owners in Dubai UAE | 200 | Passed |

**Overall Test Status: 5/5 Passed**

### Test Observations

- All five API requests completed successfully.
- All responses followed the expected API response structure.
- The API handled different industries, interests, and geographical locations.
- Publicly indexed search results were processed.
- Evidence-based filtering was applied to prospect information.
- The fallback mechanism maintained API availability when LLM providers were unavailable.

## 8. Search and Prospect Processing

The application uses Tavily to retrieve publicly indexed information.

The processing workflow includes:

- Query preparation.
- Public search result retrieval.
- Profile information extraction.
- Relevance evaluation.
- Evidence collection.
- Structured response generation.

The application aims to return relevant prospects supported by available public evidence rather than inventing profile information.

## 9. LLM Provider Comparison

The application considers three LLM providers:

| Evaluation Criteria | Gemini | OpenAI | Anthropic |
|---|---|---|---|
| Response Quality | Evaluated for extraction quality | Evaluated for extraction quality | Evaluated for extraction quality |
| Response Speed | Provider-dependent | Provider-dependent | Provider-dependent |
| API Cost | Depends on model and usage | Depends on model and usage | Depends on model and usage |
| Context Handling | Model-dependent | Model-dependent | Model-dependent |
| JSON Output | Supports structured output | Supports structured output | Supports structured output |

### Provider Selection

- Gemini is configured as the primary provider.
- OpenAI is configured as a secondary fallback when available.
- Anthropic is supported as an alternative provider.
- Deterministic extraction is used when LLM providers cannot process a request.

**Note:** Provider performance, latency, and cost depend on the selected model, API plan, and usage. No controlled benchmark is claimed in this project.

## 10. Local Setup Instructions

### Prerequisites

- Python 3.11
- Git
- VS Code or another Python IDE
- Tavily API key
- Gemini API key (optional)
- OpenAI API key (optional)
- Anthropic API key (optional)

### Step 1: Clone the Repository

```bash
git clone https://github.com/Ramyasreeneralla12/ai-prospect-discovery.git
```

### Step 2: Open the Project Directory

```bash
cd ai-prospect-discovery
```

### Step 3: Create a Virtual Environment

```bash
python -m venv venv
```

Activate it on Windows:

```powershell
venv\Scripts\activate
```

### Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 5: Configure Environment Variables

Create a `.env` file in the project root directory.

```env
TAVILY_API_KEY=your_tavily_api_key
GEMINI_API_KEY=your_gemini_api_key
OPENAI_API_KEY=your_openai_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
LLM_PROVIDER=gemini
```

Add only the API keys you have configured. Never upload real API keys or secrets to GitHub.

### Step 6: Run the Application

```bash
uvicorn app.main:app --reload
```

### Step 7: Open Swagger Documentation

Visit:

`http://127.0.0.1:8000/docs`

Use Swagger to test the API endpoints.

## 11. Automated Testing

The project includes automated tests using Pytest.

Run the test suite:

```bash
python -m pytest -q
```

**Latest recorded test result:**

```text
38 passed in 12.99s
```

The tests cover application functionality, request validation, and relevant service behavior.

## 12. Deployment

The application is deployed using Render.

**Deployment URL:**  
https://ai-prospect-discovery.onrender.com

**API Documentation:**  
https://ai-prospect-discovery.onrender.com/docs

**Health Endpoint:**  
https://ai-prospect-discovery.onrender.com/health

The application uses environment variables configured in the Render dashboard for API credentials and provider settings.

## 13. Limitations

- Search results depend on publicly indexed information.
- Some platforms may have limited publicly indexed results.
- Private profiles and restricted information cannot be accessed.
- Contact details are returned only when supported by public evidence.
- LLM provider availability and quotas may affect extraction.
- Search results and prospect relevance can vary depending on the query.

## 14. Future Enhancements

- Add more authorized search provider integrations.
- Improve prospect relevance ranking.
- Add pagination and advanced filters.
- Introduce more detailed search analytics.
- Improve extraction accuracy and duplicate detection.
- Add performance benchmarking across LLM providers.
- Expand automated test coverage.

## 15. Security and Responsible Data Usage

- API keys are stored in environment variables.
- Secrets should never be committed to GitHub.
- Only publicly indexed information is processed.
- Private or restricted personal information is not accessed.
- Extracted information should be independently verified before business outreach.
- The application is intended for responsible prospect discovery.

---

## Conclusion

The AI-Powered Multi-Platform Prospect Discovery API provides a natural-language interface for discovering publicly indexed, evidence-backed prospects across multiple platforms.

The project combines FastAPI, Tavily Search, LLM integrations, structured data extraction, fallback processing, automated testing, and Render deployment to deliver a functional prospect discovery solution.
