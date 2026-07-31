import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# Master list of candidate Chennai IT/Software/SaaS/Product companies
companies_raw = [
    # SaaS / Product / Cloud Software
    {"name": "Zoho Corporation", "type": "Software Product / SaaS", "location": "Estancia & Ramapuram", "website": "https://www.zoho.com/", "careers": "https://www.zoho.com/careers/"},
    {"name": "Freshworks", "type": "SaaS Product", "location": "Perungudi, OMR", "website": "https://www.freshworks.com/", "careers": "https://www.freshworks.com/careers/"},
    {"name": "Chargebee", "type": "SaaS / FinTech", "location": "Guindy", "website": "https://www.chargebee.com/", "careers": "https://www.chargebee.com/careers/"},
    {"name": "Kissflow", "type": "SaaS / No-Code Platform", "location": "Perungudi, OMR", "website": "https://kissflow.com/", "careers": "https://careers.kissflow.com/"},
    {"name": "SuperOps", "type": "SaaS / IT Management", "location": "OMR, Perungudi", "website": "https://superops.com/", "careers": "https://superops.com/careers"},
    {"name": "Rocketlane", "type": "SaaS Product", "location": "Perungudi, OMR", "website": "https://www.rocketlane.com/", "careers": "https://www.rocketlane.com/careers"},
    {"name": "Everstage", "type": "SaaS Product", "location": "OMR, Perungudi", "website": "https://www.everstage.com/", "careers": "https://www.everstage.com/careers"},
    {"name": "Facilio", "type": "PropTech / SaaS", "location": "Taramani, OMR", "website": "https://facilio.com/", "careers": "https://facilio.com/careers/"},
    {"name": "SurveySparrow", "type": "SaaS Product", "location": "Guindy", "website": "https://surveysparrow.com/", "careers": "https://surveysparrow.com/careers/"},
    {"name": "CustomerLabs", "type": "SaaS / Customer Data Platform", "location": "Thoraipakkam, OMR", "website": "https://www.customerlabs.com/", "careers": "https://www.customerlabs.com/careers/"},
    {"name": "Animaker", "type": "SaaS / Media Tech", "location": "Guindy", "website": "https://www.animaker.com/", "careers": "https://www.animaker.com/careers"},
    {"name": "HappyFox", "type": "SaaS / Helpdesk", "location": "Karapakkam, OMR", "website": "https://www.happyfox.com/", "careers": "https://www.happyfox.com/careers/"},
    {"name": "FourKites", "type": "Supply Chain SaaS", "location": "Perungudi, OMR", "website": "https://www.fourkites.com/", "careers": "https://www.fourkites.com/careers/"},
    {"name": "Zuper", "type": "SaaS / Field Service", "location": "Guindy", "website": "https://zuper.co/", "careers": "https://zuper.co/careers/"},
    {"name": "PipeCandy", "type": "E-Commerce Data SaaS", "location": "OMR, Perungudi", "website": "https://pipecandy.com/", "careers": "https://pipecandy.com/careers/"},
    {"name": "Testsigma", "type": "Test Automation SaaS", "location": "OMR, Perungudi", "website": "https://testsigma.com/", "careers": "https://testsigma.com/careers"},
    {"name": "CoreStack", "type": "Cloud Governance SaaS", "location": "Taramani, OMR", "website": "https://www.corestack.io/", "careers": "https://www.corestack.io/careers/"},
    {"name": "Amagi", "type": "Media Tech SaaS", "location": "OMR, Chennai", "website": "https://www.amagi.com/", "careers": "https://www.amagi.com/careers/"},
    {"name": "Ozonetel", "type": "Cloud Communications SaaS", "location": "OMR, Perungudi", "website": "https://ozonetel.com/", "careers": "https://ozonetel.com/careers/"},
    {"name": "Ideas2IT", "type": "Product Engineering / Custom Software", "location": "Guindy", "website": "https://www.ideas2it.com/", "careers": "https://www.ideas2it.com/careers/"},
    {"name": "Codilar Technologies", "type": "E-commerce & Web Dev", "location": "Perungudi, OMR", "website": "https://www.codilar.com/", "careers": "https://www.codilar.com/careers/"},
    {"name": "Sedin Technologies", "type": "Custom Software & Web Dev", "location": "Perungudi, OMR", "website": "https://sedintechnologies.com/", "careers": "https://sedintechnologies.com/careers/"},
    {"name": "Draup", "type": "AI & Sales Intelligence SaaS", "location": "Perungudi, OMR", "website": "https://draup.com/", "careers": "https://draup.com/careers/"},
    {"name": "Payoda Technology", "type": "Software Product Engineering", "location": "Guindy", "website": "https://www.payoda.com/", "careers": "https://www.payoda.com/careers/"},
    {"name": "Karomi Technology", "type": "SaaS / Packaging Management", "location": "Guindy", "website": "https://www.karomi.com/", "careers": "https://www.karomi.com/careers/"},
    {"name": "Bahwan CyberTek", "type": "Enterprise Software / IT Services", "location": "Navalur, OMR", "website": "https://www.bahwancybertek.com/", "careers": "https://www.bahwancybertek.com/careers/"},
    {"name": "CallHub", "type": "Cloud Software / SaaS", "location": "OMR, Perungudi", "website": "https://callhub.io/", "careers": "https://callhub.io/careers/"},
    {"name": "TVS Next", "type": "Digital Engineering / Web Dev", "location": "Guindy", "website": "https://tvsnext.com/", "careers": "https://tvsnext.com/careers/"},
    {"name": "ValGenesis", "type": "Pharma Validation SaaS", "location": "Guindy", "website": "https://www.valgenesis.com/", "careers": "https://www.valgenesis.com/company/careers"},
    {"name": "SaasAnt", "type": "FinTech / Accounting SaaS", "location": "OMR, Perungudi", "website": "https://www.saasant.com/", "careers": "https://www.saasant.com/careers/"},
    {"name": "ZapScale", "type": "Customer Success SaaS", "location": "Perungudi, OMR", "website": "https://www.zapscale.com/", "careers": "https://www.zapscale.com/careers"},

    # FinTech / HRTech
    {"name": "M2P Fintech", "type": "FinTech / API Infrastructure", "location": "Guindy", "website": "https://m2pfintech.com/", "careers": "https://m2pfintech.com/careers/"},
    {"name": "Mylapay", "type": "FinTech / Payment Gateway", "location": "Perungudi, OMR", "website": "https://mylapay.com/", "careers": "https://mylapay.com/careers/"},
    {"name": "Minkasu", "type": "FinTech / Authentication", "location": "OMR, Perungudi", "website": "https://www.minkasupay.com/", "careers": "https://www.minkasupay.com/careers"},
    {"name": "IppoPay", "type": "FinTech / Payments", "location": "Guindy", "website": "https://www.ippopay.com/", "careers": "https://www.ippopay.com/careers"},
    {"name": "Kaleidofin", "type": "FinTech Product", "location": "Guindy", "website": "https://www.kaleidofin.com/", "careers": "https://www.kaleidofin.com/careers"},
    {"name": "Yubi (CredAvenue)", "type": "FinTech Platform", "location": "Taramani, OMR", "website": "https://www.go-yubi.com/", "careers": "https://www.go-yubi.com/careers/"},
    {"name": "FSS (Financial Software & Systems)", "type": "FinTech & Payment Tech", "location": "Siruseri, SIPCOT IT Park", "website": "https://www.fsstech.com/", "careers": "https://www.fsstech.com/careers"},
    {"name": "Wibmo", "type": "FinTech / PayTech", "location": "Guindy", "website": "https://wibmo.co/", "careers": "https://wibmo.co/careers"},
    {"name": "FundsIndia", "type": "WealthTech / FinTech", "location": "Guindy", "website": "https://www.fundsindia.com/", "careers": "https://www.fundsindia.com/careers"},
    {"name": "Maveric Systems", "type": "FinTech Services", "location": "Guindy / Siruseri", "website": "https://maveric-systems.com/", "careers": "https://maveric-systems.com/careers/"},
    {"name": "Vayana Network", "type": "FinTech / Supply Chain Finance", "location": "Guindy", "website": "https://www.vayana.com/", "careers": "https://www.vayana.com/careers/"},
    {"name": "AssetPlus", "type": "FinTech / Mutual Funds Platform", "location": "Guindy", "website": "https://www.assetplus.in/", "careers": "https://www.assetplus.in/careers"},
    {"name": "Northern Arc Capital", "type": "FinTech / Financial Services", "location": "Guindy", "website": "https://www.northernarc.com/", "careers": "https://www.northernarc.com/careers"},
    {"name": "YNOS Venture Engine", "type": "FinTech / Startup Intelligence", "location": "Taramani (IITM Research Park)", "website": "https://www.ynos.in/", "careers": "https://www.ynos.in/careers"},
    {"name": "OroCorp", "type": "FinTech Product", "location": "Guindy", "website": "https://www.orocorp.in/", "careers": "https://www.orocorp.in/careers"},
    {"name": "Digitap", "type": "FinTech / AI Risk Management", "location": "OMR, Perungudi", "website": "https://www.digitap.ai/", "careers": "https://www.digitap.ai/careers"},
    {"name": "Xobin", "type": "HRTech / Assessment SaaS", "location": "Perungudi, OMR", "website": "https://xobin.com/", "careers": "https://xobin.com/careers/"},
    {"name": "Talview", "type": "HRTech SaaS", "location": "OMR, Perungudi", "website": "https://www.talview.com/", "careers": "https://www.talview.com/careers"},

    # AI / DeepTech / HealthTech / Cybersecurity
    {"name": "K7 Computing", "type": "Cybersecurity Software", "location": "Ambattur / Chetpet", "website": "https://www.k7computing.com/", "careers": "https://www.k7computing.com/in/careers"},
    {"name": "COSGrid Networks", "type": "Cybersecurity / SD-WAN", "location": "Perungudi, OMR", "website": "https://www.cosgrid.com/", "careers": "https://www.cosgrid.com/company/careers/"},
    {"name": "CareStack", "type": "HealthTech SaaS", "location": "Perungudi, OMR", "website": "https://carestack.com/", "careers": "https://carestack.com/careers/"},
    {"name": "Mitsogo (Hexnode)", "type": "Cybersecurity / UEM SaaS", "location": "Karapakkam, OMR", "website": "https://www.mitsogo.com/", "careers": "https://www.mitsogo.com/careers/"},
    {"name": "Gnani.ai", "type": "Conversational AI / Voice SaaS", "location": "OMR, Perungudi", "website": "https://www.gnani.ai/", "careers": "https://www.gnani.ai/careers/"},
    {"name": "Detect Technologies", "type": "AI / Industrial IoT", "location": "Taramani (IITM Research Park)", "website": "https://detecttechnologies.com/", "careers": "https://detecttechnologies.com/careers/"},
    {"name": "SISA InfoSec", "type": "Cybersecurity Services & Software", "location": "OMR, Perungudi", "website": "https://www.sisainfosec.com/", "careers": "https://www.sisainfosec.com/careers/"},
    {"name": "Prophaze", "type": "Cybersecurity SaaS", "location": "Perungudi, OMR", "website": "https://www.prophaze.com/", "careers": "https://www.prophaze.com/careers"},
    {"name": "MocDoc", "type": "HealthTech SaaS", "location": "Velachery / Perungudi", "website": "https://mocdoc.com/", "careers": "https://mocdoc.com/careers"},
    {"name": "Agilisium", "type": "Data Analytics & Cloud", "location": "Sholinganallur, OMR", "website": "https://www.agilisium.com/", "careers": "https://www.agilisium.com/careers"},
    {"name": "Botminds.ai", "type": "AI / Intelligent Process Automation", "location": "Taramani (IITM Research Park)", "website": "https://www.botminds.ai/", "careers": "https://www.botminds.ai/careers"},
    {"name": "Health Sensei", "type": "HealthTech / IoT", "location": "Guindy", "website": "https://healthsensei.co.in/", "careers": "https://healthsensei.co.in/careers"},
    {"name": "Disprz", "type": "EdTech / AI Skilling SaaS", "location": "Guindy", "website": "https://disprz.ai/", "careers": "https://disprz.ai/careers/"},
    {"name": "Attune Technologies", "type": "HealthTech SaaS", "location": "Perungudi, OMR", "website": "https://attunelive.com/", "careers": "https://attunelive.com/careers"},
    {"name": "Agnikul Cosmos", "type": "DeepTech / SpaceTech Software", "location": "Taramani (IITM Research Park)", "website": "https://agnikul.in/", "careers": "https://agnikul.in/#/careers"},
    {"name": "The ePlane Company", "type": "DeepTech Software & Aerospace", "location": "Taramani (IITM Research Park)", "website": "https://eplane.ai/", "careers": "https://eplane.ai/careers"},
    {"name": "Planys Technologies", "type": "Robotics & AI Software", "location": "Taramani (IITM Research Park)", "website": "https://www.planystech.com/", "careers": "https://www.planystech.com/careers/"},
    {"name": "Pando", "type": "Supply Chain SaaS", "location": "Perungudi, OMR", "website": "https://pando.ai/", "careers": "https://pando.ai/careers/"},
    {"name": "GuardianLink", "type": "Web3 / Tech SaaS", "location": "Guindy", "website": "https://www.guardianlink.io/", "careers": "https://www.guardianlink.io/careers"},
    {"name": "Mad Street Den (Vue.ai)", "type": "Retail AI / Computer Vision SaaS", "location": "Guindy / OMR", "website": "https://www.madstreetden.com/", "careers": "https://www.madstreetden.com/careers/"},
    {"name": "Uniphore", "type": "Conversational AI SaaS", "location": "Guindy / OMR", "website": "https://www.uniphore.com/", "careers": "https://www.uniphore.com/careers/"},

    # Web Development, Custom Software & Regional Tech Companies
    {"name": "CONTUS Tech", "type": "Web & Mobile Product Dev", "location": "Porur", "website": "https://www.contus.com/", "careers": "https://www.contus.com/careers.php"},
    {"name": "KnackForge", "type": "Web Dev & Custom Software", "location": "Ambattur", "website": "https://knackforge.com/", "careers": "https://knackforge.com/careers"},
    {"name": "SyberGate Technologies", "type": "Web Dev & ERP Consulting", "location": "Ambattur", "website": "https://sybergate.co.in/", "careers": "https://sybergate.co.in/careers"},
    {"name": "Jasmin InfoTech", "type": "Embedded & IoT Software", "location": "Pallikaranai", "website": "https://www.jasmin-infotech.com/", "careers": "https://www.jasmin-infotech.com/careers.html"},
    {"name": "Kryptos Technologies", "type": "Cloud Services & Software", "location": "Pallikaranai / Guindy", "website": "https://www.kryptostechnologies.com/", "careers": "https://www.kryptostechnologies.com/careers/"},
    {"name": "DataWENS Technologies", "type": "Enterprise Apps & Cloud", "location": "Ekkatuthangal", "website": "https://datawens.com/", "careers": "https://datawens.com/careers"},
    {"name": "Sathuram Software", "type": "AI & Web Development", "location": "Perungudi, OMR", "website": "https://sathuramsoft.com/", "careers": "https://sathuramsoft.com/careers"},
    {"name": "CaddyCode", "type": "SaaS & Custom Software Dev", "location": "Perungudi, OMR", "website": "https://caddycode.com/", "careers": "https://caddycode.com/careers"},
    {"name": "Gilead Digital", "type": "Web Dev & Custom Software", "location": "Thoraipakkam, OMR", "website": "https://gileaddigital.in/", "careers": "https://gileaddigital.in/careers"},
    {"name": "Adyog Software", "type": "Enterprise Web Dev & UX", "location": "Velachery", "website": "https://adyog.com/", "careers": "https://adyog.com/careers"},
    {"name": "Mindset Software Technologies", "type": "Custom Software Dev", "location": "Porur", "website": "https://mindsetechnologies.com/", "careers": "https://mindsetechnologies.com/careers"},
    {"name": "Provility Software", "type": "Cloud & Custom Software", "location": "Perungudi, OMR", "website": "https://provility.com/", "careers": "https://provility.com/careers"},
    {"name": "Scope Thinkers", "type": "Web Development & IT", "location": "Perungudi, OMR", "website": "https://scopethinkers.com/", "careers": "https://scopethinkers.com/careers"},
    {"name": "Revolite Infotech", "type": "Web Dev & AI Solutions", "location": "Ambattur", "website": "https://revolite.io/", "careers": "https://revolite.io/careers"},
    {"name": "Besoins Technologies", "type": "Web Development & Startup MVPs", "location": "Porur", "website": "https://besoins.in/", "careers": "https://besoins.in/careers"},
    {"name": "eHash Software", "type": "Web & Custom Software", "location": "Pallikaranai", "website": "https://ehashsoft.com/", "careers": "https://ehashsoft.com/careers"},
    {"name": "Lumel Technologies", "type": "Analytics & BI Software SaaS", "location": "Perungudi, OMR", "website": "https://lumel.com/", "careers": "https://lumel.com/careers/"},
    {"name": "iTech India", "type": "Custom Software & Web Dev", "location": "Ambattur", "website": "https://itechindia.co/", "careers": "https://itechindia.co/careers/"},
    {"name": "BICS Global", "type": "Software Services & Web Dev", "location": "Ambattur", "website": "https://bicsglobal.com/", "careers": "https://bicsglobal.com/careers"},
    {"name": "Dextra Technologies", "type": "Web Development Services", "location": "Velachery", "website": "https://dextratechnologies.com/", "careers": "https://dextratechnologies.com/careers"},
    {"name": "SoftTeam Solutions", "type": "Software Services & Apps", "location": "Pallikaranai", "website": "https://softteam.com/", "careers": "https://softteam.com/careers"},
    {"name": "iCore Software Systems", "type": "Cloud & Web Software", "location": "Navalur, OMR", "website": "https://icoresoftwaresystems.com/", "careers": "https://icoresoftwaresystems.com/careers"},
    {"name": "Ninos IT Solution", "type": "Web & Software Development", "location": "Navalur / Guindy", "website": "https://ninositsolution.com/", "careers": "https://ninositsolution.com/careers"},
    {"name": "Lucid Software", "type": "Non-Destructive Testing Software", "location": "Ekkatuthangal", "website": "https://lucidsoft.com/", "careers": "https://lucidsoft.com/careers"},
    {"name": "Fieldproxy", "type": "Field Operations SaaS", "location": "Perungudi, OMR", "website": "https://fieldproxy.com/", "careers": "https://fieldproxy.com/careers"},
    {"name": "Resulticks", "type": "Marketing Automation SaaS", "location": "Guindy", "website": "https://www.resulticks.com/", "careers": "https://www.resulticks.com/careers.html"},
    {"name": "Cryotos", "type": "Maintenance & CMMS SaaS", "location": "OMR, Perungudi", "website": "https://www.cryotos.com/", "careers": "https://www.cryotos.com/careers"},
    {"name": "CultureMonkey", "type": "HRTech & Engagement SaaS", "location": "Perungudi, OMR", "website": "https://www.culturemonkey.io/", "careers": "https://www.culturemonkey.io/careers"},
    {"name": "GUVI (HCL GUVI)", "type": "EdTech Tech Platform", "location": "Taramani (IITM Research Park)", "website": "https://www.guvi.in/", "careers": "https://www.guvi.in/current-openings"},
    {"name": "Skill-Lync", "type": "EdTech Software Platform", "location": "Guindy / OMR", "website": "https://skill-lync.com/", "careers": "https://skill-lync.com/careers"},
    {"name": "Camu (Octoze Technologies)", "type": "EdTech ERP SaaS", "location": "Perungudi, OMR", "website": "https://camudigitalcampus.com/", "careers": "https://camudigitalcampus.com/careers/"},
    {"name": "Net Access India", "type": "IT Infrastructure & Cloud", "location": "Guindy", "website": "https://www.netaccess-india.com/", "careers": "https://www.netaccess-india.com/careers.html"},
    {"name": "Kumaran Systems", "type": "Custom Software & IT Services", "location": "Velachery", "website": "https://www.kumaran.com/", "careers": "https://www.kumaran.com/careers"}
]

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def verify_single(comp):
    name = comp['name']
    web_url = comp['website']
    car_url = comp['careers']
    
    web_status = False
    final_web_url = web_url
    try:
        r = requests.get(web_url, headers=headers, timeout=5, allow_redirects=True)
        if r.status_code < 400:
            web_status = True
            final_web_url = r.url
    except Exception:
        pass

    potential_paths = [
        car_url,
        web_url.rstrip('/') + '/careers',
        web_url.rstrip('/') + '/careers/',
        web_url.rstrip('/') + '/jobs',
        web_url.rstrip('/') + '/company/careers',
        web_url.rstrip('/') + '/join-us',
        web_url.rstrip('/') + '/work-with-us'
    ]

    seen = []
    for p in potential_paths:
        if p not in seen:
            seen.append(p)

    valid_car_url = None
    car_text = ""

    for p in seen:
        try:
            r = requests.get(p, headers=headers, timeout=5, allow_redirects=True)
            if r.status_code < 400:
                valid_car_url = r.url
                car_text = r.text.lower()
                break
        except Exception:
            continue

    car_status = "Not Found"
    final_car_url = "Not Found"

    if valid_car_url:
        final_car_url = valid_car_url
        no_jobs_kw = ["no open positions", "no current openings", "no jobs found", "no open roles", "currently no open", "0 open positions", "no position available"]
        has_jobs_kw = ["apply", "openings", "open positions", "job details", "role", "view job", "current openings", "apply now", "hiring", "developer", "engineer"]
        
        if any(ats in valid_car_url for ats in ['lever.co', 'greenhouse.io', 'keka.com', 'freshteam.com', 'workable.com', 'zoho.com/recruiter', 'darwinbox.in']):
            car_status = "Active"
        elif any(k in car_text for k in no_jobs_kw):
            car_status = "Available but no current openings"
        elif any(k in car_text for k in has_jobs_kw):
            car_status = "Active"
        else:
            car_status = "Available but no current openings"
    else:
        if web_status:
            final_car_url = "Not Found"
            car_status = "Not Found"
        else:
            final_car_url = car_url
            car_status = "Unable to Verify"

    return {
        "name": name,
        "type": comp['type'],
        "location": comp['location'],
        "website_final": final_web_url,
        "careers_final": final_car_url,
        "status": car_status
    }

print(f"Starting parallel verification of {len(companies_raw)} companies...")
results = []

with ThreadPoolExecutor(max_workers=25) as executor:
    future_to_comp = {executor.submit(verify_single, c): c for c in companies_raw}
    for future in as_completed(future_to_comp):
        try:
            data = future.result()
            results.append(data)
            print(f"Verified: {data['name']} -> {data['status']}")
        except Exception as exc:
            comp = future_to_comp[future]
            print(f"Exception for {comp['name']}: {exc}")

with open("verified_companies.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print("\nSaved verified_companies.json successfully!")
