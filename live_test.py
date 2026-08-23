import asyncio
import json
import sys

sys.path.insert(0, "app")
import audit

r = asyncio.run(audit.run_paid_audit("https://brozapi.com", lang="fr"))
out = dict(r)
out["technical"] = {"score": r["technical"]["score"],
                    "checks": {k: v["status"] for k, v in r["technical"]["checks"].items()}}
out["citations"]["queries"] = [{k: q[k] for k in ("query", "cited", "error")}
                               for q in r["citations"]["queries"]]
print(json.dumps(out, ensure_ascii=False, indent=1))
json.dump(r, open("live_audit_result.json", "w"), ensure_ascii=False, indent=1)
