from job_agent.sources.watchlist import check_company
from pathlib import Path
import yaml

config_path = Path('config/companies.yaml')
cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
fresher_signals = [s.lower() for s in cfg.get("fresher_signals", [])]
negative_signals = [s.lower() for s in cfg.get("negative_signals", [])]

# Find a company with explicit ATS config
companies = cfg.get("companies", [])
test_company = None
for c in companies:
    if c.get("ats") and c.get("board_token"):
        test_company = c
        break

if test_company:
    print(f"Testing company: {test_company['name']}")
    print(f"ATS: {test_company['ats']}")
    print(f"Board token: {test_company['board_token']}")
    
    jobs = check_company(test_company, fresher_signals, negative_signals, extract_jobs=True)
    print(f"Jobs found: {len(jobs)}")
    
    if jobs:
        print(f"\nShowing first 3 jobs:")
        for i, job in enumerate(jobs[:3]):
            print(f"\n  [{i+1}] {job.title}")
            print(f"      Company: {job.company}")
            print(f"      URL: {job.url[:60]}...")
            print(f"      Description: {job.description[:100]}...")
            print(f"      Desc length: {len(job.description)} chars")
            print(f"      Source: {job.source}")
            print(f"      Experience level: {job.experience_level}")
else:
    print("No company with explicit ATS found")
