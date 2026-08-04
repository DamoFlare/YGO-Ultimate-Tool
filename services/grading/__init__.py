"""
Hybrid Multi-Agent card grading module.

Combines a deterministic Computer Vision agent (geometric_agent.py) with a local
Vision-Language Model agent (ai_agent.py), merged by the orchestrator (grader.py).
"""
from services.grading.grader import CardGrader

__all__ = ["CardGrader"]
