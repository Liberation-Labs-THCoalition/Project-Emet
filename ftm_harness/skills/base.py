"""Base skill chip abstractions for investigative journalism.

Adapts the Kintsugi BaseSkillChip for the FollowTheMoney ecosystem.
All skill chips in the FtM Harness inherit from this base class and
operate against the FtM data spine, Aleph API, and external data sources.

Key adaptations from Kintsugi:
- SkillDomain reflects investigation functions, not nonprofit operations
- SkillContext carries investigation-specific BDI state
- EFEWeights map to the Five Pillars of Journalism
- Consensus actions map to editorial review gates
- Capabilities reflect investigative tool access (Aleph, OSINT, NLP)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine


class SkillDomain(str, Enum):
    """Investigation domains that skill chips operate in."""
    ENTITY_SEARCH = "entity_search"
    CROSS_REFERENCE = "cross_reference"
    DOCUMENT_ANALYSIS = "document_analysis"
    NLP_EXTRACTION = "nlp_extraction"
    NETWORK_ANALYSIS = "network_analysis"
    DATA_QUALITY = "data_quality"
    FINANCIAL_INVESTIGATION = "financial_investigation"
    GOVERNMENT_ACCOUNTABILITY = "government_accountability"
    ENVIRONMENTAL_INVESTIGATION = "environmental_investigation"
    LABOR_INVESTIGATION = "labor_investigation"
    CORPORATE_RESEARCH = "corporate_research"
    MONITORING = "monitoring"
    VERIFICATION = "verification"
    PUBLICATION = "publication"
    DIGITAL_SECURITY = "digital_security"
    RESOURCES = "resources"


@dataclass
class EFEWeights:
    """Ethical Framing Engine weights — Five Pillars of Journalism."""
    accuracy: float = 0.25
    source_protection: float = 0.25
    public_interest: float = 0.20
    proportionality: float = 0.15
    transparency: float = 0.15

    def to_dict(self) -> dict[str, float]:
        return {
            "accuracy": self.accuracy,
            "source_protection": self.source_protection,
            "public_interest": self.public_interest,
            "proportionality": self.proportionality,
            "transparency": self.transparency,
        }


@dataclass
class SkillContext:
    """Context passed to skill chip handlers."""
    investigation_id: str
    user_id: str
    session_id: str | None = None
    platform: str | None = None
    channel_id: str | None = None
    thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Investigation BDI context
    beliefs: list[dict[str, Any]] = field(default_factory=list)
    desires: list[dict[str, Any]] = field(default_factory=list)
    intentions: list[dict[str, Any]] = field(default_factory=list)
    # Investigation-specific
    collection_ids: list[str] = field(default_factory=list)
    target_entities: list[str] = field(default_factory=list)
    hypothesis: str = ""


@dataclass
class SkillRequest:
    """Request to a skill chip."""
    intent: str
    entities: dict[str, Any] = field(default_factory=dict)
    raw_input: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResponse:
    """Response from a skill chip."""
    content: str
    success: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)
    requires_consensus: bool = False
    consensus_action: str | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    produced_entities: list[dict[str, Any]] = field(default_factory=list)
    result_confidence: float = 0.5


class SkillCapability(str, Enum):
    """Capabilities that investigation chips can declare."""
    READ_ALEPH = "read_aleph"
    WRITE_ALEPH = "write_aleph"
    SEARCH_ALEPH = "search_aleph"
    XREF_ALEPH = "xref_aleph"
    INGEST_ALEPH = "ingest_aleph"
    READ_OPENSANCTIONS = "read_opensanctions"
    READ_OPENCORPORATES = "read_opencorporates"
    READ_ICIJ = "read_icij"
    READ_GLEIF = "read_gleif"
    NLP_PROCESSING = "nlp_processing"
    NETWORK_ANALYSIS = "network_analysis"
    EXTERNAL_API = "external_api"
    SEND_NOTIFICATIONS = "send_notifications"
    FILE_ACCESS = "file_access"
    WEB_SCRAPING = "web_scraping"
    HUMAN_SOURCE_DATA = "human_source_data"


class BaseSkillChip(ABC):
    """Abstract base class for all FtM Harness investigation skill chips."""
    name: str = "base_chip"
    description: str = "Base investigation skill chip"
    version: str = "1.0.0"
    domain: SkillDomain = SkillDomain.ENTITY_SEARCH
    efe_weights: EFEWeights | None = None
    required_spans: list[str] = []
    consensus_actions: list[str] = []
    capabilities: list[SkillCapability] = []

    def __init__(self) -> None:
        if self.efe_weights is None:
            self.efe_weights = EFEWeights()

    @abstractmethod
    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Main execution method."""
        ...

    def requires_consensus(self, action: str) -> bool:
        return action in self.consensus_actions

    def get_info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "domain": self.domain.value,
            "efe_weights": self.efe_weights.to_dict() if self.efe_weights else {},
            "capabilities": [c.value for c in self.capabilities],
        }


SkillHandler = Callable[
    [SkillRequest, SkillContext], Coroutine[Any, Any, SkillResponse]
]
