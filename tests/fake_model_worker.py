"""Fault-injection process for lifecycle tests; no model or network."""
import json
import os
import sys
import time
time.sleep(float(os.environ.get("JIS_TEST_LOAD_SLEEP", "0")))
print(json.dumps({"kind": "ready", "device": sys.argv[2]}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    time.sleep(float(os.environ.get("JIS_TEST_INFER_SLEEP", "0")))
    print(json.dumps({"id": request["id"], "answer": {"choice": "c0", "answer_confidence": .95,
                       "probabilities": {"c0": .95, "c1": .03, "keep": .02}}}), flush=True)
