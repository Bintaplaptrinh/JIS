from dataclasses import dataclass, field, asdict
from typing import Protocol


@dataclass(frozen=True)
class Context:
    session: str
    cwd: str
    buffer: str
    previous: str = ""
    path: str = ""
    known: tuple[str, ...] = ()


@dataclass
class Candidate:
    command: str
    kind: str
    source: str
    features: dict[str, float] = field(default_factory=dict)
    score: float = 0.0


@dataclass
class Decision:
    kind: str = "none"
    command: str = ""
    score: float = 0.0
    reason: str = "No confident candidate"
    candidates: list[dict] = field(default_factory=list)

    def json(self):
        return asdict(self)


class Provider(Protocol):
    def generate(self, context: Context) -> list[Candidate]: ...


class Ranker(Protocol):
    def rank(self, context: Context, candidates: list[Candidate]) -> list[Candidate]: ...
