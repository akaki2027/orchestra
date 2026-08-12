"""Privacy-tiered routing: decide what is allowed to leave this machine.

The product claim is "your sensitive data never reaches a hosted model, and the
app shows you what did leave." A claim like that is only worth making if it is
enforced somewhere it cannot be forgotten, so this module provides the policy
and the ledger, and `providers/guard.py` applies it to *every* provider the
registry hands out. No call site opts in; call sites cannot opt out.

Detection is deliberately deterministic — regexes and checksums, not a model.
A classifier that is right 95% of the time cannot back a guarantee, and it
cannot be audited by someone reading the source. The cost of that choice is
real and is stated plainly in `LIMITS` below and in the README: this catches
structured identifiers, not names, addresses, or the fact that a paragraph is
about someone's medical history.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

Mode = Literal["off", "redact", "strict"]

LIMITS = (
    "Detection is pattern-based. It reliably catches structured identifiers — "
    "emails, phone numbers, card numbers, keys, IPs, file paths with your "
    "username. It does NOT catch names, street addresses, dates of birth, or "
    "the fact that a sentence is about someone's health or finances. For those, "
    "mark the agent local-only so its model never changes."
)


# --------------------------------------------------------------- detectors

@dataclass(frozen=True)
class Detector:
    category: str
    label: str
    pattern: re.Pattern[str]
    validator: Callable[[str], bool] | None = None
    group: int = 0


def _luhn(value: str) -> bool:
    """Card numbers have a checksum; use it so we don't redact order numbers."""
    digits = [int(c) for c in value if c.isdigit()]
    if not 12 <= len(digits) <= 19:
        return False
    total, parity = 0, len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _valid_ssn(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 9:
        return False
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    # Ranges the SSA never issues — filters out invoice and part numbers.
    return not (
        area in {"000", "666"}
        or area.startswith("9")
        or group == "00"
        or serial == "0000"
    )


def _real_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    # Version strings like 1.2.3.4 are technically valid addresses; requiring a
    # non-trivial first octet trims the most common false positive.
    return not value.startswith(("0.", "1.2.3"))


DETECTORS: tuple[Detector, ...] = (
    Detector(
        "secret",
        "API key or token",
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}"
            r"|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}"
            r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|glpat-[A-Za-z0-9_-]{16,})"
        ),
    ),
    Detector(
        "email",
        "Email address",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    Detector(
        "card",
        "Payment card number",
        re.compile(r"\b(?:\d[ -]?){12,19}\b"),
        validator=_luhn,
    ),
    Detector(
        "ssn",
        "US Social Security number",
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        validator=_valid_ssn,
    ),
    Detector(
        "phone",
        "Phone number",
        # The trailing guard is (?!\d) rather than (?![\w.]) so a number that
        # ends a sentence still matches — "call 415-555-0142." is the common case.
        re.compile(
            r"(?<![\w.])(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?!\d)"
        ),
    ),
    Detector(
        "ip",
        "IP address",
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        validator=_real_ip,
    ),
    Detector(
        "path",
        "Local file path with your username",
        # The final class excludes '.' so a path ending a sentence does not
        # absorb the full stop and come back with it on restore.
        re.compile(r"(?:/(?:home|Users)/|[A-Za-z]:\\Users\\)[^\s\"'<>|,;]*[^\s\"'<>|,;.]"),
    ),
    Detector(
        "iban",
        "Bank account (IBAN)",
        re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    ),
)

ALL_CATEGORIES = tuple(d.category for d in DETECTORS)

# On by default. `path` is included because a home directory leaks your real
# name to a hosted model more often than people expect.
DEFAULT_CATEGORIES = ALL_CATEGORIES


@dataclass
class Finding:
    category: str
    label: str
    start: int
    end: int
    value: str


def scan(text: str, categories: Iterable[str] | None = None) -> list[Finding]:
    """Find sensitive spans, longest-match-wins on overlap."""
    if not text:
        return []
    enabled = set(categories if categories is not None else DEFAULT_CATEGORIES)

    findings: list[Finding] = []
    for detector in DETECTORS:
        if detector.category not in enabled:
            continue
        for match in detector.pattern.finditer(text):
            value = match.group(detector.group)
            if detector.validator and not detector.validator(value):
                continue
            findings.append(
                Finding(detector.category, detector.label, match.start(), match.end(), value)
            )

    # A card number inside a longer string, or an email inside a path, would
    # otherwise produce nested placeholders. Keep the widest span.
    findings.sort(key=lambda f: (f.start, -(f.end - f.start)))
    kept: list[Finding] = []
    for finding in findings:
        if kept and finding.start < kept[-1].end:
            continue
        kept.append(finding)
    return kept


# --------------------------------------------------------------- redaction

PLACEHOLDER_RE = re.compile(r"\[([A-Z]+)_(\d+)\]")


@dataclass
class Redaction:
    text: str
    mapping: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.mapping)


