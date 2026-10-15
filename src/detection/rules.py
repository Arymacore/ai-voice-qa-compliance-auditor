"""
rules.py

The explicit compliance rule set the detection engine checks calls against.

These are simplified, FDCPA-style debt-collection rules chosen for this
course project (one well-documented public standard, per our charter).
Each rule is plain data, so adding or changing a rule never requires
touching detector logic.

Required rules: the agent MUST say something matching at least one pattern.
Prohibited rules: the agent must NOT say anything matching any pattern.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    rule_id: str
    name: str
    description: str
    rule_type: str  # "required" | "prohibited"
    severity: str  # "high" | "medium" | "low"
    patterns: tuple[str, ...]  # regex patterns, matched case-insensitively


REQUIRED_RULES = [
    Rule(
        rule_id="R1",
        name="Recording disclosure",
        description="Agent must tell the customer the call may be recorded.",
        rule_type="required",
        severity="high",
        patterns=(
            r"may be recorded",
            r"being recorded",
            r"recorded for (?:quality|training)",
        ),
    ),
    Rule(
        rule_id="R2",
        name="Debt collector identification",
        description="Agent must state this is an attempt to collect a debt / from a debt collector.",
        rule_type="required",
        severity="high",
        patterns=(
            r"attempt to collect a debt",
            r"from a debt collector",
        ),
    ),
    Rule(
        rule_id="R3",
        name="Dispute rights notice",
        description="Agent must inform the customer of their right to dispute the debt.",
        rule_type="required",
        severity="high",
        patterns=(
            r"right to dispute",
            r"dispute (?:this|the) debt",
        ),
    ),
    Rule(
        rule_id="R4",
        name="Agent identification",
        description="Agent must identify themselves by name.",
        rule_type="required",
        severity="medium",
        patterns=(
            r"my name is \w+",
            r"this is \w+ (?:calling|from)",
        ),
    ),
]

PROHIBITED_RULES = [
    Rule(
        rule_id="P1",
        name="Threats of consequences",
        description="Agent must not threaten escalation, arrest, or legal/seizure action.",
        rule_type="prohibited",
        severity="high",
        patterns=(
            r"we(?:'re| are) going to escalate",
            r"there will be consequences",
            r"you will be arrested",
            r"we(?:'ll| will) (?:sue|garnish|seize)",
        ),
    ),
    Rule(
        rule_id="P2",
        name="Pressure tactics",
        description="Agent must not demand immediate payment under pressure.",
        rule_type="prohibited",
        severity="medium",
        patterns=(
            r"you need to pay (?:this |it )?(?:today|right now)",
            r"pay (?:something )?(?:today|right now)",
        ),
    ),
]

ALL_RULES = REQUIRED_RULES + PROHIBITED_RULES