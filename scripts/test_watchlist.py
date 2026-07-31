from job_agent.sources.watchlist import check_company
from pathlib import Path
import yaml

config_path = Path('config/companies.yaml')
cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
fresher_signals = [s.lower() for s in cfg.get("fresher_signals", [])]
negative_signals = [s.lower() for s in cfg.get("negative_signals", [])]

# Test with first company
companies = cfg.get("companies", [])
test_company = companies[0]

print(f"Testing company: {test_company['name']}")
print(f"Homepage: {test_company['homepage']}")

jobs = check_company(test_company, fresher_signals, negative_signals, extract_jobs=True)
print(f"Jobs found: {len(jobs)}")

if jobs:
    for job in jobs[:2]:
        print(f"\nJob: {job.title}")
        print(f"  URL: {job.url}")
        print(f"  Description length: {len(job.description)}")
        print(f"  Source: {job.source}")
else:
    print("No jobs found for this company")
