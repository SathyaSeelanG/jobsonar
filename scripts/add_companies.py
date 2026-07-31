import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

new_candidates = [
    {"name": "HyperVerge", "type": "AI DeepTech Startup", "location": "Taramani (IITM Research Park)", "website": "https://hyperverge.co/", "careers": "https://hyperverge.co/careers/"},
    {"name": "Siam Computing", "type": "Custom Web & Product Dev", "location": "Adyar", "website": "https://siamcomputing.com/", "careers": "https://siamcomputing.com/careers/"},
    {"name": "OptiSol Business Solutions", "type": "AI & Full Stack Web Dev", "location": "Guindy / OMR", "website": "https://www.optisolbusiness.com/", "careers": "https://www.optisolbusiness.com/careers/"},
    {"name": "Aspire Systems", "type": "Software Product Engineering", "location": "Siruseri (SIPCOT IT Park)", "website": "https://www.aspiresys.com/", "careers": "https://www.aspiresys.com/careers"},
    {"name": "Intellect Design Arena", "type": "FinTech Software Product", "location": "Siruseri / Guindy", "website": "https://www.intellectdesign.com/", "careers": "https://www.intellectdesign.com/careers/"},
    {"name": "Indium Software", "type": "Digital Engineering & Full Stack", "location": "Guindy / OMR", "website": "https://www.indiumsoftware.com/", "careers": "https://www.indiumsoftware.com/careers/"},
    {"name": "Ionixx Technologies", "type": "Web3 & Custom Web Dev", "location": "Perungudi, OMR", "website": "https://ionixxtech.com/", "careers": "https://ionixxtech.com/careers/"},
    {"name": "Skcript", "type": "Automation & Web Software", "location": "Adyar", "website": "https://skcript.com/", "careers": "https://skcript.com/careers"},
    {"name": "Blazedream", "type": "Web & Mobile App Dev", "location": "Nungambakkam", "website": "https://www.blazedream.com/", "careers": "https://www.blazedream.com/careers/"},
    {"name": "Smarther Technologies", "type": "Web Development Agency", "location": "Guindy", "website": "https://smarther.co/", "careers": "https://smarther.co/careers/"},
    {"name": "Istudiotech", "type": "Web Development & Software", "location": "Ambattur", "website": "https://istudiotech.in/", "careers": "https://istudiotech.in/careers"},
    {"name": "Deforay Technologies", "type": "Web Dev & Cloud Software", "location": "Nungambakkam", "website": "https://deforay.com/", "careers": "https://deforay.com/careers"},
    {"name": "CodeTez", "type": "Web & Software Engineering", "location": "Adyar", "website": "https://codetez.com/", "careers": "https://codetez.com/careers"},
    {"name": "Paladin Software", "type": "Enterprise Custom Software", "location": "Anna Nagar", "website": "https://paladinsoftwares.com/", "careers": "https://paladinsoftwares.com/careers"},
    {"name": "Swathi Soft Solutions", "type": "Custom Software & Web", "location": "Alwarpet", "website": "https://swathisoft.com/", "careers": "https://swathisoft.com/careers"},
    {"name": "Greenvironment", "type": "AI & IoT Software", "location": "Taramani (IITM Research Park)", "website": "https://greenvironmentindia.com/", "careers": "https://greenvironmentindia.com/careers"},
    {"name": "Satori XR", "type": "AR/VR & 3D Web Software", "location": "Taramani (IITM Research Park)", "website": "https://satorixr.com/", "careers": "https://satorixr.com/careers"},
    {"name": "DMA Technologies", "type": "AI & Cloud Consulting", "location": "Taramani (IITM Research Park)", "website": "https://dmatechnologies.com/", "careers": "https://dmatechnologies.com/careers"},
    {"name": "Vuram (WNS Vuram)", "type": "Hyperautomation & SaaS", "location": "Perungudi, OMR", "website": "https://www.vuram.com/", "careers": "https://www.vuram.com/careers/"},
    {"name": "SquareShift Technologies", "type": "Cloud Native & Web Dev", "location": "Adyar / OMR", "website": "https://squareshift.co/", "careers": "https://squareshift.co/careers"},
    {"name": "Speridian Technologies", "type": "CRM & Web Engineering", "location": "Guindy", "website": "https://www.speridian.com/", "careers": "https://www.speridian.com/careers/"},
    {"name": "Kovaion Consulting", "type": "HRTech & Cloud Solutions", "location": "Ambattur", "website": "https://kovaion.com/", "careers": "https://kovaion.com/careers/"},
    {"name": "Creators Web India", "type": "Web Development Services", "location": "Chennai", "website": "https://creatorswebindia.com/", "careers": "https://creatorswebindia.com/careers"},
    {"name": "Infonovum Technologies", "type": "Analytics & Software Solutions", "location": "Alwarpet", "website": "https://infonovum.com/", "careers": "https://infonovum.com/careers"},
    {"name": "WebBitech", "type": "Web Development & Software", "location": "Perungudi, OMR", "website": "https://webbitech.com/", "careers": "https://webbitech.com/careers"},
    {"name": "Casperon Technologies", "type": "On-Demand Software & Web", "location": "Guindy", "website": "https://casperon.com/", "careers": "https://casperon.com/careers"},
    {"name": "Lendingkart", "type": "FinTech Engineering Center", "location": "OMR, Perungudi", "website": "https://www.lendingkart.com/", "careers": "https://www.lendingkart.com/careers/"},
    {"name": "Perfios Software", "type": "FinTech SaaS Platform", "location": "Guindy / OMR", "website": "https://www.perfios.com/", "careers": "https://www.perfios.com/careers/"},
    {"name": "Syndigo (Riversand)", "type": "Master Data SaaS Platform", "location": "Taramani, OMR", "website": "https://syndigo.com/", "careers": "https://syndigo.com/careers/"},
    {"name": "Zencode Technologies", "type": "Custom Web Apps & Cloud", "location": "Perungudi, OMR", "website": "https://zencode.io/", "careers": "https://zencode.io/careers"},
    {"name": "SmarTek21", "type": "AI & Enterprise Cloud Software", "location": "Navalur, OMR", "website": "https://smartek21.com/", "careers": "https://smartek21.com/careers"},
    {"name": "Prodapt Solutions", "type": "Connected Software & Engineering", "location": "Velachery / Guindy", "website": "https://www.prodapt.com/", "careers": "https://www.prodapt.com/careers/"},
    {"name": "InApp Information Tech", "type": "Custom Web Applications", "location": "Perungudi, OMR", "website": "https://inapp.com/", "careers": "https://inapp.com/careers/"},
    {"name": "Aura Software Solutions", "type": "Enterprise Web Apps", "location": "Velachery", "website": "https://aurasoftsolutions.com/", "careers": "https://aurasoftsolutions.com/careers"},
    {"name": "Bounteous / Accolite", "type": "Digital Engineering & Web Apps", "location": "Taramani / Guindy", "website": "https://www.bounteous.com/", "careers": "https://www.bounteous.com/careers/"}
]

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def check(c):
    web = c['website']
    car = c['careers']
    web_ok = False
    try:
        r = requests.get(web, headers=headers, timeout=2.5, allow_redirects=True)
        if r.status_code < 400:
            web_ok = True
            web = r.url
    except Exception:
        pass

    car_ok = False
    status = "Not Found"
    final_car = "Not Found"

    try:
        r = requests.get(car, headers=headers, timeout=2.5, allow_redirects=True)
        if r.status_code < 400:
            car_ok = True
            final_car = r.url
            txt = r.text.lower()
            if any(ats in final_car for ats in ['lever.co', 'greenhouse.io', 'keka.com', 'freshteam.com', 'workable.com', 'darwinbox.in', 'myworkdayjobs.com']):
                status = "Active"
            elif any(k in txt for k in ["no open positions", "no current openings", "0 open positions"]):
                status = "Available but no current openings"
            elif any(k in txt for k in ["apply", "openings", "jobs", "careers", "hiring", "developer", "engineer"]):
                status = "Active"
            else:
                status = "Available but no current openings"
    except Exception:
        pass

    if not car_ok:
        if web_ok:
            status = "Not Found"
            final_car = "Not Found"
        else:
            status = "Unable to Verify"
            final_car = car

    c['website'] = web
    c['careers'] = final_car
    c['status'] = status
    return c

verified_new = []
with ThreadPoolExecutor(max_workers=25) as ex:
    futs = [ex.submit(check, c) for c in new_candidates]
    for f in as_completed(futs):
        try:
            res = f.result()
            verified_new.append(res)
        except Exception:
            pass

print(f"Verified {len(verified_new)} new candidate companies.")
with open("new_verified_companies.json", "w", encoding="utf-8") as f:
    json.dump(verified_new, f, indent=2)
