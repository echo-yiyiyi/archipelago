"""Prepare a frozen shared review round; never calls an LLM.

Run with --help. Shortfalls are recorded in the private round report.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from judge_review import JudgeStore
from judge_blind import BlindStore, review_goal, SAFETY_GOALS


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--round', required=True)
    p.add_argument('--exposure-goals', default=','.join(str(g) for g in range(1,33) if g != 11))
    p.add_argument('--safety-goals', default=','.join(map(str, SAFETY_GOALS)))
    p.add_argument('--seed', type=int, default=20260926)
    p.add_argument('--policy', choices=['goal-balanced','legacy'], default='goal-balanced')
    p.add_argument('--fill', action='store_true', help='Explicit fallback: fill missing strata from other available strata')
    p.add_argument('--all-goals', action='store_true', help='Cover all goal IDs found in judge records, within the 40/20 cap')
    args=p.parse_args()
    source=JudgeStore(); store=BlindStore(source)
    goals={'exposure':sorted(set(map(int,args.exposure_goals.split(',')))),
           'security':sorted(set(map(int,args.safety_goals.split(','))))}
    if args.all_goals:
        source.scan()
        goals={kind: sorted({review_goal(c,args.policy)[0] for c in source.cases.values()
                            if c['kind']==kind and review_goal(c,args.policy)})
               for kind in ('exposure','security')}
    report=store.create_round(args.round,goals,seed=args.seed,fill=args.fill,policy=args.policy)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
