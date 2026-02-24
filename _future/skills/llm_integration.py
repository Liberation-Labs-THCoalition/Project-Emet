"""LLM integration layer for skill chips.

Provides shared infrastructure for skill chips to use LLM capabilities:
  - Investigative system prompts with methodology encoding
  - Structured JSON output parsing with fallback
  - Evidence grounding (entity/document citation)
  - Confidence calibration
  - Token usage tracking
  - Consensus gate preparation (flagging high-stakes outputs)

Usage in a skill chip::

    class MyChip(BaseSkillChip):
        async def handle(self, request, context):
            llm = SkillLLMHelper(context)
            result = await llm.analyze(
                prompt="Analyze this corporate structure...",
                schema={"risk_level": "str", "explanation": "str"},
                evidence=entities,
            )
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from emet.cognition.llm_base import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompts encoding investigative methodology
# ---------------------------------------------------------------------------

SYSTEM_PROMPTS: dict[str, str] = {
    "investigative_base": (
        "You are an investigative analysis assistant supporting journalists. "
        "Your role is to analyze data objectively and identify patterns worthy "
        "of further investigation. You MUST:\n"
        "1. Ground all claims in evidence from the provided data\n"
        "2. Distinguish between confirmed facts and inferences\n"
        "3. Assign confidence scores (0.0-1.0) to all findings\n"
        "4. Flag findings that require human verification\n"
        "5. Never fabricate entities, relationships, or facts\n"
        "6. Acknowledge data limitations and gaps\n"
        "7. Respond with valid JSON when structured output is requested"
    ),

    "entity_extraction": (
        "You are a named entity recognition specialist for investigative journalism. "
        "Extract persons, organizations, locations, dates, and monetary amounts from text. "
        "For each entity, provide:\n"
        "- name: The entity as it appears in text\n"
        "- type: PERSON, ORGANIZATION, LOCATION, DATE, MONEY, or OTHER\n"
        "- confidence: 0.0-1.0 certainty score\n"
        "- context: Brief surrounding context\n"
        "Be conservative — only extract entities you're confident about."
    ),

    "corporate_analysis": (
        "You are a corporate structure analyst supporting investigative journalists. "
        "Analyze corporate ownership, directorship, and financial relationships. "
        "You are trained to identify:\n"
        "- Shell company indicators (nominee directors, unusual jurisdictions, "
        "  circular ownership, minimal economic activity)\n"
        "- Beneficial ownership obfuscation patterns\n"
        "- Jurisdictional arbitrage and treaty shopping\n"
        "- Unusual corporate formation timing\n"
        "Ground all findings in the provided entity data."
    ),

    "story_development": (
        "You are a narrative analyst supporting investigative journalists. "
        "Help structure investigative findings into coherent story narratives. "
        "You should:\n"
        "- Identify the strongest narrative thread supported by evidence\n"
        "- Highlight the public interest angle\n"
        "- Identify gaps that need additional reporting\n"
        "- Suggest sources to approach for comment\n"
        "- Flag potential legal risks in publication\n"
        "Never invent facts. Clearly distinguish confirmed information from leads."
    ),

    "verification": (
        "You are a fact-checking analyst supporting investigative journalists. "
        "Cross-reference claims against available evidence and identify:\n"
        "- Claims supported by multiple independent sources\n"
        "- Claims with only single-source support\n"
        "- Claims that contradict available evidence\n"
        "- Claims that cannot be verified with available data\n"
        "Be rigorous and skeptical. Better to under-claim than over-claim."
    ),

    "financial_analysis": (
        "You are a financial crime analyst supporting investigative journalists. "
        "Analyze financial flows, transactions, and corporate structures for:\n"
        "- Money laundering indicators (layering, smurfing, round-tripping)\n"
        "- Unusual transaction patterns\n"
        "- Conflict of interest indicators\n"
        "- Pay-to-play patterns between donors and contract recipients\n"
        "Ground all findings in provided financial data."
    ),
}


# ---------------------------------------------------------------------------
# Token usage tracker
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Tracks LLM token usage across a workflow."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    call_count: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list)

    def record(self, response: LLMResponse, purpose: str = "") -> None:
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens
        self.total_cost_usd += response.cost_usd
        self.call_count += 1
        self.calls.append({
            "purpose": purpose,
            "model": response.model,
            "provider": response.provider.value,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cost_usd": response.cost_usd,
        })

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def summary(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_cost_usd": self.total_cost_usd,
            "call_count": self.call_count,
        }


# ---------------------------------------------------------------------------
# Structured output parser
# ---------------------------------------------------------------------------


def parse_json_response(text: str) -> dict[str, Any] | list[Any] | None:
    """Parse JSON from LLM response, handling common formatting issues.

    LLMs often wrap JSON in markdown code fences or add preamble text.
    This function strips those artifacts before parsing.
    """
    text = text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object/array in text
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue

    return None


# ---------------------------------------------------------------------------
# Skill LLM Helper
# ---------------------------------------------------------------------------


class SkillLLMHelper:
    """LLM integration helper for skill chips.

    Wraps the LLM client with investigative methodology prompts,
    structured output parsing, and token tracking.

    Parameters
    ----------
    llm_client:
        The LLM client to use for calls.
    domain:
        Investigative domain (maps to system prompt).
    usage_tracker:
        Optional token usage tracker.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        domain: str = "investigative_base",
        usage_tracker: TokenUsage | None = None,
    ) -> None:
        self._llm = llm_client
        self._domain = domain
        self._system = SYSTEM_PROMPTS.get(domain, SYSTEM_PROMPTS["investigative_base"])
        self._usage = usage_tracker or TokenUsage()

    @property
    def usage(self) -> TokenUsage:
        return self._usage

    async def analyze(
        self,
        prompt: str,
        *,
        evidence: list[dict[str, Any]] | None = None,
        tier: str = "balanced",
        max_tokens: int = 1024,
        purpose: str = "",
    ) -> str:
        """Run an analysis prompt with evidence grounding.

        Parameters
        ----------
        prompt:
            The analysis question/instruction.
        evidence:
            List of FtM entity dicts to ground the analysis in.
        tier:
            LLM tier (fast/balanced/powerful).
        max_tokens:
            Maximum response tokens.
        purpose:
            Description for usage tracking.
        """
        full_prompt = prompt
        if evidence:
            evidence_text = self._format_evidence(evidence)
            full_prompt = f"{prompt}\n\n## Available Evidence\n{evidence_text}"

        response = await self._llm.complete(
            full_prompt,
            system=self._system,
            tier=tier,
            max_tokens=max_tokens,
            temperature=0.3,
        )

        self._usage.record(response, purpose or "analyze")
        return response.text

    async def analyze_structured(
        self,
        prompt: str,
        output_schema: dict[str, str],
        *,
        evidence: list[dict[str, Any]] | None = None,
        tier: str = "balanced",
        max_tokens: int = 1024,
        purpose: str = "",
    ) -> dict[str, Any]:
        """Run analysis expecting structured JSON output.

        Parameters
        ----------
        prompt:
            The analysis instruction.
        output_schema:
            ``{field_name: description}`` of expected JSON fields.
        evidence:
            FtM entities for grounding.
        tier:
            LLM tier.

        Returns
        -------
        Parsed JSON dict, or ``{"error": "..."}`` on parse failure.
        """
        schema_desc = "\n".join(f'  "{k}": {v}' for k, v in output_schema.items())

        structured_prompt = (
            f"{prompt}\n\n"
            f"Respond with ONLY a JSON object containing these fields:\n"
            f"{{{{\n{schema_desc}\n}}}}\n\n"
            f"Do not include any text before or after the JSON."
        )

        text = await self.analyze(
            structured_prompt,
            evidence=evidence,
            tier=tier,
            max_tokens=max_tokens,
            purpose=purpose or "structured_analyze",
        )

        result = parse_json_response(text)
        if result is None:
            logger.warning("Failed to parse structured LLM output")
            return {"error": "Failed to parse LLM response", "raw_text": text[:200]}

        if isinstance(result, dict):
            return result
        return {"data": result}

    async def extract_entities(
        self,
        text: str,
        *,
        tier: str = "fast",
        purpose: str = "",
    ) -> list[dict[str, Any]]:
        """Extract named entities from text using LLM.

        Returns list of ``{name, type, confidence, context}`` dicts.
        """
        prompt = (
            f"Extract all named entities from the following text.\n\n"
            f'Text: """{text}"""\n\n'
            f"Return a JSON array of objects with these fields:\n"
            f'  "name": the entity name as it appears\n'
            f'  "type": one of PERSON, ORGANIZATION, LOCATION, DATE, MONEY, OTHER\n'
            f'  "confidence": 0.0-1.0 certainty score\n'
            f"Only include entities you are confident about."
        )

        response = await self._llm.complete(
            prompt,
            system=SYSTEM_PROMPTS["entity_extraction"],
            tier=tier,
            max_tokens=1024,
            temperature=0.0,
        )

        self._usage.record(response, purpose or "entity_extraction")
        result = parse_json_response(response.text)

        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "entities" in result:
            return result["entities"]
        return []

    async def classify_risk(
        self,
        entity_data: dict[str, Any],
        risk_factors: list[str],
        *,
        tier: str = "balanced",
        purpose: str = "",
    ) -> dict[str, Any]:
        """Classify risk level for an entity.

        Returns ``{risk_level, score, factors, explanation}``.
        """
        factors_str = "\n".join(f"- {f}" for f in risk_factors)
        entity_str = json.dumps(entity_data, indent=2, default=str)

        prompt = (
            f"Assess the risk profile of the following entity:\n\n"
            f"{entity_str}\n\n"
            f"Consider these risk factors:\n{factors_str}\n\n"
            f"Respond with JSON: {{\"risk_level\": \"low|medium|high|critical\", "
            f"\"score\": 0.0-1.0, \"active_factors\": [...], \"explanation\": \"...\"}}"
        )

        return await self.analyze_structured(
            prompt,
            output_schema={
                "risk_level": "One of: low, medium, high, critical",
                "score": "Risk score from 0.0 to 1.0",
                "active_factors": "List of risk factors that apply",
                "explanation": "Brief explanation of the assessment",
            },
            tier=tier,
            purpose=purpose or "risk_classification",
        )

    async def generate_narrative(
        self,
        findings: dict[str, Any],
        *,
        angle: str = "",
        tier: str = "powerful",
        purpose: str = "",
    ) -> dict[str, Any]:
        """Generate investigation narrative from findings.

        Returns ``{headline, summary, key_findings, gaps, next_steps}``.
        """
        findings_str = json.dumps(findings, indent=2, default=str)

        prompt = (
            f"Based on the following investigation findings, develop a narrative structure:\n\n"
            f"{findings_str}\n\n"
        )
        if angle:
            prompt += f"Suggested angle: {angle}\n\n"

        prompt += (
            f"Respond with JSON containing:\n"
            f'  "headline": Proposed investigation headline\n'
            f'  "summary": 2-3 sentence executive summary\n'
            f'  "key_findings": Array of the most significant findings\n'
            f'  "evidence_gaps": What additional reporting is needed\n'
            f'  "next_steps": Recommended next actions for the journalist\n'
            f'  "legal_considerations": Any publication risks to flag'
        )

        return await self.analyze_structured(
            prompt,
            output_schema={
                "headline": "Investigation headline",
                "summary": "Executive summary (2-3 sentences)",
                "key_findings": "Array of significant findings",
                "evidence_gaps": "Array of gaps needing more reporting",
                "next_steps": "Array of recommended next actions",
                "legal_considerations": "Publication risk notes",
            },
            tier=tier,
            purpose=purpose or "narrative_generation",
        )

    async def verify_claims(
        self,
        claims: list[str],
        evidence: list[dict[str, Any]],
        *,
        tier: str = "balanced",
        purpose: str = "",
    ) -> list[dict[str, Any]]:
        """Verify claims against available evidence.

        Returns list of ``{claim, status, supporting_evidence, confidence}``.
        """
        claims_str = "\n".join(f"- {c}" for c in claims)
        evidence_str = self._format_evidence(evidence)

        prompt = (
            f"Verify each of these claims against the available evidence:\n\n"
            f"Claims:\n{claims_str}\n\n"
            f"Evidence:\n{evidence_str}\n\n"
            f"For each claim, respond with JSON array:\n"
            f'  "claim": The original claim\n'
            f'  "status": "supported" | "contradicted" | "unverifiable" | "partially_supported"\n'
            f'  "supporting_evidence": Which evidence supports/contradicts\n'
            f'  "confidence": 0.0-1.0\n'
            f'  "notes": Any caveats or limitations'
        )

        text = await self.analyze(
            prompt,
            tier=tier,
            purpose=purpose or "verification",
        )

        result = parse_json_response(text)
        if isinstance(result, list):
            return result
        return []

    # -- Evidence formatting --------------------------------------------------

    @staticmethod
    def _format_evidence(entities: list[dict[str, Any]], max_entities: int = 30) -> str:
        """Format FtM entities as evidence text for LLM prompts."""
        lines: list[str] = []

        for entity in entities[:max_entities]:
            schema = entity.get("schema", "Unknown")
            props = entity.get("properties", {})
            name = (props.get("name", []) or [entity.get("id", "?")[:12]])[0]

            # Key properties
            details = []
            for key in ("country", "jurisdiction", "incorporationDate",
                        "registrationNumber", "address", "date"):
                vals = props.get(key, [])
                if vals:
                    details.append(f"{key}={vals[0]}")

            detail_str = f" ({', '.join(details)})" if details else ""
            provenance = entity.get("_provenance", {}).get("source", "")
            source_str = f" [source: {provenance}]" if provenance else ""

            lines.append(f"- [{schema}] {name}{detail_str}{source_str}")

        if len(entities) > max_entities:
            lines.append(f"  ... and {len(entities) - max_entities} more entities")

        return "\n".join(lines) if lines else "No evidence provided."
