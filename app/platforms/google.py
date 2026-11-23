"""Google is intentionally represented as a search source only, never as a prospect profile."""

class GoogleDiscoveryAdapter:
    name = "Google"
    supported = False
    reason = "Google Custom Search JSON API is closed to new customers; use Tavily Search in this project."
