"""Renderers. Each takes a `ReportContent` and produces one artefact.

A renderer decides only how to draw. It never selects, computes or rewords —
that all happened in the planner, which is what lets the text preview and the
deck make the same claims.
"""
