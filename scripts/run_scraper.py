import json
import sys
from pathlib import Path
from datetime import datetime
from job_agent.sources.watchlist import scan_watchlist

config_path = Path('config/companies.yaml')
output_file = Path('watchlist_jobs.json')

print(f"[{datetime.now().isoformat()}] Starting watchlist scraper...")
sys.stdout.flush()

try:
    jobs = scan_watchlist(config_path, extract_jobs=True, company_limit=0)
    
    # Convert jobs to dicts for JSON serialization
    jobs_data = [job.to_dict() for job in jobs]
    
    # Save to file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(jobs_data, f, indent=2, default=str)
    
    print(f"[{datetime.now().isoformat()}] Completed! Found {len(jobs)} jobs")
    print(f"Results saved to: {output_file}")
    
except Exception as e:
    print(f"[{datetime.now().isoformat()}] Error: {e}")
    import traceback
    traceback.print_exc()
