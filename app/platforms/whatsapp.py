"""WhatsApp has no public directory API; only public wa.me links are recognized as contact evidence."""
from app.utils.validators import platform_for_url

class WhatsAppAdapter:
    name = "WhatsApp"
    supported = "public contact links only; no prospect search endpoint"
    def accepts(self, url: str) -> bool: return platform_for_url(url) == self.name
