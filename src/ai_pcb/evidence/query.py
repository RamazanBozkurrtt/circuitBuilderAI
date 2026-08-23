from __future__ import annotations

import re

from ai_pcb.models.knowledge import QueryClassification, QueryIntent

_IDENTIFIER = re.compile(
    r"\b(?:0x[0-9a-f]+|[A-Z][A-Z0-9_]*_[A-Z0-9_]+|"
    r"(?:AVDD|DVDD|PVDD|VBAT|MCLK|BCLK|FSYNC|SPORT|S/PDIF|I2S|TDM)\d*)\b",
    re.IGNORECASE,
)
_SPLIT = re.compile(r"\s+(?:and|versus|vs\.?|or)\s+|[;,]", re.IGNORECASE)


def classify_engineering_query(query: str) -> QueryClassification:
    """Classify common datasheet intents without an LLM or inferred engineering facts."""

    folded = query.casefold()
    exact_terms = list(dict.fromkeys(match.group(0) for match in _IDENTIFIER.finditer(query)))
    if any(term in folded for term in ("layout", "powerpad", "thermal", "heatsink", "pcb")):
        intent = QueryIntent.LAYOUT_THERMAL
        sections = ["layout", "thermal", "package"]
    elif any(term in folded for term in ("latency", "group delay", "propagation delay")):
        intent = QueryIntent.TIMING_LATENCY
        sections = ["digital filter", "timing", "electrical characteristics"]
    elif any(
        term in folded
        for term in ("snr", "thd", "dynamic range", "noise", "distortion", "performance")
    ):
        intent = QueryIntent.PERFORMANCE
        sections = ["performance", "electrical characteristics", "general description"]
    elif any(
        term in folded
        for term in (
            "interface",
            "clock",
            "mclk",
            "bclk",
            "fsync",
            "sport",
            "i2s",
            "tdm",
            "left justified",
            "right justified",
            "serial mode",
        )
    ):
        intent = QueryIntent.INTERFACE_CLOCK
        sections = ["serial audio", "interface", "clock", "processor features"]
    elif any(
        term in folded
        for term in (
            "supply",
            "voltage",
            "current",
            "impedance",
            "ohm",
            "output power",
            "power per",
            "operating range",
            "switching frequency",
        )
    ):
        intent = QueryIntent.ELECTRICAL_SPECIFICATION
        sections = [
            "electrical characteristics",
            "recommended operating conditions",
            "power supply",
            "general description",
        ]
    elif exact_terms or any(term in folded for term in ("register", " pin ", " rail ")):
        intent = QueryIntent.EXACT_IDENTIFIER
        sections = ["register", "pin functions", "processor features"]
    else:
        intent = QueryIntent.GENERAL_SEMANTIC
        sections = ["features", "general description", "applications"]

    parts = [part.strip() for part in _SPLIT.split(query) if len(part.strip().split()) >= 2]
    decomposed = list(dict.fromkeys([query, *parts]))
    prefer_overview = (
        any(
            term in folded
            for term in (
            "number of",
            " count",
                "channels",
                "supported sampling rate",
                "sampling rate",
                "sample rates",
                "maximum",
                "target applications",
                "operating range",
                "switching frequency",
                "power supply voltages",
            )
        )
        or len(parts) > 1
        or len(exact_terms) > 1
        or len(re.findall(r"\d+(?:\.\d+)?", query)) > 2
    )
    prefer_tables = intent in {
        QueryIntent.ELECTRICAL_SPECIFICATION,
        QueryIntent.TIMING_LATENCY,
        QueryIntent.EXACT_IDENTIFIER,
    } or any(term in folded for term in ("conditions", "range", "number of"))
    return QueryClassification(
        intent=intent,
        exact_terms=exact_terms,
        decomposed_queries=decomposed,
        preferred_sections=sections,
        prefer_tables=prefer_tables,
        prefer_overview=prefer_overview,
    )
