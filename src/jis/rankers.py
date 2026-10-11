import math


class HeuristicRanker:
    """Scores are ranking utilities, NOT calibrated probabilities."""
    def rank(self, context, candidates):
        for c in candidates:
            f = c.features
            if c.kind == "correction":
                c.score = .65 * f["similarity"] + .22 * f["common"] + .13 / f["distance"]
            else:
                c.score = (3 * f["session"] + 4 * f["cwd"] + 2 * f["transition"]
                           + .3 * math.log1p(f["frequency"]) + .4 * f["recency"])
        return sorted(candidates, key=lambda c: (-c.score, len(c.command), c.command))

