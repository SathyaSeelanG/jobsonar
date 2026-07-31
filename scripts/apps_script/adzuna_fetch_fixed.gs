/**
 * Pulls a min/max years-of-experience requirement out of free-text job copy.
 * Returns { min, max } in years, or null if no experience info was found at all.
 * "Fresher" / "no experience" / "0 years" all resolve to { min: 0, max: 0 }.
 */
function extractExperienceYears(text) {
  if (!text) return null; // guard against undefined/null/empty input
  const t = String(text).toLowerCase();

  if (/\bfresher(s)?\b|\bno experience\b|\bentry[- ]level\b|\b0\s*years?\b/.test(t)) {
    return { min: 0, max: 0 };
  }

  // "2-4 years", "2 to 4 yrs", "2–4 year(s)"
  let m = t.match(/(\d+)\s*(?:-|–|to)\s*(\d+)\s*\+?\s*(?:years?|yrs?)/);
  if (m) return { min: parseInt(m[1], 10), max: parseInt(m[2], 10) };

  // "5+ years", "minimum 3 years", "at least 4 yrs"
  m = t.match(/(?:minimum|min\.?|at least)?\s*(\d+)\s*\+\s*(?:years?|yrs?)/);
  if (m) return { min: parseInt(m[1], 10), max: parseInt(m[1], 10) };

  m = t.match(/(?:minimum|min\.?|at least)\s+(\d+)\s*(?:years?|yrs?)/);
  if (m) return { min: parseInt(m[1], 10), max: parseInt(m[1], 10) };

  // Bare "3 years experience" with no range/plus sign
  m = t.match(/(\d+)\s*(?:years?|yrs?)\s*(?:of\s*)?experience/);
  if (m) return { min: parseInt(m[1], 10), max: parseInt(m[1], 10) };

  return null; // couldn't detect anything — experience requirement unknown
}

/**
 * Scores fit against your profile using simple local keyword matching —
 * no external LLM call, so this never fails or costs an API call.
 * Returns { score: 0-100, reason: string }.
 */
function scoreJobLocally(title, company, description) {
  const text = ((title || "") + " " + (description || "")).toLowerCase();

  const STACK_KEYWORDS = ["react", "node", "node.js", "express", "mongodb", "mongo",
    "javascript", "typescript", "next.js", "nextjs", "redux", "rest api",
    "graphql", "postgresql", "postgres", "docker", "aws", "git", "html", "css", "tailwind"];

  let hits = 0;
  STACK_KEYWORDS.forEach(kw => {
    if (text.indexOf(kw) !== -1) hits++;
  });

  // MERN core (react/node/express/mongo) counts double — those matter most.
  const CORE_KEYWORDS = ["react", "node", "node.js", "express", "mongodb", "mongo"];
  let coreHits = 0;
  CORE_KEYWORDS.forEach(kw => {
    if (text.indexOf(kw) !== -1) coreHits++;
  });

  const score = Math.min(100, Math.round((coreHits / CORE_KEYWORDS.length) * 60 + (hits / STACK_KEYWORDS.length) * 40));
  const reason = `Matched ${coreHits}/${CORE_KEYWORDS.length} core MERN keywords and ${hits}/${STACK_KEYWORDS.length} total stack keywords.`;

  return { score, reason };
}

