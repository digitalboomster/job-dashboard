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


# Greenhouse board tokens verified via public Job Board API (404 = remove or fix token).
SOURCES: list[Source] = [
    lever("InstaDeep", "instadeep", region="eu"),
    greenhouse("Baringa", "baringa", flags=["consulting"]),
    greenhouse("Watershed", "watershed", flags=["energy", "climate"]),
    greenhouse("Sunnova", "sunnova", flags=["energy"]),
    greenhouse("Anthropic", "anthropic"),
    greenhouse("DeepMind", "deepmind"),
    greenhouse("Databricks", "databricks"),
    greenhouse("Scale AI", "scaleai"),
    greenhouse("Snorkel AI", "snorkelai"),
    greenhouse("Runpod", "runpod"),
    greenhouse("Comet", "comet"),
    greenhouse("Stability AI", "stabilityai"),
    greenhouse("Lightricks", "lightricks"),
    greenhouse("CoreWeave", "coreweave"),
    greenhouse("Waymo", "waymo"),
    greenhouse("Applied Intuition", "appliedintuition"),
    greenhouse("Airbnb", "airbnb"),
    greenhouse("Robinhood", "robinhood"),
    greenhouse("Duolingo", "duolingo"),
    greenhouse("Monzo", "monzo"),
    greenhouse("Canonical", "canonical"),
    greenhouse("Stripe", "stripe"),
    greenhouse("Cleo", "cleo"),
]
