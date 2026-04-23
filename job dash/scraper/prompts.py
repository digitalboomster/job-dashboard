"""
Instructions for Claude job scoring (used when ANTHROPIC_API_KEY is wired in).

Merge `SCORING_SYSTEM_ADDENDUM` into the system prompt alongside the candidate CV.
"""

SCORING_SYSTEM_ADDENDUM = """
Scoring rules for this candidate:
- Penalize heavily (roughly 20–30 points) if the posting clearly expects roughly 3+ years of relevant experience or reads like a mid/senior bar.
- Boost (about +10 points) when the role explicitly welcomes graduates, interns, apprentices, early-career, or junior applicants.
- The candidate has about 1 year of professional AI engineering, an MSc with Distinction, RL dissertation depth, and very little production ML shipping experience — score with that reality in mind.

The candidate is early-career (~1 year professional AI experience + MSc). Score harshly against senior roles and generously toward roles that explicitly welcome junior/graduate applicants. A 'perfect' domain match at senior level should score 55-65, not 80+.
""".strip()