function fetchAdzunaMernJobs() {
  // Make sure these three are defined (either here or as script properties)
  const COUNTRY_CODE = "in"; // Adzuna country code for India
  const APP_ID = "YOUR_APP_ID";
  const APP_KEY = "YOUR_APP_KEY";

  // Adzuna's "what" / "what_exclude" params do NOT support boolean "OR" syntax —
  // they're plain keyword/phrase searches. Use "what_or" for an actual OR match,
  // and keep what_exclude to plain space-separated words (ANDed exclude terms).
  const query = encodeURIComponent('MERN React Node.js MongoDB');
  const location = encodeURIComponent('Chennai');
  const excludeKeywords = encodeURIComponent('senior lead manager architect');

  const url = `https://api.adzuna.com/v1/api/jobs/${COUNTRY_CODE}/search/1?app_id=${APP_ID}&app_key=${APP_KEY}&results_per_page=50&what_or=${query}&what_exclude=${excludeKeywords}&where=${location}`;

  Logger.log("Request URL: " + url.replace(APP_ID, "***").replace(APP_KEY, "***"));

  try {
    // Retry with backoff — Adzuna occasionally returns a transient 503.
    let response, responseCode;
    const maxAttempts = 3;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      response = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
      responseCode = response.getResponseCode();
      Logger.log(`Attempt ${attempt}: HTTP status ${responseCode}`);

      if (responseCode === 200) break;

      if (attempt < maxAttempts) {
        const waitMs = attempt * 2000; // 2s, then 4s
        Logger.log(`Non-200 response, retrying in ${waitMs / 1000}s...`);
        Utilities.sleep(waitMs);
      }
    }

    if (responseCode !== 200) {
      Logger.log("Adzuna API error response after retries: " + response.getContentText());
      return;
    }

    const data = JSON.parse(response.getContentText());

    Logger.log("Raw results from Adzuna: " + (data.results ? data.results.length : 0) +
               " (API reports total available: " + data.count + ")");

    if (!data.results || data.results.length === 0) {
      Logger.log("Adzuna API returned absolutely 0 MERN jobs for Chennai right now.");
      return;
    }

    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    let sheet = spreadsheet.getSheetByName("Jobs");

    // Column order matches the sheet exactly, plus G (experience) and H/I (Fable score + reason):
    // A: Date Found | B: Job Title | C: Company | D: Location | E: Description | F: Action/Apply Link
    // G: Experience Required | H: Fit Score | I: Fit Reason
    const HEADERS = ["Date Found", "Job Title", "Company", "Location", "Description", "Action/Apply Link", "Experience Required", "Fit Score", "Fit Reason"];
    const URL_COL = 6;   // column F

    if (!sheet) {
      sheet = spreadsheet.insertSheet("Jobs");
      sheet.appendRow(HEADERS);
      sheet.getRange(1, 1, 1, HEADERS.length).setFontWeight("bold").setBackground("#ea4335").setFontColor("white");
    } else {
      // Sheet already existed — backfill any headers added since it was created.
      for (let col = 7; col <= HEADERS.length; col++) {
        if (sheet.getRange(1, col).getValue() === "") {
          sheet.getRange(1, col).setValue(HEADERS[col - 1]).setFontWeight("bold").setBackground("#ea4335").setFontColor("white");
        }
      }
    }

    let existingUrls = [];
    if (sheet.getLastRow() > 1) {
      // Read from column F (the actual link column), not column E
      existingUrls = sheet.getRange(2, URL_COL, sheet.getLastRow() - 1, 1).getValues().flat();
    }

    let newJobsCount = 0;
    let skippedDuplicate = 0;
    let skippedTooExperienced = 0;
    const today = new Date();

    const MAX_YEARS_ALLOWED = 2; // treat anything requiring more than this as "too experienced"

    data.results.forEach(job => {
      const jobUrl = job.redirect_url || "";
      const title = job.title || "";
      const description = job.description || "";
      const companyName = (job.company && job.company.display_name) || "Unknown company";
      const locationName = (job.location && job.location.display_name) || "Unknown location";
      const fullText = title + " " + description;

      const exp = extractExperienceYears(fullText);
      // exp.min is the real signal — a listing that says "2-4 years" needs at least 2,
      // so we exclude it even though 2 is within range. Title keywords still catch
      // senior/lead/etc. postings that don't spell out a number at all.
      const titleFlagsSenior = /(senior|lead|manager|architect|principal|\bsr\.)/i.test(title);
      const isTooExperienced = titleFlagsSenior || (exp !== null && exp.min > MAX_YEARS_ALLOWED);
      const isDuplicate = existingUrls.includes(jobUrl);

      const expLabel = exp === null ? "Not specified" :
                        (exp.min === 0 && exp.max === 0) ? "Fresher" :
                        (exp.min === exp.max) ? `${exp.min}+ years` :
                        `${exp.min}-${exp.max} years`;

      if (isDuplicate) {
        skippedDuplicate++;
      } else if (isTooExperienced) {
        skippedTooExperienced++;
        Logger.log(`SKIPPED (experience: ${expLabel}): ${title} @ ${companyName}`);
      } else {
        const fit = scoreJobLocally(title, companyName, description);

        sheet.appendRow([
          today,                          // Date Found
          title,                          // Job Title
          companyName,                    // Company
          locationName,                   // Location
          description,                     // Description
          jobUrl,                         // Action/Apply Link
          expLabel,                       // Experience Required
          fit.score,                      // Fit Score (0-100, or blank if scoring failed)
          fit.reason                      // Fit Reason
        ]);
        newJobsCount++;
        Logger.log(`ADDED (experience: ${expLabel}, fit score: ${fit.score}): ${title} @ ${companyName}`);
      }
    });

    Logger.log(`Summary: ${data.results.length} fetched, ${newJobsCount} added, ${skippedDuplicate} already in sheet, ${skippedTooExperienced} filtered as too experienced.`);

  } catch (error) {
    Logger.log("Error fetching jobs: " + error.toString());
  }
}
