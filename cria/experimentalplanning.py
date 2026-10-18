"""Public compatibility reexports for explicitly opted-in planning stages.

Planner owns selection and executable stage contracts beside its DEFINITIONS;
planningcontracts owns shared data/support. These are the same canonical objects,
not parallel definitions or wrappers. Importing them never enables planning.
"""
from .planner import (PlanningAttempt, Ask, GatherCall, GatherDefinition,
                      CoverageDefinition, ReadinessInput, ReadinessResult,
                      ReadinessDefinition, RevisionInput, RevisionResult,
                      RevisionDefinition, PlanningDefinition, PlanningSelection)
from .planningcontracts import EventLog
