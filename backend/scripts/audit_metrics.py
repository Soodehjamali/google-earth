import sys
from pathlib import Path

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services.agriculture import register_all_metrics
from app.services.agriculture.catalog import all_metrics
from app.services.agriculture.support import parse_native_resolution_m
from app.services.agriculture.quality_gating import COARSE_DATASET_IDS

def generate_audit():
    register_all_metrics()
    metrics = all_metrics()
    
    res = []
    for m in metrics:
        ds_id = m.primary_dataset_id if hasattr(m, "primary_dataset_id") else (m.dataset_ids[0] if m.dataset_ids else None)
        ds = m.primary_dataset() if hasattr(m, "primary_dataset") and ds_id else None
        spatial_res = ds.spatial_resolution if ds else ("N/A" if ds_id is None else None)
        res_m = parse_native_resolution_m(spatial_res) if spatial_res else None
        is_unavail = m.key.startswith("unavailable_") or m.__class__.__name__.startswith("Unavailable")
        if is_unavail:
            state = "unavailable"
        elif ds_id in COARSE_DATASET_IDS or (res_m is not None and res_m > 30.0):
            state = "coarse_context"
        else:
            state = "valid"
        
        domain_name = m.domain.value if hasattr(m.domain, "value") else str(m.domain)
        res.append({
            "key": m.key,
            "display_name": m.display_name,
            "domain": domain_name,
            "dataset_id": ds_id,
            "spatial_res": spatial_res,
            "res_m": res_m,
            "state": state,
        })

    counts = {}
    for r in res:
        counts[r["state"]] = counts.get(r["state"], 0) + 1

    print("Counts by quality_state category:", counts)
    print(f"Total metrics audited: {len(res)}")

    docs_file = backend_dir.parent / "docs" / "metric-resolution-audit.md"
    docs_file.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Metric Resolution & Quality-State Audit (Phase 2)\n\n",
        "This document audits all 118 registered metrics in the Agricultural Intelligence Platform, "
        "classifying their native resolution and three-state quality category:\n"
        "- `valid`: Field-scale resolution (<= 30 m) capable of resolving orchard/parcel variation.\n"
        "- `coarse_context`: Regional context (> 30 m up to 11 km) reflecting regional climate or hydrology.\n"
        "- `unavailable`: Explicitly unavailable/unsupported metric placeholder returning structured reasons.\n\n",
        f"**Audit Summary**:\n",
        f"- Total Registered Metrics: {len(res)}\n",
        f"- Field-Scale Valid (`valid`): {counts.get('valid', 0)}\n",
        f"- Regional Coarse Context (`coarse_context`): {counts.get('coarse_context', 0)}\n",
        f"- Explicitly Unavailable (`unavailable`): {counts.get('unavailable', 0)}\n\n",
        "| # | Metric Key | Display Name | Domain | Primary Dataset | Native Resolution | Resolution (m) | Quality State |\n",
        "|---|---|---|---|---|---|---|---|\n",
    ]

    sorted_metrics = sorted(res, key=lambda x: (x["state"], x["domain"], x["key"]))
    for i, r in enumerate(sorted_metrics, 1):
        ds_text = f"`{r['dataset_id']}`" if r['dataset_id'] else "—"
        res_text = r['spatial_res'] or "—"
        m_text = f"{r['res_m']:.0f} m" if r['res_m'] is not None else "—"
        lines.append(
            f"| {i} | `{r['key']}` | {r['display_name']} | {r['domain']} | {ds_text} | {res_text} | {m_text} | **`{r['state']}`** |\n"
        )

    with open(docs_file, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"Audit document successfully written to {docs_file}")

if __name__ == "__main__":
    generate_audit()
