"""ATS endpoints — add a company with one line using `lever(...)` or `greenhouse(...)`."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class LeverSource(TypedDict):
    kind: Literal["lever"]
    company: str
    slug: str
    region: Literal["us", "eu"]
    flags: NotRequired[list[str]]


class GreenhouseSource(TypedDict):
    kind: Literal["greenhouse"]
    company: str
    board: str
    flags: NotRequired[list[str]]


Source = LeverSource | GreenhouseSource


def lever(
    company: str,
    slug: str,
    region: Literal["us", "eu"] = "us",
    flags: list[str] | None = None,
) -> LeverSource:
    s: LeverSource = {"kind": "lever", "company": company, "slug": slug, "region": region}
    if flags:
        s["flags"] = flags
    return s


def greenhouse(
    company: str,
    board: str,
    flags: list[str] | None = None,
) -> GreenhouseSource:
    s: GreenhouseSource = {"kind": "greenhouse", "company": company, "board": board}
    if flags:
        s["flags"] = flags
    return s


SOURCES: list[Source] = [
    lever("InstaDeep", "instadeep", region="eu"),
    greenhouse("Anthropic", "anthropic", flags=["residency_pipeline"]),
    greenhouse("Monzo", "monzo"),
    greenhouse("Canonical", "canonical"),
    greenhouse("Stripe", "stripe"),
    greenhouse("Cleo", "cleo"),
    # Greenhouse tokens below return 404 as of 2026-04 — replace when you have working slugs.
    # greenhouse("Wise", "wise"),
    # greenhouse("Deliveroo", "deliveroo"),
    # greenhouse("Zilch", "zilch"),
    # Octopus Energy: no public Lever/Greenhouse slug found here — add when known.
]
