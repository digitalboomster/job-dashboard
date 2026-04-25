"""
Instructions for LLM job scoring (OpenAI chat; merge into system prompt with candidate CV).
"""

SCORING_SYSTEM_ADDENDUM = """
Scoring rules for this candidate:
- Penalize heavily (roughly 20–30 points) if the posting clearly expects roughly 3+ years of relevant experience or reads like a mid/senior bar.
- Boost (about +10 points) when the role explicitly welcomes graduates, interns, apprentices, early-career, or junior applicants.
- Boost strongly (about +12 to +18 points) when requirements explicitly include 0 years, 0-1 years, 0-2 years, or "no prior experience required".
- Give a moderate boost (about +6 to +10 points) when the JD is broad/generalist and does not demand a highly specialized niche stack.
- Sector preference bonus: add a small boost (about +3 to +6 points) for energy, utilities, climate-tech, power systems, consulting, or advisory-track AI/data roles.
- The candidate has about 1 year of professional AI engineering, an MSc with Distinction, RL dissertation depth, and very little production ML shipping experience — score with that reality in mind.

The candidate is early-career (~1 year professional AI experience + MSc). Score harshly against senior roles and generously toward roles that explicitly welcome junior/graduate applicants. A 'perfect' domain match at senior level should score 55-65, not 80+.
""".strip()
