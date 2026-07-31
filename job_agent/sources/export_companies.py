"""Export config/companies.yaml into a single consolidated JSON file.

Resolves each company's real careers page URL (using careers_url_override
when set, otherwise falling back to the homepage) and includes any known
ATS platform/token, so the JSON is a self-contained directory of every
watched company plus where its job listings live.
"""
from pathlib import Path
import json

import yaml


def export_companies(config_path: Path, output_path: Path) -> list[dict]:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    companies = cfg.get("companies", [])

    directory = []
    for entry in companies:
        directory.append({
            "name": entry["name"],
            "homepage": entry["homepage"],
            "careers_url": entry.get("careers_url_override") or entry["homepage"],
            "ats": entry.get("ats", ""),
            "board_token": entry.get("board_token", ""),
            "js_rendered": entry.get("js_rendered", False),
        })

    output_path.write_text(json.dumps(directory, indent=2, ensure_ascii=False), encoding="utf-8")
    return directory


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    result = export_companies(root / "config" / "companies.yaml", root / "data" / "companies.json")
    print(f"Exported {len(result)} companies to data/companies.json")
