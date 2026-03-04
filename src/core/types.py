from dataclasses import dataclass


@dataclass(frozen=True)
class BoundaryCondition:
    name: str
    condition: str
    rationale: str
