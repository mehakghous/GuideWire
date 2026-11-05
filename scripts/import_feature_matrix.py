"""Convert GuideWire_Rigging_Animation_Feature_Matrix.xlsx into knowledge/rigging_features.json (one record per feature).

    python scripts/import_feature_matrix.py "C:/path/GuideWire_Rigging_Animation_Feature_Matrix.xlsx"

Reads the workbook's XML directly (no spreadsheet library). The JSON is the committed source of truth for ingestion; re-run this when the matrix changes.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
OUT = Path(__file__).resolve().parents[1] / "knowledge" / "rigging_features.json"
COLUMNS = ["id", "category", "name", "outcome", "blender", "maya", "houdini", "workflow", "depends_on", "complexity", "priority",
           "acceptance", "references", "group", "phase", "mvp"]


def read_rows(xlsx: Path) -> list[list[str]]:
    with zipfile.ZipFile(xlsx) as z:
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows = []
    for r in root.iter(M + "row"):
        cells = {}
        for c in r.findall(M + "c"):
            col = re.match(r"[A-Z]+", c.get("r")).group()
            v = "".join(t.text or "" for t in c.iter(M + "t"))
            if not v and c.find(M + "v") is not None:
                v = c.find(M + "v").text or ""
            cells[col] = v.strip()
        rows.append([cells.get(chr(65 + i), "") for i in range(len(COLUMNS))])
    return rows


def build(xlsx: Path) -> dict:
    header, *rows = read_rows(xlsx)
    if [h.lower() for h in header[:3]] != ["feature id", "category", "feature name"]:
        raise SystemExit(f"unexpected header row: {header[:3]}")
    feats = []
    for r in rows:
        d = dict(zip(COLUMNS, r))
        d["depends_on"] = [x.strip() for x in re.split(r"[,;]", d["depends_on"]) if re.fullmatch(r"[A-Z]{4}-\d{2}", x.strip())]
        d["mvp"] = d["mvp"].lower() == "yes"
        feats.append(d)
    return {"source": xlsx.name, "sha256": hashlib.sha256(xlsx.read_bytes()).hexdigest(), "features": feats}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    data = build(Path(sys.argv[1]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(data['features'])} features to {OUT}")
