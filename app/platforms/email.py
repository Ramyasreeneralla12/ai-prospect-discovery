"""Email is extracted only when literally published in an authorized search result snippet."""
from app.utils.validators import public_contacts

class EmailAdapter:
    name = "Email"
    supported = "evidence-based snippet extraction; no email search or address guessing"
    def extract(self, title: str, snippet: str) -> list[tuple[str, str]]:
        return [contact for contact in public_contacts(f"{title} {snippet}") if contact[0] == "Email"]
