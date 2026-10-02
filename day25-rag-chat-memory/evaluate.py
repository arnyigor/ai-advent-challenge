"""Two long scenarios through the real chat; structural checks on every turn.

Hard checks per answered turn: sources and quotes present, quotes verbatim,
source metadata matching the retrieved chunks, task state never errors.
Hard checks per scenario: the goal survives to the last turn and every user
constraint stays recorded. Unknown turns must refuse without fake evidence.
Required terms and state snapshots are reported for review, not enforced.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from chat_agent import ChatAgent, DEFAULT_MODEL, DEFAULT_DATA_DIR

DAY = Path(__file__).resolve().parent
SCENARIOS_DIR = DAY / "scenarios"
DEFAULT_REPORT = DAY / "results" / "scenarios.json"


def load_scenarios() -> list[dict]:
    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("scenario_*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        if not 10 <= len(scenario["messages"]) <= 15:
            raise ValueError(f"{path.name}: нужен сценарий на 10–15 сообщений")
        scenarios.append(scenario)
    if len(scenarios) != 2:
        raise ValueError("Нужны ровно два сценария")
    return scenarios


def audit_turn(result: dict, expect: dict) -> dict:
    answered = result["status"] == "answered"
    chunks = {c["chunk_id"]: c for c in result["retrieved_chunks"]}
    checks = {
        "status_matches": result["status"] == expect["status"],
        "sources_shown": not answered or bool(result["sources"]),
        "quotes_shown": not answered or bool(result["quotes"]),
        "exact_quotes": not answered or all(
            q["chunk_id"] in chunks and q["quote"] in chunks[q["chunk_id"]]["text"]
            for q in result["quotes"]
        ),
        "metadata_valid": not answered or all(
            s["chunk_id"] in chunks
            and all(s[k] == chunks[s["chunk_id"]][k] for k in ("source", "section"))
            for s in result["sources"]
        ),
        "state_saved": not result["state_errors"],
        "unknown_without_evidence": answered or (not result["sources"] and not result["quotes"]),
    }
    if answered and expect["status"] == "answered":
        answer = " ".join(result["answer"].split()).casefold()
        checks["required_terms"] = all(
            term.casefold() in answer for term in expect.get("required_terms", [])
        )
        if expect.get('required_any_terms'):
            checks['required_mechanism'] = any(term.casefold() in answer for term in expect['required_any_terms'])
    return checks


def audit_scenario(scenario: dict, rows: list[dict], final_state: dict) -> dict:
    goal_text = " ".join(final_state["goal"].split()).casefold()
    goal_retained = all(term.casefold() in goal_text for term in scenario["goal_terms"])
    missing_constraints = []
    for row in rows:
        expected = row["expect"].get("constraint")
        if expected and not any(expected.casefold() in c.casefold() for c in final_state["constraints"]):
            missing_constraints.append({"turn": row["turn"], "constraint": expected})
    missing_terms = []
    for row in rows:
        expected = row["expect"].get("term")
        if expected and not any(expected.casefold() in t.casefold() for t in final_state["terms"]):
            missing_terms.append({"turn": row["turn"], "term": expected})
    hard_keys = ("status_matches", "sources_shown", "quotes_shown", "exact_quotes",
                 "metadata_valid", "state_saved", "unknown_without_evidence")
    per_turn = {key: sum(row["checks"][key] for row in rows) for key in hard_keys}
    first_goal = rows[0]['result']['task_state']['goal']
    stable_goal = all(row['result']['task_state']['goal'] == first_goal for row in rows)
    memory_applied = all(row['result'].get('memory_used', {}).get('goal') == first_goal for row in rows[1:])
    constraints_applied = all(
        set(rows[i-1]['result']['task_state']['constraints']).issubset(
            set(rows[i]['result'].get('memory_used', {}).get('constraints', [])))
        for i in range(1, len(rows)))
    return {
        "turns": len(rows),
        "answered_turns": sum(row['result']['status'] == 'answered' for row in rows),
        "answers_with_sources": sum(row['result']['status'] == 'answered' and bool(row['result']['sources']) for row in rows),
        "refused_turns": sum(row['result']['status'] == 'unknown' for row in rows),
        "goal_retained": goal_retained,
        "goal_stable_every_turn": stable_goal,
        "memory_applied_every_turn": memory_applied,
        "constraints_applied_every_turn": constraints_applied,
        "constraints_retained": not missing_constraints,
        "terms_retained": not missing_terms,
        "missing_constraints": missing_constraints,
        "missing_terms": missing_terms,
        "per_turn_checks": per_turn,
        "required_terms_hits": sum(
            1 for row in rows
            if row["expect"].get("required_terms") and row["checks"].get("required_terms") is True
        ),
        "required_terms_total": sum(
            1 for row in rows
            if row["expect"].get("required_terms") and row["result"]["status"] == "answered"
        ),
        "final_state": {key: final_state[key] for key in ("goal", "clarified", "constraints", "terms", "version")},
    }


def evaluate(agent: ChatAgent, scenarios: list[dict]) -> dict:
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "model": agent.model, "scenarios": []}
    for scenario in scenarios:
        print(f"=== {scenario['id']}", flush=True)
        session_id = agent.create_session()
        rows = []
        for index, step in enumerate(scenario["messages"], 1):
            print(f"  turn {index}: {step['text'][:60]}", flush=True)
            result = agent.turn(session_id, step["text"])
            rows.append({
                "turn": index,
                "message": step["text"],
                "expect": step["expect"],
                "result": result,
                "checks": audit_turn(result, step["expect"]),
            })
        final_state = agent.states.get(session_id).to_dict()
        report["scenarios"].append({
            "id": scenario["id"],
            "title": scenario["title"],
            "session_id": session_id,
            "turns": rows,
            "summary": audit_scenario(scenario, rows, final_state),
        })
    report["summary"] = {}
    for scenario in report["scenarios"]:
        passed = (
            all(all(row["checks"].values()) for row in scenario["turns"])
            and scenario["summary"]["goal_retained"]
            and scenario["summary"]["constraints_retained"]
            and scenario["summary"]["terms_retained"]
            and scenario['summary']['goal_stable_every_turn']
            and scenario['summary']['memory_applied_every_turn']
            and scenario['summary']['constraints_applied_every_turn']
        )
        report["summary"][scenario["id"]] = "passed" if passed else "failed"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument('--audit-report', type=Path, help='Recheck saved evidence without model calls')
    args = parser.parse_args()
    if args.audit_report:
        report = json.loads(args.audit_report.read_text(encoding='utf-8'))
        scenarios = {s['id']: s for s in load_scenarios()}
        for saved in report['scenarios']:
            scenario = scenarios[saved['id']]
            if len(saved['turns']) != len(scenario['messages']):
                raise ValueError('Сохранённый отчёт не соответствует сценарию')
            for row, step in zip(saved['turns'], scenario['messages']):
                if row['message'] != step['text']:
                    raise ValueError('Сообщения изменились: нужен новый реальный прогон')
                row['expect'] = step['expect']
                row['checks'] = audit_turn(row['result'], step['expect'])
            summary = audit_scenario(scenario, saved['turns'], saved['turns'][-1]['result']['task_state'])
            saved['summary'] = summary
            good = all(all(r['checks'].values()) for r in saved['turns']) and all(summary[k] for k in (
                'goal_retained', 'constraints_retained', 'terms_retained', 'goal_stable_every_turn',
                'memory_applied_every_turn', 'constraints_applied_every_turn'))
            report['summary'][saved['id']] = 'passed' if good else 'failed'
        report['audit_updated_at'] = datetime.now(timezone.utc).isoformat()
        args.audit_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report['summary'], ensure_ascii=False))
        return 0 if all(v == 'passed' for v in report['summary'].values()) else 1
    report = evaluate(ChatAgent(model=args.model, data_dir=args.data_dir), load_scenarios())
    DEFAULT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": report["summary"],
                      "scenarios": {s["id"]: s["summary"]["turns"] for s in report["scenarios"]}},
                     ensure_ascii=False, indent=2))
    return 0 if all(value == 'passed' for value in report['summary'].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
