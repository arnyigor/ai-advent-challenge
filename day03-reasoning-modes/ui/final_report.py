"""Final analytical summaries for Day 3."""

from scoring import accuracy
from ui.theme import method_label


def pareto_frontier(results, methods):
    points = {}
    for method in methods:
        rows = [r for r in results if r.method == method]
        correct, total = accuracy(rows)
        tokens = sum((r.prompt_tokens or 0) + (r.output_tokens or 0) for r in rows)
        points[method] = {
            "accuracy": correct / total if total else 0.0,
            "correct": correct,
            "total": total,
            "tokens": tokens,
        }

    dominated = set()
    for method, p in points.items():
        for other, q in points.items():
            if method == other:
                continue
            better_or_equal = q["accuracy"] >= p["accuracy"] and q["tokens"] <= p["tokens"]
            strictly_better = q["accuracy"] > p["accuracy"] or q["tokens"] < p["tokens"]
            if better_or_equal and strictly_better:
                dominated.add(method)
                break
    frontier = [m for m in methods if m not in dominated]
    return frontier, [m for m in methods if m in dominated], points


def best_by_accuracy(results, methods):
    rows = []
    for method in methods:
        correct, total = accuracy([r for r in results if r.method == method])
        rows.append((method, correct, total))
    rows.sort(key=lambda x: (x[1], -x[2]), reverse=True)
    return rows[0] if rows else None


def format_pareto_summary(results, methods):
    frontier, dominated, _points = pareto_frontier(results, methods)
    f = ", ".join(method_label(m) for m in frontier) or "-"
    d = ", ".join(method_label(m) for m in dominated) or "-"
    return f"Pareto frontier: {f}\nDominated: {d}"