def redact(
    text: str,
    categories: Iterable[str] | None = None,
    mapping: dict[str, str] | None = None,
) -> Redaction:
    """Replace sensitive spans with stable placeholders.

    The same value always gets the same placeholder, within a run — so a model
    that sees `[EMAIL_1]` twice can still tell it is one person. Passing an
    existing `mapping` extends it, which is what keeps placeholders consistent
    across the several calls that make up one run.
    """
    findings = scan(text, categories)
    if not findings:
        return Redaction(text, dict(mapping or {}), {})

    mapping = dict(mapping or {})
    reverse = {value: token for token, value in mapping.items()}
    counts: dict[str, int] = {}

    out, cursor = [], 0
    for finding in findings:
        token = reverse.get(finding.value)
        if token is None:
            existing = sum(1 for t in mapping if t.startswith(f"[{finding.category.upper()}_"))
            token = f"[{finding.category.upper()}_{existing + 1}]"
            mapping[token] = finding.value
            reverse[finding.value] = token
        out.append(text[cursor : finding.start])
        out.append(token)
        cursor = finding.end
        counts[finding.category] = counts.get(finding.category, 0) + 1

    out.append(text[cursor:])
    return Redaction("".join(out), mapping, counts)


def restore(text: str, mapping: dict[str, str]) -> str:
    """Put the real values back. Only ever called on output shown locally."""
    if not mapping or not text:
        return text
    return PLACEHOLDER_RE.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)


# ------------------------------------------------------------ host trust

def classify_host(host: str) -> Literal["private", "public", "unknown"]:
    """Is this address on this machine or this network?

    Shared with the research fetcher, which needs the same question asked the
    other way round. Resolution failure is `unknown` so each caller can fail
    closed in its own direction — here that means "treat it as remote".
    """
    if not host:
        return "unknown"
    if host.lower() in {"localhost", "localhost.localdomain"}:
        return "private"
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return "unknown"

    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return "unknown"
        if not (addr.is_private or addr.is_loopback or addr.is_link_local):
            return "public"
    return "private"


def is_local_host(host: str) -> bool:
    """Fail closed: anything we cannot resolve is treated as remote."""
    return classify_host(host) == "private"


# ---------------------------------------------------------------- policy

@dataclass
class Policy:
    mode: Mode = "off"
    categories: tuple[str, ...] = DEFAULT_CATEGORIES
    local_fallback: dict[str, str] | None = None

    @property
    def active(self) -> bool:
        return self.mode in ("redact", "strict")

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "Policy":
        raw = cfg.get("privacy") or {}
        mode = raw.get("mode") if raw.get("mode") in ("off", "redact", "strict") else "off"
        cats = raw.get("categories")
        if not isinstance(cats, list) or not cats:
            categories = DEFAULT_CATEGORIES
        else:
            categories = tuple(c for c in cats if c in ALL_CATEGORIES)
        fallback = raw.get("local_fallback")
        if not (isinstance(fallback, dict) and fallback.get("provider") and fallback.get("model")):
            fallback = None
        return cls(mode=mode, categories=categories, local_fallback=fallback)


class BlockedEgress(RuntimeError):
    """Strict mode refused to send sensitive text to a hosted model."""

    def __init__(self, provider: str, categories: list[str]) -> None:
        self.provider = provider
        self.categories = categories
        pretty = ", ".join(sorted(set(categories)))
        super().__init__(
            f"Blocked: this text contains {pretty} and privacy mode is set to strict, "
            f"so it will not be sent to {provider}. Route this step to a local model, "
            f"or switch the mode to Redact."
        )


# ---------------------------------------------------------------- ledger

@dataclass
class Egress:
    """One outbound call, recorded whether or not anything was redacted."""

    provider: str
    model: str
    destination: Literal["local", "remote"]
    chars: int
    redacted: dict[str, int] = field(default_factory=dict)
    blocked: bool = False
    at: float = field(default_factory=time.time)
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "destination": self.destination,
            "chars": self.chars,
            "redacted": self.redacted,
            "blocked": self.blocked,
            "at": self.at,
            "note": self.note,
        }


@dataclass
class Ledger:
    """Per-run record of everything that crossed the machine boundary.

    This is the receipt behind the claim. It records local calls too — being
    able to say "6 calls, 4 never left this machine" is the whole point, and a
    ledger that only lists remote calls cannot prove the ratio.
    """

    policy: Policy
    entries: list[Egress] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)

    def record(self, entry: Egress) -> None:
        self.entries.append(entry)

    def summary(self) -> dict[str, Any]:
        remote = [e for e in self.entries if e.destination == "remote"]
        totals: dict[str, int] = {}
        for entry in self.entries:
            for category, count in entry.redacted.items():
                totals[category] = totals.get(category, 0) + count
        return {
            "mode": self.policy.mode,
            "calls": len(self.entries),
            "local_calls": len(self.entries) - len(remote),
            "remote_calls": len(remote),
            "remote_chars": sum(e.chars for e in remote),
            "blocked": sum(1 for e in self.entries if e.blocked),
            "redacted": totals,
            "protected_values": len(self.mapping),
            "destinations": sorted({e.provider for e in remote}),
            "entries": [e.as_dict() for e in self.entries],
        }


_LEDGER: ContextVar[Ledger | None] = ContextVar("orchestra_ledger", default=None)


def current_ledger() -> Ledger | None:
    return _LEDGER.get()


def use_ledger(ledger: Ledger | None):
    """Bind a ledger for this task and everything it spawns.

    asyncio copies the context when a task is created, so every sub-agent
    launched by the runner inherits this without it being threaded through
    call signatures — which is what keeps the guard impossible to skip.
    """
    return _LEDGER.set(ledger)


def reset_ledger(token) -> None:
    _LEDGER.reset(token)
