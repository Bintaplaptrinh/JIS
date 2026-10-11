from dataclasses import asdict
from .policy import eligible, simple
from .providers import CommandIndex, TypoProvider, HistoryProvider
from .rankers import HeuristicRanker
from .types import Decision


class Engine:
    def __init__(self, store, ranker=None):
        self.providers = (TypoProvider(CommandIndex()), HistoryProvider(store))
        self.ranker = ranker or HeuristicRanker()
        self.fast_ranker = HeuristicRanker()

    def generate(self, context, correction_only=False):
        if not simple(context.buffer):
            return []
        candidates = []
        for provider in self.providers:
            if correction_only and isinstance(provider, HistoryProvider):
                continue
            candidates.extend(provider.generate(context))
        candidates = [c for c in candidates if eligible(c, context)]
        # Corrections take precedence over history; avoid suggesting completions
        # to executable typos that happen to occur in old history.
        corrections = [c for c in candidates if c.kind == "correction"]
        return corrections or candidates

    def decide(self, ranked):
        ranked = ranked[:8]
        if not ranked:
            return Decision()
        top = ranked[0]
        evidence = [asdict(c) for c in ranked]
        if top.kind == "correction":
            if top.score < .64 or (len(ranked) > 1 and abs(top.score-ranked[1].score) < .06):
                return Decision(reason="Ambiguous spelling: abstain", candidates=evidence)
        return Decision(top.kind, top.command, round(top.score, 4), top.source, evidence)

    def suggest(self, context, correction_only=False):
        if not simple(context.buffer):
            return Decision(reason="Complex, private or incomplete input: abstain")
        candidates = self.generate(context, correction_only)
        ranker = self.ranker if correction_only else self.fast_ranker
        return self.decide(ranker.rank(context, candidates))
