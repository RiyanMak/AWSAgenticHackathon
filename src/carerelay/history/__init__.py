"""History Agent: turns a patient's medical history into a coded HistoryProfile.

Three input paths, all producing the same ``HistoryProfile``:

* FHIR R4 bundle (Synthea / Synthea Coherent)  -> ``parsers.fhir``
* MIMIC-IV demo CSV tables for one subject      -> ``parsers.mimic``
* Free-text intake form                         -> ``parsers.intake`` (Comprehend Medical, offline fallback)

The parsers are deterministic. The LLM (via Strands) only writes the plain-language
summary and clinician notes on top of the parsed profile.
"""

from .agent import build_history_profile, make_history_agent, run_history_agent
from .schema import CodedItem, HistoryProfile, PatientSummary

__all__ = [
    "CodedItem",
    "HistoryProfile",
    "PatientSummary",
    "build_history_profile",
    "make_history_agent",
    "run_history_agent",
]
