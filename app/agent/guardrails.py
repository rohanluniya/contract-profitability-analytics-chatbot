"""Safety, prompt-injection, financial anomaly, and numeric grounding guardrails for Apex Margin Advisor."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.semantic.service import ToolPayload, semantic_catalog

INJECTION_PATTERNS = [
    (
        r"\bignore\s+(all\s+)?(previous|prior|system)\s+instructions\b",
        "Prompt-injection attempt blocked: Apex Margin Advisor governance rules cannot be overridden.",
    ),
    (
        r"\b(drop\s+table|truncate\s+table|delete\s+from|insert\s+into|update\s+\w+\s+set|alter\s+table|xp_cmdshell)\b",
        "Arbitrary or mutating SQL is strictly blocked. Only `/log` may write governed remediation records to CAT (`Fact_ActionLog`).",
    ),
    (
        r"\bselect\b.{1,80}\bfrom\b\s+(owms|efl|gte|crc|cat|vwm|proddta|sys|information_schema)",
        "Direct raw SQL execution is blocked. Ask a portfolio question or use `/summary`, `/exceptions`, `/trace`, or `/log`.",
    ),
    (
        r"\b(openai_api_key|gemini_api_key|mssql_sa_password|mssql_app_password|app_access_code|api[_\s-]?key|password|\.env)\b",
        "Credential and environment inspection requests are blocked by security policy.",
    ),
    (
        r"\b(proddta|bvcoreprod|corporate\s+vpn|connect\s+to\s+prod|production\s+jde)\b",
        "External/production ERP connectivity is disabled. Apex Margin Advisor operates strictly on isolated synthetic TIC benchmark data.",
    ),
]

BAD_SPECIAL_PURPOSE_RE = re.compile(
    r"(sp-rev-901.{0,60}\b100(?:\.0)?%|sp-cost-902.{0,60}-100(?:\.0)?%|disc-specialist-9.{0,60}\$0\b)",
    re.IGNORECASE,
)

NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])([+-]?\d{1,3}(?:,\d{3})+|[+-]?\d+(?:\.\d+)?)(?![A-Za-z0-9_])")


@dataclass
class GuardrailVerdict:
    ok: bool
    reason: str = ""
    used_template: bool = False


def check_prompt_safety(question: str) -> str | None:
    q = (question or "").strip()
    for pat, msg in INJECTION_PATTERNS:
        if re.search(pat, q, flags=re.IGNORECASE | re.DOTALL):
            return msg
    return None


def check_out_of_scope(question: str) -> str | None:
    q = (question or "").strip().lower()
    for item in semantic_catalog().get("out_of_scope_topics", []):
        if re.search(item["pattern"], q, flags=re.IGNORECASE):
            return item["reason"]
    return None


def _allowed_numbers(payload: ToolPayload) -> set[str]:
    blob = " ".join([
        payload.headline,
        " ".join(payload.facts),
        " ".join(payload.warnings),
        payload.period_label,
    ])
    if payload.df is not None and not payload.df.empty:
        blob += " " + payload.df.to_string()
    allowed: set[str] = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "12", "14", "15", "20", "25", "30", "45", "80", "100", "115", "120", "150", "2026", "5000", "8000", "9000"}
    for m in NUMBER_TOKEN_RE.finditer(blob):
        raw = m.group(1).lstrip("+").replace(",", "")
        allowed.add(raw)
        try:
            fval = float(raw)
            allowed.add(str(int(round(fval))))
            allowed.add(f"{fval:.1f}")
            allowed.add(f"{abs(fval):.1f}")
            allowed.add(str(int(round(abs(fval)))))
        except ValueError:
            pass
    return allowed


def verify_prose(prose: str, payload: ToolPayload) -> GuardrailVerdict:
    """Verify LLM prose preserves Special Purpose N/A rules, unmapped rate rules, and numeric grounding."""
    if not prose or not prose.strip():
        return GuardrailVerdict(ok=False, reason="empty_llm_output", used_template=True)
    if BAD_SPECIAL_PURPOSE_RE.search(prose):
        return GuardrailVerdict(ok=False, reason="special_purpose_or_zero_rate_violation", used_template=True)

    allowed = _allowed_numbers(payload)
    scrubbed = re.sub(r"\b202\d-\d{2}(?:-\d{2})?\b", " ", prose)
    scrubbed = re.sub(r"\b(?:FS|TM|SP|BU|EXC|SVC|TSK|PRJ|ACT|GL|DISC)-[A-Z0-9-]+\b", " ", scrubbed, flags=re.IGNORECASE)

    bad = []
    for m in NUMBER_TOKEN_RE.finditer(scrubbed):
        tok = m.group(1).lstrip("+").replace(",", "")
        if tok not in allowed:
            bad.append(m.group(1))
    if bad:
        return GuardrailVerdict(ok=False, reason=f"ungrounded_numbers:{','.join(bad[:3])}", used_template=True)
    return GuardrailVerdict(ok=True, reason="verified", used_template=False)


def deterministic_prose(payload: ToolPayload) -> str:
    """Render clean, direct-answer-first deterministic prose directly from ToolPayload."""
    lines = [payload.headline]
    if payload.facts:
        lines.append("")
        for f in payload.facts[:5]:
            lines.append(f"- {f}")
    for w in payload.warnings[:3]:
        lines.append(f"\n> **Integrity & Risk Alert:** {w}")
    return "\n".join(lines).strip()
