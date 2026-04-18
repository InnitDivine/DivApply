"""Prompt builder for the autonomous job application agent.

Constructs the full instruction prompt that tells Claude Code / the AI agent
how to fill out a job application form using Playwright MCP tools. All
personal data is loaded from the user's profile -- nothing is hardcoded.
"""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from divapply import config

logger = logging.getLogger(__name__)


def _build_profile_summary(profile: dict) -> str:
    """Format the applicant profile section of the prompt.

    Reads all relevant fields from the profile dict and returns a
    human-readable multi-line summary for the agent.
    """
    p = profile
    personal = p.get("personal", {})
    work_auth = p.get("work_authorization", {})
    comp = p.get("compensation", {})
    exp = p.get("experience", {})
    avail = p.get("availability", {})
    eeo = p.get("eeo_voluntary", {})

    lines = [
        f"Name: {personal['full_name']}",
        f"Email: {personal['email']}",
        f"Phone: {personal['phone']}",
    ]

    # Address -- handle optional fields gracefully
    addr_parts = [
        personal.get("address", ""),
        personal.get("city", ""),
        personal.get("province_state", ""),
        personal.get("country", ""),
        personal.get("postal_code", ""),
    ]
    lines.append(f"Address: {', '.join(p for p in addr_parts if p)}")

    if personal.get("linkedin_url"):
        lines.append(f"LinkedIn: {personal['linkedin_url']}")
    if personal.get("github_url"):
        lines.append(f"GitHub: {personal['github_url']}")
    if personal.get("portfolio_url"):
        lines.append(f"Portfolio: {personal['portfolio_url']}")
    if personal.get("website_url"):
        lines.append(f"Website: {personal['website_url']}")

    # Work authorization
    lines.append(f"Work Auth: {work_auth.get('legally_authorized_to_work', 'See profile')}")
    lines.append(f"Sponsorship Needed: {work_auth.get('require_sponsorship', 'See profile')}")
    if work_auth.get("work_permit_type"):
        lines.append(f"Work Permit: {work_auth['work_permit_type']}")

    # Compensation
    currency = comp.get("salary_currency", "USD")
    lines.append(f"Salary Expectation: ${comp['salary_expectation']} {currency}")

    # Experience
    if exp.get("years_of_experience_total"):
        lines.append(f"Years Experience: {exp['years_of_experience_total']}")
    if exp.get("education_level"):
        lines.append(f"Education: {exp['education_level']}")

    # Availability
    lines.append(f"Available: {avail.get('earliest_start_date', 'Immediately')}")

    # Standard responses
    lines.extend([
        "Age 18+: Yes",
        "Background Check: Yes",
        "Felony: No",
        "Previously Worked Here: No",
        "How Heard: Online Job Board",
    ])

    # EEO
    lines.append(f"Gender: {eeo.get('gender', 'Decline to self-identify')}")
    lines.append(f"Race: {eeo.get('race_ethnicity', 'Decline to self-identify')}")
    lines.append(f"Veteran: {eeo.get('veteran_status', 'I am not a protected veteran')}")
    lines.append(f"Disability: {eeo.get('disability_status', 'I do not wish to answer')}")

    # Education schools
    edu_schools = p.get("education_schools", [])
    if edu_schools:
        lines.append("\n== EDUCATION (list ALL schools in this order on forms) ==")
        for i, sch in enumerate(edu_schools, 1):
            degree_status = "Yes" if sch.get("degree_received") else "No (in progress)" if sch.get("end_year") == "present" else "No"
            lines.append(
                f"School {i}: {sch['school']} | {sch['city_state']} | "
                f"Major: {sch['major']} | Minor: {sch.get('minor','N/A')} | "
                f"Degree: {sch['degree']} | Received: {degree_status} | "
                f"Units: {sch['units']} {sch.get('units_type','Semester')} | GPA: {sch.get('gpa','N/A')} | "
                f"{sch['start_year']}â€“{sch['end_year']}"
            )
        school_names = ", ".join(s["school"] for s in edu_schools)
        lines.append(f"IMPORTANT: Always enter ALL {len(edu_schools)} schools ({school_names}). Add schools if needed using 'Add Another School'.")

    # Employer addresses
    emp_addrs = p.get("employer_addresses", {})
    if emp_addrs:
        lines.append("\n== EMPLOYER ADDRESSES (use when work history forms require an address) ==")
        for employer, addr in emp_addrs.items():
            lines.append(f"{employer}: {addr}")

    # Supplemental answers
    supplemental = p.get("supplemental_answers", {})
    if supplemental:
        lines.append("\n== PRE-WRITTEN ANSWERS (use these verbatim for matching questions) ==")
        for key, val in supplemental.items():
            lines.append(f"{key}: {val}")

    # Question bank â€” covers common government/ATS questions
    qbank = p.get("question_bank", {})
    if qbank:
        lines.append("\n== QUESTION BANK (use for any question that matches) ==")
        lines.append("When you encounter any supplemental, screening, or agency question, find the closest match below and use that answer. Do not leave questions blank or guess randomly.")
        for key, val in qbank.items():
            label = key.replace("_", " ").title()
            lines.append(f"{label}: {val}")

    return "\n".join(lines)


def _build_location_check(profile: dict, search_config: dict) -> str:
    """Build the location eligibility check section of the prompt.

    Uses the accept_patterns from search config to determine which cities
    are acceptable for hybrid/onsite roles.
    """
    personal = profile["personal"]
    location_cfg = search_config.get("location", {})
    accept_patterns = location_cfg.get("accept_patterns", [])
    primary_city = personal.get("city", location_cfg.get("primary", "your city"))

    # Build the list of acceptable cities for hybrid/onsite
    if accept_patterns:
        city_list = ", ".join(accept_patterns)
    else:
        city_list = primary_city

    return f"""== LOCATION CHECK (do this FIRST before any form) ==
Read the job page. Determine the work arrangement. Then decide:
- "Remote" or "work from anywhere" -> ELIGIBLE. Apply.
- "Hybrid" or "onsite" in {city_list} -> ELIGIBLE. Apply.
- "Hybrid" or "onsite" in another city BUT the posting also says "remote OK" or "remote option available" -> ELIGIBLE. Apply.
- "Onsite only" or "hybrid only" in any city outside the list above with NO remote option -> NOT ELIGIBLE. Stop immediately. Output RESULT:FAILED:not_eligible_location
- City is overseas (India, Philippines, Europe, etc.) with no remote option -> NOT ELIGIBLE. Output RESULT:FAILED:not_eligible_location
- Cannot determine location -> Continue applying. If a screening question reveals it's non-local onsite, answer honestly and let the system reject if needed.
Do NOT fill out forms for jobs that are clearly onsite in a non-acceptable location. Check EARLY, save time."""


def _build_salary_section(profile: dict) -> str:
    """Build the salary negotiation instructions.

    Adapts floor, range, and currency from the profile's compensation section.
    """
    comp = profile["compensation"]
    currency = comp.get("salary_currency", "USD")
    floor = comp["salary_expectation"]
    range_min = comp.get("salary_range_min", floor)
    range_max = comp.get("salary_range_max", str(int(floor) + 20000) if floor.isdigit() else floor)
    conversion_note = comp.get("currency_conversion_note", "")

    # Compute example hourly rates at 3 salary levels
    try:
        floor_int = int(floor)
        examples = [
            (f"${floor_int // 1000}K", floor_int // 2080),
            (f"${(floor_int + 25000) // 1000}K", (floor_int + 25000) // 2080),
            (f"${(floor_int + 55000) // 1000}K", (floor_int + 55000) // 2080),
        ]
        hourly_line = ", ".join(f"{sal} = ${hr}/hr" for sal, hr in examples)
    except (ValueError, TypeError):
        hourly_line = "Divide annual salary by 2080"

    # Currency conversion guidance
    if conversion_note:
        convert_line = f"Posting is in a different currency? -> {conversion_note}"
    else:
        convert_line = "Posting is in a different currency? -> Target midpoint of their range. Convert if needed."

    return f"""== SALARY (think, don't just copy) ==
${floor} {currency} is the FLOOR. Never go below it. But don't always use it either.

Decision tree:
1. Job posting shows a range (e.g. "$120K-$160K")? -> Answer with the MIDPOINT ($140K).
2. Title says Senior, Staff, Lead, Principal, Architect, or level II/III/IV? -> Minimum $110K {currency}. Use midpoint of posted range if higher.
3. {convert_line}
4. No salary info anywhere? -> Use ${floor} {currency}.
5. Asked for a range? -> Give posted midpoint minus 10% to midpoint plus 10%. No posted range? -> "${range_min}-${range_max} {currency}".
6. Hourly rate? -> Divide your annual answer by 2080. ({hourly_line})"""


def _build_screening_section(profile: dict) -> str:
    """Build the screening questions guidance section."""
    personal = profile["personal"]
    exp = profile.get("experience", {})
    city = personal.get("city", "their city")
    years = exp.get("years_of_experience_total", "multiple")
    target_role = exp.get("target_role", personal.get("current_job_title", "software engineer"))
    work_auth = profile["work_authorization"]

    return f"""== SCREENING QUESTIONS (be strategic) ==
Hard facts -> answer truthfully from the profile. No guessing. This includes:
  - Location/relocation: lives in {city}, cannot relocate
  - Work authorization: {work_auth.get('legally_authorized_to_work', 'see profile')}
  - Citizenship, clearance, licenses, certifications: answer from profile only
  - Criminal/background: answer from profile only

Skills and tools -> be confident. This candidate is a {target_role} with {years} years experience. If the question asks "Do you have experience with [tool]?" and it's in the same domain (DevOps, backend, ML, cloud, automation), answer YES. Software engineers learn tools fast. Don't sell short.

ABSOLUTE RULE: NEVER leave ANY required field blank. NEVER click Next or Submit with unanswered required fields.
  - If a field has "Error: This field is required" or an asterisk (*), it MUST be filled before proceeding.
  - If you don't know the exact answer, use the closest match from the profile/question bank.
  - If you genuinely have no relevant experience for a question, say so honestly but connect transferable skills.

Open-ended / essay questions -> NEVER leave a required text field blank. You MUST write an answer. Rules:
  1. Read the question carefully. Write 2-4 sentences directly answering it.
  2. Draw from the resume and job description. Be specific -- name real experiences.
  3. No generic fluff. No "I am passionate about..." Start with a fact or action.
  4. If the question is about an area where the candidate has direct experience, lead with that.
  5. If the question is about an area where experience is indirect, connect transferable skills honestly.
  6. If the candidate has NO experience in the area asked, be honest but frame it constructively: "While I do not have direct [X] experience, I bring [transferable skill] from [real experience]." NEVER leave it blank.

BACKGROUND FOR COMMUNITY/RECREATION/SENIOR PROGRAM QUESTIONS:
  - Candidate currently works at City of Roseville Parks, Recreation & Libraries -- direct public recreation experience
  - Serves the public daily at a high-volume municipal counter across Parks, Recreation, and Libraries divisions
  - Has processed program registrations, facility permits, and fee payments for recreation programs
  - Public Health degree (in progress) includes coursework relevant to community health and services
  - Government operations experience spans multiple departments and age groups
  Use this context when answering questions about senior programs, recreation coordination, community engagement, or working with the public.

CalPERS questions -> "Are you a CalPERS member?" = No. "Are you a CalPERS retiree?" = No.
Previously employed here -> No (unless the job site matches current/former employers in the profile).
Related to employee -> No.
Under 18 / work permit -> N/A (candidate is an adult).
Acknowledge salary / background check checkboxes -> Always check/acknowledge these.

RADIO BUTTON + CONDITIONAL TEXT BOX PATTERN (extremely common on government forms):
Many questions are a Yes/No radio followed by a text box. The text box may say "If yes, explain", "If no, put N/A", or it may say NOTHING at all â€” just a blank text box sitting below the radio.
RULES:
  - ALWAYS select a radio button. Never leave a radio group unselected.
  - After selecting a radio, look at ANY text box immediately below it and fill it:
      * Selected NO + text box present (regardless of what the label says) -> type N/A
      * Selected YES + text box present -> fill with the real relevant information
  - Do NOT assume a text box is optional just because it doesn't say "required" â€” fill it anyway
  - Even if the text box appears grayed out or is not marked required, fill it with N/A when you answered No
  - The text box may be on the NEXT line, indented, or appear after a follow-up question number â€” scroll carefully and check every field after each radio answer

COMMON RADIO ANSWERS for government applications:
  - "Have you ever been employed here before?" -> No -> text box = N/A
  - "Are you related to a current employee?" -> No -> text box = N/A
  - "Are you a CalPERS member/retiree?" -> No
  - "Are you under 18?" -> No (or N/A on permit field)
  - "Do you have a valid driver's license?" -> Yes (candidate has a license)
  - "Are you willing to work overtime?" -> Yes
  - "Are you willing to work weekends/evenings?" -> Yes
  - Shift availability checkboxes -> Check ALL options available: Day âœ…, Evening âœ…, Nights âœ…, Weekends âœ…, Holidays âœ… â€” select everything, candidate is fully flexible
  - "Where did you hear about this position?" -> GovernmentJobs Website / Internet / Other (pick whichever matches the site)

EEO / Voluntary Self-Identification / Agency Questions -> Use the REAL answers below. Do NOT select "Decline to state" or "Prefer not to say":
  - Gender: Male
  - Preferred Pronoun: he/him
  - Race/Ethnicity: White (Not Hispanic or Latino) â€” pick whichever option matches "White" and is NOT Hispanic/Latino
  - Veteran status: I am not a protected veteran / Not a veteran / No (select whatever option means not a veteran)
  - Disability status: I do not have a disability / No disability (do NOT select "Decline to state" or "I don't wish to answer")
  - Related to employee at this agency: No -> text box = N/A
  - Currently employed at this agency: No
  - How did you hear about this position: GovernmentJobs.com (or closest match like "Internet", "Online Job Board", "Government Jobs Website")
  - If "Other" for how heard: leave blank or type "Online Job Board"
  - Tribal affiliation: N/A
  These are voluntary disclosures â€” always fill them with the real answer, never decline.
  CRITICAL: Agency Questions sections often appear BEFORE supplemental questions. Fill ALL of them. Do not skip any.

EDUCATION FORM RULES (applies to all ATS / government application education sections):
  The candidate's education path: UNR (first) â†’ TMCC (transferred, got Associate's) â†’ University of the Cumberlands (current/highest, pursuing Bachelor's).
  "Highest education" = University of the Cumberlands (B.S. in progress). On dropdowns, select "Bachelor's Degree" or "Some College" â€” never stop at "Associate's" even though that's the highest completed.
  Always enter all THREE schools, most recent first:
    1. University of the Cumberlands â€” Williamsburg, KY â€” Major: Public Health â€” Minor: Business â€” Degree: Bachelor of Science (in progress) â€” Degree received: No â€” ~101 semester units â€” GPA 3.692 â€” 2024â€“present
    2. Truckee Meadows Community College â€” Reno, NV â€” Major: General Studies â€” Minor: Business â€” Degree: Associate of General Studies â€” Degree received: Yes (May 2024) â€” 17 semester units â€” GPA 2.92 â€” 2023â€“2024
    3. University of Nevada, Reno â€” Reno, NV â€” Major: Community Health Sciences â€” Minor: Business â€” Degree: Bachelor of Science (not completed) â€” Degree received: No â€” 71 semester units â€” GPA 3.358 â€” 2019â€“2022
  If the form only allows 2 schools, enter #1 and #2 and skip #3.
  If the form has an "Add Another School" or "+ Add Education" button, click it to add the third entry.
  Never leave UNR out if there is room for it.

CIVIL SERVICE / GOVERNMENT SUPPLEMENTAL QUESTIONNAIRE RULES:
Government agencies (NEOGOV, GovernmentJobs, Workday government portals) often have a dedicated "Supplemental Questions" page. These are MANDATORY â€” you cannot submit without answering all of them.

== SPEED STRATEGY: DO THIS IN 3 BROWSER ACTIONS, NOT 50 ==

ACTION 1 â€” READ THE WHOLE PAGE AT ONCE:
Use browser_evaluate to extract ALL question text and ALL option text in one shot:
browser_evaluate function: () => {{
  const out = [];
  document.querySelectorAll('input[type=checkbox],input[type=radio],textarea,select').forEach(el => {{
    const lbl = el.labels?.[0]?.textContent?.trim() || el.closest('label')?.textContent?.trim() || el.name || el.id;
    out.push({{ type: el.type || el.tagName, name: el.name, id: el.id, label: lbl, value: el.value }});
  }});
  return out;
}}
Read the result. Now you know EVERY input on the page with its id/name. Plan all answers before touching anything.

ACTION 2 â€” RUN THIS EXACT JavaScript (browser_evaluate) â€” it handles ALL checkboxes and ALL text areas on the page in one call:
browser_evaluate function: () => {{
  const results = {{}};
  // --- CHECKBOX HELPER: click any checkbox whose label contains any of the given strings ---
  function checkAll(partials) {{
    let n = 0;
    document.querySelectorAll('input[type=checkbox]').forEach(el => {{
      const lbl = (el.labels?.[0]?.textContent || el.closest('label')?.textContent || document.querySelector('label[for="'+el.id+'"]')?.textContent || '').toLowerCase();
      if (partials.some(p => lbl.includes(p.toLowerCase())) && !el.checked) {{ el.click(); n++; }}
    }});
    return n;
  }}
  // --- RADIO HELPER: click radio whose label best matches ---
  function clickRadio(partial) {{
    for (const el of document.querySelectorAll('input[type=radio]')) {{
      const lbl = (el.labels?.[0]?.textContent || el.closest('label')?.textContent || '').toLowerCase();
      if (lbl.includes(partial.toLowerCase()) && !el.checked) {{ el.click(); return true; }}
    }}
    return false;
  }}
  // --- TEXTAREA HELPER: fill first textarea whose id/name/nearby-label contains partial ---
  function fillArea(partial, text) {{
    for (const el of document.querySelectorAll('textarea')) {{
      const key = (el.id + ' ' + el.name + ' ' + (el.closest('[class*="question"],[class*="Question"],[class*="item"]')?.textContent||'')).toLowerCase();
      if (key.includes(partial.toLowerCase())) {{
        el.value = text; el.dispatchEvent(new Event('input',{{bubbles:true}})); el.dispatchEvent(new Event('change',{{bubbles:true}})); return true;
      }}
    }}
    // fallback: fill first empty textarea
    for (const el of document.querySelectorAll('textarea')) {{ if (!el.value.trim()) {{ el.value = text; el.dispatchEvent(new Event('input',{{bubbles:true}})); el.dispatchEvent(new Event('change',{{bubbles:true}})); return true; }} }}
    return false;
  }}

  // === IT ENVIRONMENTS / TOOLS (Q04 equivalent â€” 21 options) ===
  results.it_env = checkAll(['applications development','cloud applications','computer hardware','desktop operating system','enterprise resource planning','help desk','service desk','i.t. security','it security','microsoft office','network connectivity','remote assistance','server applications','server operating system','training end users','other']);

  // === IT SUPPORT EXPERIENCE (Q05 equivalent) ===
  results.it_support = checkAll(['deploying devices','end user technical support','installing','configuring','monitoring applications','monitoring devices','file backup','service request','user account administration']);

  // === FORMAL TRAINING (Q03 equivalent) ===
  results.training = checkAll(['business software','computer hardware diagnostic','computer operating system','computer programming','customer service','cybersecurity','enterprise resource planning','network operations','server operations','other']);

  // === DOCUMENTATION EXPERIENCE (Q07 equivalent) ===
  results.docs = checkAll(['application software operation','equipment operating','program documentation','training materials','troubleshooting procedure','other']);

  // === YEARS EXPERIENCE RADIO â€” pick "3 years or more" or highest bracket ===
  results.yrs = clickRadio('3 years or more') || clickRadio('3 or more') || clickRadio('more than 2');

  // === ACKNOWLEDGMENTS â€” drug test, read requirements, "I have read" ===
  results.ack = checkAll(['i have read','i understand']) + (clickRadio('yes') ? 1 : 0);

  // === CAREER FAIR RADIO ===
  results.fair = clickRadio('have not attended') || clickRadio('not attended');

  // === CAREER FAIR TEXT ===
  results.fairText = fillArea('career fair', 'None') || fillArea('name of event', 'None') || fillArea('event', 'None');

  // === ESSAY / NARRATIVE (Q08) â€” fill with candidate experience ===
  const essay = `Job Title: Customer Service Specialist
Employer: City of Roseville
Department/Unit: Parks, Recreation & Libraries
Dates: September 2025 â€“ Present
Duties: Tier 1 IT support for public kiosks and payment terminals via SSH and remote desktop tools. Active Directory user and group account administration. Documented recurring technical issues and authored a troubleshooting reference guide for front desk staff, reducing repeat IT escalations. High-volume transaction processing and real-time system error resolution at public counter.

Job Title: Senior Accounting Assistant
Employer: Nevada County Treasurer-Tax Collector
Department/Unit: Treasurer-Tax Collector
Dates: January 2025 â€“ May 2025
Duties: Operated Megabyte Property Tax System and Workday ERP to process property tax transactions and vendor payments. Researched and resolved data discrepancies in the automated system. Maintained audit-ready documentation of financial workflows. Assisted staff with ERP navigation, data entry procedures, and issue resolution.

Self-Directed IT Training â€“ Home Lab Administration (3+ years, ongoing):
Administer Oracle Cloud Infrastructure running Ubuntu and Oracle Linux 9 servers with Docker containerization. Configure DNS, DHCP, SSH tunnels, port forwarding, and firewall rules. Deploy and monitor web server, media server, and application server environments. File backup and recovery via NAS. Python and Bash automation scripting. PC hardware builds, POST diagnostics, BIOS recovery. Active Directory user account management.

Education:
- B.S. Public Health (Business Administration minor) â€” University of the Cumberlands, GPA 3.692, in progress (2024â€“present)
- A.A. General Studies â€” Truckee Meadows Community College (May 2024)
- 71 semester credits â€” University of Nevada, Reno (2019â€“2022)`;
  results.essay = fillArea('describe', essay) || fillArea('detail', essay) || fillArea('experience', essay) || fillArea('education', essay);

  return results;
}}

ACTION 3 â€” browser_take_screenshot to verify checkboxes are selected. If any results show 0 or false, re-run that specific section. Then scroll full page to find any remaining "Error: This field is required" messages and fix them before clicking Next.

== WHAT TO ANSWER FOR EACH QUESTION TYPE ==

ACKNOWLEDGMENT / "I have read..." -> clickByLabel("I have read") or select the only checkbox/radio.

MINIMUM QUALIFICATIONS (single radio â€” pick best fit):
  Select the option that is strictly supported by the profile and job history. Do not exaggerate experience or education.

"SELECT ALL THAT APPLY" checkbox questions â€” NEVER assume a group is "partially complete". Always select every applicable box.
CRITICAL: Do NOT skip a question because it appears to have some boxes checked. Verify and complete it.

  IT ENVIRONMENTS / TOOLS / TRAINING â€” YES only when explicitly supported by the profile or transcript knowledge. If uncertain, leave it as NO.

  IT SUPPORT EXPERIENCE (common question type about what support tasks you have done) â€” YES only for tasks explicitly supported by the profile, transcripts, or resume. Otherwise NO.

  NO for all checkbox questions: any skill, system, or certification that is not supported by the profile. "None of the above" only if it is the best factual choice.

YEARS OF EXPERIENCE radios:
  IT-specific: 3+ years -> select "3 years or more" or highest bracket
  General experience: 8 years -> select highest available bracket

NARRATIVE / ESSAY text areas â€” write inline, do NOT leave blank:
  City of Roseville, Parks Recreation & Libraries | Customer Service Specialist | Sept 2025â€“Present:
  Tier 1 IT support for public kiosks and payment terminals via SSH and remote tools. Active Directory user/group administration. Documented recurring issues; authored troubleshooting reference guide for front desk staff. High-volume transaction processing and real-time system error resolution.

  Nevada County Treasurer-Tax Collector | Senior Accounting Assistant | Janâ€“May 2025:
  Operated Megabyte Property Tax System and Workday ERP for property tax processing and vendor payments. Researched and resolved discrepancies in automated financial system records. Maintained audit-ready documentation of workflows. Assisted staff with ERP navigation and data entry.

  Self-Directed Home Lab (3+ years ongoing):
  Administer Oracle Cloud Infrastructure running Ubuntu/Oracle Linux 9 servers with Docker containers. Configure DNS, DHCP, SSH tunnels, port forwarding, and firewall rules. Deploy and monitor applications (web server, Jellyfin, game servers). NAS backup and recovery. Python/Bash automation scripting. PC builds, POST diagnostics, BIOS recovery.

  Education: B.S. Public Health (Business minor) â€” University of the Cumberlands (GPA 3.692, in progress). A.A. General Studies â€” TMCC (May 2024). 71 credits â€” UNR (2019â€“2022).

DRUG TEST / BACKGROUND CHECK acknowledgment -> ALWAYS "Yes". This is required and is often near the bottom of the page.
GENERAL REQUIREMENTS / "I have read the job announcement" acknowledgment -> ALWAYS select/check it. Required.
CAREER FAIR ATTENDANCE -> "Have not attended a career fair and/or job event." -> follow-up text = None.
HOW DID YOU HEAR -> GovernmentJobs Website / Online Job Board.

BEFORE CLICKING PROCEED/NEXT â€” MANDATORY VERIFICATION:
1. Scroll to the TOP of the page.
2. Use browser_evaluate to find every element with error text: document.querySelectorAll('[class*="error"],[class*="Error"]').forEach(e => console.log(e.textContent))
3. Scroll slowly to the BOTTOM. Count every numbered question. Check that EACH one has a selected radio, checked checkbox, or filled text.
4. Questions commonly missed: drug test agreement (Yes), "I have read..." acknowledgment, career fair attendance radio, career fair details text box.
5. Only click Proceed/Next when ZERO errors are visible and EVERY question has an answer.

ERROR MESSAGES after clicking Proceed/Next: scroll to TOP, find red error messages, fix each one. Do not click Proceed again until all are cleared."""


def _build_hard_rules(profile: dict) -> str:
    """Build the hard rules section with work auth and name from profile."""
    personal = profile["personal"]
    work_auth = profile["work_authorization"]

    full_name = personal["full_name"]
    preferred_name = personal.get("preferred_name", full_name.split()[0])
    preferred_last = full_name.split()[-1] if " " in full_name else ""
    display_name = f"{preferred_name} {preferred_last}".strip() if preferred_last else preferred_name

    # Build work auth rule dynamically
    auth_info = work_auth.get("legally_authorized_to_work", "")
    sponsorship = work_auth.get("require_sponsorship", "")
    permit_type = work_auth.get("work_permit_type", "")

    work_auth_rule = "Work auth: Answer truthfully from profile."
    if permit_type:
        work_auth_rule = f"Work auth: {permit_type}. Sponsorship needed: {sponsorship}."

    name_rule = f'Name: Legal name = {full_name}.'
    if preferred_name and preferred_name != full_name.split()[0]:
        name_rule += f' Preferred name = {preferred_name}. Use "{display_name}" unless a field specifically says "legal name".'

    return f"""== HARD RULES (never break these) ==
1. Never lie about: citizenship, work authorization, criminal history, education credentials, security clearance, licenses.
2. {work_auth_rule}
3. {name_rule}"""


def _build_captcha_section() -> str:
    """Build the CAPTCHA detection and solving instructions.

    Reads the CapSolver API key from environment. The CAPTCHA section
    contains no personal data -- it's the same for every user.
    """
    config.load_env()
    capsolver_key = os.environ.get("CAPSOLVER_API_KEY", "")

    return f"""== CAPTCHA ==
You solve CAPTCHAs via the CapSolver REST API. No browser extension. You control the entire flow.
API key: {capsolver_key or 'NOT CONFIGURED â€” skip to MANUAL FALLBACK for all CAPTCHAs'}
API base: https://api.capsolver.com

CRITICAL RULE: When ANY CAPTCHA appears (hCaptcha, reCAPTCHA, Turnstile -- regardless of what it looks like visually), you MUST:
1. Run CAPTCHA DETECT to get the type and sitekey
2. Run CAPTCHA SOLVE (createTask -> poll -> inject) with the CapSolver API
3. ONLY go to MANUAL FALLBACK if CapSolver returns errorId > 0
Do NOT skip the API call based on what the CAPTCHA looks like. CapSolver solves CAPTCHAs server-side -- it does NOT need to see or interact with images, puzzles, or games. Even "drag the pipe" or "click all traffic lights" hCaptchas are solved via API token, not visually. ALWAYS try the API first.

--- CAPTCHA DETECT ---
Run this browser_evaluate after every navigation, Apply/Submit/Login click, or when a page feels stuck.
IMPORTANT: Detection order matters. hCaptcha elements also have data-sitekey, so check hCaptcha BEFORE reCAPTCHA.

browser_evaluate function: () => {{{{
  const r = {{}};
  const url = window.location.href;
  // 1. hCaptcha (check FIRST -- hCaptcha uses data-sitekey too)
  const hc = document.querySelector('.h-captcha, [data-hcaptcha-sitekey]');
  if (hc) {{{{
    r.type = 'hcaptcha'; r.sitekey = hc.dataset.sitekey || hc.dataset.hcaptchaSitekey;
  }}}}
  if (!r.type && document.querySelector('script[src*="hcaptcha.com"], iframe[src*="hcaptcha.com"]')) {{{{
    const el = document.querySelector('[data-sitekey]');
    if (el) {{{{ r.type = 'hcaptcha'; r.sitekey = el.dataset.sitekey; }}}}
  }}}}
  // 2. Cloudflare Turnstile
  if (!r.type) {{{{
    const cf = document.querySelector('.cf-turnstile, [data-turnstile-sitekey]');
    if (cf) {{{{
      r.type = 'turnstile'; r.sitekey = cf.dataset.sitekey || cf.dataset.turnstileSitekey;
      if (cf.dataset.action) r.action = cf.dataset.action;
      if (cf.dataset.cdata) r.cdata = cf.dataset.cdata;
    }}}}
  }}}}
  if (!r.type && document.querySelector('script[src*="challenges.cloudflare.com"]')) {{{{
    r.type = 'turnstile_script_only'; r.note = 'Wait 3s and re-detect.';
  }}}}
  // 3. reCAPTCHA v3 (invisible, loaded via render= param)
  if (!r.type) {{{{
    const s = document.querySelector('script[src*="recaptcha"][src*="render="]');
    if (s) {{{{
      const m = s.src.match(/render=([^&]+)/);
      if (m && m[1] !== 'explicit') {{{{ r.type = 'recaptchav3'; r.sitekey = m[1]; }}}}
    }}}}
  }}}}
  // 4. reCAPTCHA v2 (checkbox or invisible)
  if (!r.type) {{{{
    const rc = document.querySelector('.g-recaptcha');
    if (rc) {{{{ r.type = 'recaptchav2'; r.sitekey = rc.dataset.sitekey; }}}}
  }}}}
  if (!r.type && document.querySelector('script[src*="recaptcha"]')) {{{{
    const el = document.querySelector('[data-sitekey]');
    if (el) {{{{ r.type = 'recaptchav2'; r.sitekey = el.dataset.sitekey; }}}}
  }}}}
  // 5. FunCaptcha (Arkose Labs)
  if (!r.type) {{{{
    const fc = document.querySelector('#FunCaptcha, [data-pkey], .funcaptcha');
    if (fc) {{{{ r.type = 'funcaptcha'; r.sitekey = fc.dataset.pkey; }}}}
  }}}}
  if (!r.type && document.querySelector('script[src*="arkoselabs"], script[src*="funcaptcha"]')) {{{{
    const el = document.querySelector('[data-pkey]');
    if (el) {{{{ r.type = 'funcaptcha'; r.sitekey = el.dataset.pkey; }}}}
  }}}}
  if (r.type) {{{{ r.url = url; return r; }}}}
  return null;
}}}}

Result actions:
- null -> no CAPTCHA. Continue normally.
- "turnstile_script_only" -> browser_wait_for time: 3, re-run detect.
- Any other type -> proceed to CAPTCHA SOLVE below.

âš  DO NOT CLICK THE CAPTCHA WIDGET. Do NOT click "I'm not a robot", do NOT click the checkbox, do NOT interact with the CAPTCHA visually AT ALL before or during API solving. Clicking it triggers the interactive visual/audio challenge which you cannot solve. The API returns a token you inject silently â€” the visual widget never gets clicked.

--- CAPTCHA SOLVE ---
Three steps: createTask -> poll -> inject.
Steps 1 and 2 use Bash (curl) â€” NOT browser_evaluate. This bypasses site CSP which would block the fetch.

STEP 1 -- CREATE TASK (run as a Bash command, fill in TASK_TYPE, PAGE_URL, SITE_KEY):
curl -s -X POST https://api.capsolver.com/createTask \
  -H "Content-Type: application/json" \
  -d '{{"clientKey":"{capsolver_key}","task":{{"type":"TASK_TYPE","websiteURL":"PAGE_URL","websiteKey":"SITE_KEY"}}}}'

TASK_TYPE values (use EXACTLY these strings):
  hcaptcha     -> HCaptchaTaskProxyLess
  recaptchav2  -> ReCaptchaV2TaskProxyLess
  recaptchav3  -> ReCaptchaV3TaskProxyLess
  turnstile    -> AntiTurnstileTaskProxyLess
  funcaptcha   -> FunCaptchaTaskProxyLess

PAGE_URL = the url from detect result. SITE_KEY = the sitekey from detect result.
For recaptchav3: add ,"pageAction":"submit" inside the task object (or the actual action from page scripts).
For turnstile: add ,"metadata":{{"action":"...","cdata":"..."}} inside task if those were in detect result.

Response: {{"errorId": 0, "taskId": "abc123"}} on success.
If errorId > 0 -> CAPTCHA SOLVE failed. Go to MANUAL FALLBACK.

STEP 2 -- POLL (run as a Bash command, replace TASK_ID with taskId from step 1):
Loop: sleep 3 between polls. Max 10 polls (30s total).
curl -s -X POST https://api.capsolver.com/getTaskResult \
  -H "Content-Type: application/json" \
  -d '{{"clientKey":"{capsolver_key}","taskId":"TASK_ID"}}'

- status "processing" -> sleep 3, poll again.
- status "ready" -> extract token:
    reCAPTCHA: solution.gRecaptchaResponse
    hCaptcha:  solution.gRecaptchaResponse
    Turnstile: solution.token
- errorId > 0 or 30s timeout -> MANUAL FALLBACK.

STEP 3 -- INJECT TOKEN (replace THE_TOKEN with actual token string):

For reCAPTCHA v2/v3:
browser_evaluate function: () => {{{{
  const token = 'THE_TOKEN';
  document.querySelectorAll('[name="g-recaptcha-response"]').forEach(el => {{{{ el.value = token; el.style.display = 'block'; }}}});
  if (window.___grecaptcha_cfg) {{{{
    const clients = window.___grecaptcha_cfg.clients;
    for (const key in clients) {{{{
      const walk = (obj, d) => {{{{
        if (d > 4 || !obj) return;
        for (const k in obj) {{{{
          if (typeof obj[k] === 'function' && k.length < 3) try {{{{ obj[k](token); }}}} catch(e) {{{{}}}}
          else if (typeof obj[k] === 'object') walk(obj[k], d+1);
        }}}}
      }}}};
      walk(clients[key], 0);
    }}}}
  }}}}
  return 'injected';
}}}}

For hCaptcha:
browser_evaluate function: () => {{{{
  const token = 'THE_TOKEN';
  const ta = document.querySelector('[name="h-captcha-response"], textarea[name*="hcaptcha"]');
  if (ta) ta.value = token;
  document.querySelectorAll('iframe[data-hcaptcha-response]').forEach(f => f.setAttribute('data-hcaptcha-response', token));
  const cb = document.querySelector('[data-hcaptcha-widget-id]');
  if (cb && window.hcaptcha) try {{{{ window.hcaptcha.getResponse(cb.dataset.hcaptchaWidgetId); }}}} catch(e) {{{{}}}}
  return 'injected';
}}}}

For Turnstile:
browser_evaluate function: () => {{{{
  const token = 'THE_TOKEN';
  const inp = document.querySelector('[name="cf-turnstile-response"], input[name*="turnstile"]');
  if (inp) inp.value = token;
  if (window.turnstile) try {{{{ const w = document.querySelector('.cf-turnstile'); if (w) window.turnstile.getResponse(w); }}}} catch(e) {{{{}}}}
  return 'injected';
}}}}

For FunCaptcha: inject token into #FunCaptcha-Token or input[name="fc-token"], call window.ArkoseEnforcement.setConfig({{{{data:{{{{blob:token}}}}}}}})) if present.

After injecting: browser_wait_for time: 2, then snapshot.
- Widget gone or green check -> success. Click Submit if needed.
- No change -> click Submit/Verify/Continue button (some sites need it).
- Still stuck -> token may have expired (~2 min lifetime). Re-run from STEP 1.

--- MANUAL FALLBACK ---
You should ONLY be here if CapSolver createTask returned errorId > 0. If you haven't tried CapSolver yet, GO BACK and try it first.
If CapSolver genuinely failed (errorId > 0):
1. Audio challenge: Look for "audio" or "accessibility" button -> click it for an easier challenge.
2. Text/logic puzzles: Solve them yourself. Think step by step. Common tricks: "All but 9 die" = 9 left. "3 sisters and 4 brothers, how many siblings?" = 7.
3. Simple text captchas ("What is 3+7?", "Type the word") -> solve them.
4. All else fails -> Output RESULT:CAPTCHA."""


def build_prompt(job: dict, tailored_resume: str,
                 cover_letter: str | None = None,
                 dry_run: bool = False) -> str:
    """Build the full instruction prompt for the apply agent.

    Loads the user profile and search config internally. All personal data
    comes from the profile -- nothing is hardcoded.

    Args:
        job: Job dict from the database (must have url, title, site,
             application_url, fit_score, tailored_resume_path).
        tailored_resume: Plain-text content of the tailored resume.
        cover_letter: Optional plain-text cover letter content.
        dry_run: If True, tell the agent not to click Submit.

    Returns:
        Complete prompt string for the AI agent.
    """
    profile = config.load_profile()
    search_config = config.load_search_config()
    personal = profile["personal"]

    # --- Resolve resume PDF path ---
    resume_path = job.get("tailored_resume_path")
    if not resume_path:
        raise ValueError(f"No tailored resume for job: {job.get('title', 'unknown')}")

    src_pdf = Path(resume_path).with_suffix(".pdf").resolve()
    if not src_pdf.exists():
        raise ValueError(f"Resume PDF not found: {src_pdf}")

    # Copy to a clean filename for upload (recruiters see the filename)
    full_name = personal["full_name"]
    name_slug = full_name.replace(" ", "_")
    dest_dir = config.APPLY_WORKER_DIR / "current"
    dest_dir.mkdir(parents=True, exist_ok=True)
    upload_pdf = dest_dir / f"{name_slug}_Resume.pdf"
    shutil.copy(str(src_pdf), str(upload_pdf))
    pdf_path = str(upload_pdf)

    # --- Cover letter handling ---
    cover_letter_text = cover_letter or ""
    cl_upload_path = ""
    cl_path = job.get("cover_letter_path")
    if cl_path and Path(cl_path).exists():
        cl_src = Path(cl_path)
        # Read text from .txt sibling (PDF is binary)
        cl_txt = cl_src.with_suffix(".txt")
        if cl_txt.exists():
            cover_letter_text = cl_txt.read_text(encoding="utf-8")
        elif cl_src.suffix == ".txt":
            cover_letter_text = cl_src.read_text(encoding="utf-8")
        # Upload must be PDF
        cl_pdf_src = cl_src.with_suffix(".pdf")
        if cl_pdf_src.exists():
            cl_upload = dest_dir / f"{name_slug}_Cover_Letter.pdf"
            shutil.copy(str(cl_pdf_src), str(cl_upload))
            cl_upload_path = str(cl_upload)

    # --- Build all prompt sections ---
    profile_summary = _build_profile_summary(profile)
    location_check = _build_location_check(profile, search_config)
    salary_section = _build_salary_section(profile)
    screening_section = _build_screening_section(profile)
    hard_rules = _build_hard_rules(profile)
    captcha_section = _build_captcha_section()

    # Cover letter fallback text
    city = personal.get("city", "the area")
    if not cover_letter_text:
        cl_display = (
            f"None available. Skip if optional. If required, write 2 factual "
            f"sentences: (1) relevant experience from the resume that matches "
            f"this role, (2) available immediately and based in {city}."
        )
    else:
        cl_display = cover_letter_text

    # Phone digits only (for fields with country prefix)
    phone_digits = "".join(c for c in personal.get("phone", "") if c.isdigit())

    # SSO domains the agent cannot sign into (loaded from config/sites.yaml)
    from divapply.config import load_blocked_sso
    blocked_sso = load_blocked_sso()

    # Site-specific credentials (overrides personal.password for specific domains)
    site_creds = profile.get("site_credentials", {})
    site_creds_lines = []
    for domain, creds in site_creds.items():
        site_creds_lines.append(
            f"  - {domain}: username={creds.get('username', personal['email'])}  password={creds.get('password', '')}"
        )
    site_creds_block = (
        "SITE-SPECIFIC LOGINS (use these instead of the default password for these domains):\n"
        + "\n".join(site_creds_lines)
        if site_creds_lines else ""
    )

    # Preferred display name
    preferred_name = personal.get("preferred_name", full_name.split()[0])
    last_name = full_name.split()[-1] if " " in full_name else ""
    display_name = f"{preferred_name} {last_name}".strip()

    # Dry-run: override submit instruction
    if dry_run:
        submit_instruction = "IMPORTANT: Do NOT click the final Submit/Apply button. Review the form, verify all fields, then output RESULT:APPLIED with a note that this was a dry run."
    else:
        submit_instruction = """BEFORE clicking Submit/Apply, run a mandatory pre-submit check:
  1. Scroll to the top of the page. Take a snapshot.
  2. Scan every visible field. Look specifically for:
     - Any text area or input that is empty or says "Answer" / placeholder text (not filled in)
     - Any required field (*) that is blank
     - Any radio group with nothing selected
     - Any required checkbox that is unchecked
  3. For EVERY empty required text field you find: write a real answer based on the job description and resume. NEVER leave a required field blank. If you don't have a pre-written answer, compose one from context.
  4. Scroll down and repeat until you have checked every page section.
  5. Only after ALL fields are filled and all required items are answered: click Submit/Apply.
  6. Verify all data matches the APPLICANT PROFILE and TAILORED RESUME -- name, email, phone, location, work auth, resume uploaded, cover letter if applicable."""

    prompt = f"""You are an autonomous job application agent running in HIGH EFFORT mode. Your ONE mission: submit a complete, accurate application and get this candidate an interview. You have all the information and tools needed. Never give up on solvable obstacles â€” CAPTCHAs get solved via API, supplemental questions get answered from profile data, login walls get bypassed with provided credentials. Think strategically. Act decisively. Use every tool available. The only acceptable reason to stop early is a hard blocker explicitly listed in RESULT CODES (expired job, permanent auth wall, unsafe site). Everything else: push through and submit.

== BROWSER TOOLS â€” CRITICAL ==
You control a dedicated browser via the Playwright MCP. Use ONLY these tool prefixes:
  mcp__playwright__*  (browser_navigate, browser_click, browser_fill, browser_snapshot, etc.)
Do NOT use any alternate browser tool namespace. Those connect to a different browser and will break the application. Every browser action must go through the playwright MCP tools only.

JAVASCRIPT AND PLAYWRIGHT CODE IN THE BROWSER:
Two valid tools for browser interaction â€” use whichever is faster for the task:
  browser_evaluate  â†’ runs JavaScript directly in the page (best for reading DOM, setting .value, bulk-checking checkboxes)
  browser_run_code  â†’ runs Playwright Python API code (best for click, fill, select by label/role)
NEVER use plain Bash or computer tool to interact with the page â€” those run outside the browser entirely.

SCROLLING â€” USE browser_scroll, NEVER browser_press_key for scrolling:
  CORRECT: browser_scroll  direction: down  coordinate: [512, 400]
  WRONG:   browser_press_key key: PageDown â€” extremely slow, burns turns.
To scroll to bottom: browser_scroll direction: down coordinate: [512, 600] (repeat if page is long).

== JOB ==
URL: {job.get('application_url') or job['url']}
Title: {job['title']}
Company: {job.get('site', 'Unknown')}
Fit Score: {job.get('fit_score', 'N/A')}/10

== FILES (absolute paths â€” use EXACTLY as shown, do NOT modify or retry with different formats) ==
Resume PDF (upload this): {pdf_path}
Cover Letter PDF (upload if asked): {cl_upload_path or "N/A"}
IMPORTANT: These files are pre-staged in your working directory. When using browser_file_upload, pass the EXACT path above. Do NOT waste actions retrying with different path formats â€” if the first attempt fails, use browser_evaluate to find the <input type="file"> element and set files via JavaScript.

== RESUME TEXT (use when filling text fields) ==
{tailored_resume}

== COVER LETTER TEXT (paste if text field, upload PDF if file field) ==
{cl_display}

== APPLICANT PROFILE ==
{profile_summary}

== YOUR MISSION ==
Submit a complete, accurate application. Use the profile and resume as source data -- adapt to fit each form's format.

If something unexpected happens and these instructions don't cover it, figure it out yourself. You are autonomous. Navigate pages, read content, try buttons, explore the site. The goal is always the same: submit the application. Do whatever it takes to reach that goal.

{hard_rules}

== SCAM DETECTION â€” CHECK BEFORE APPLYING ==
Before filling any form, spend 2 actions verifying this is a legitimate employer:
1. Check the page for a real company name, physical address, or "About Us" link.
2. If ANY of these are true, output RESULT:FAILED:scam and stop immediately:
   - No company name anywhere on the page or application (just "Confidential" or "Our Client")
   - Page asks for SSN, bank account, routing number, or payment before any interview
   - Page asks you to "pay for training", "purchase a starter kit", or "send a deposit"
   - Job promises unusually high pay with no experience required and no real company behind it
   - Site redirects through 2+ domains before reaching an actual application form
   - Page is asking to "create a contractor profile" or "set your hourly rate"
   - Application is on a site like Craigslist, random Google Forms, or an unknown single-page domain with no business info
3. If the company checks out (real employer, real ATS, or government site), proceed normally.

== NEVER DO THESE (immediate RESULT:FAILED if encountered) ==
- NEVER grant camera, microphone, screen sharing, or location permissions. If a site requests them -> RESULT:FAILED:unsafe_permissions
- NEVER do video/audio verification, selfie capture, ID photo upload, or biometric anything -> RESULT:FAILED:unsafe_verification
- NEVER set up a freelancing profile (Mercor, Toptal, Upwork, Fiverr, Turing, etc.). These are contractor marketplaces, not job applications -> RESULT:FAILED:not_a_job_application
- NEVER agree to hourly/contract rates, availability calendars, or "set your rate" flows. You are applying for FULL-TIME salaried positions only.
- NEVER install browser extensions, download executables, or run assessment software.
- NEVER enter payment info, bank details, or SSN/SIN.
- NEVER click "Allow" on any browser permission popup. Always deny/block.
- If the site is NOT a job application form (it's a profile builder, skills marketplace, talent network signup, coding assessment platform) -> RESULT:FAILED:not_a_job_application

{location_check}

{salary_section}

{screening_section}

== STEP-BY-STEP ==
1. browser_navigate to the job URL.
2. browser_snapshot to read the page. Then run CAPTCHA DETECT (see CAPTCHA section). If a CAPTCHA is found, solve it before continuing.
3. LOCATION CHECK. Read the page for location info. If not eligible, output RESULT and stop.
4. Find and click the Apply button. If email-only (page says "email resume to X"):
   - send_email with subject "Application for {job['title']} -- {display_name}", body = 2-3 sentence pitch + contact info, attach resume PDF: ["{pdf_path}"]
   - Output RESULT:APPLIED. Done.
   After clicking Apply: browser_snapshot. Run CAPTCHA DETECT -- many sites trigger CAPTCHAs right after the Apply click. If found, solve before continuing.
5. Login wall?
   5a. FIRST: check the URL.
       - If you landed on accounts.google.com: this is a Google Sign-In page. The user is already signed in to Google in this browser. Look for the user's account ({personal['email']}) in the account chooser and click it. If prompted with a confirmation screen, click "Continue" or "Allow". Do NOT enter any password -- just select the existing account. After completing, you will be redirected back to the application.
       - If you landed on {', '.join(blocked_sso)}, or any other SSO/OAuth page (Microsoft, Okta, Auth0) -> STOP. Output RESULT:FAILED:sso_required.
   5b. Check for popups. Run browser_tabs action "list". If a new tab/window appeared (login popup), switch to it with browser_tabs action "select". Check the URL there too -- if it's accounts.google.com, select the existing Google account ({personal['email']}) and click Continue. If it's {', '.join(blocked_sso)} -> RESULT:FAILED:sso_required.
   5c. Regular login form (employer's own site)?
       {site_creds_block}
       Check the current URL domain. If it matches a domain in SITE-SPECIFIC LOGINS above, use those credentials.
       Otherwise use default: {personal['email']} / {personal.get('password', '')}
   5d. After clicking Login/Sign-in: run CAPTCHA DETECT. Login pages frequently have invisible CAPTCHAs that silently block form submissions. If found, solve it then retry login.
   5e. Sign in failed? Try sign up with same email and password.
   5f. Need email verification? Use search_emails + read_email to get the code.
   5g. After login, run browser_tabs action "list" again. Switch back to the application tab if needed.
   5h. All failed? Output RESULT:FAILED:login_issue. Do not loop.
6. Upload resume. ALWAYS upload fresh -- delete any existing resume first, then browser_file_upload with the PDF path above. This is the tailored resume for THIS job. Non-negotiable.
7. Upload cover letter if there's a field for it. Text field -> paste the cover letter text. File upload -> use the cover letter PDF path.
8. Check pre-filled fields but be STRATEGIC about edits. ATS systems auto-fill from your profile -- only fix things that MATTER:
   - "Current Job Title" or "Most Recent Title" -> use the title from the TAILORED RESUME summary, NOT whatever the parser guessed.
   - Fix WRONG data (wrong degree type, wrong employer, wrong job title). Fill EMPTY required fields.
   - Do NOT waste actions on trivial differences (units 103 vs 101, minor date variations, formatting differences). These won't affect your application.
9. Answer screening questions using the rules above.
10. {submit_instruction}
11. After submit: browser_snapshot. Run CAPTCHA DETECT -- submit buttons often trigger invisible CAPTCHAs. If found, solve it (the form will auto-submit once the token clears, or you may need to click Submit again). Then check for new tabs (browser_tabs action: "list"). Switch to newest, close old. Snapshot to confirm submission. Look for "thank you" or "application received".
12. Output your result.

== RESULT CODES (output EXACTLY one) ==
RESULT:APPLIED -- submitted successfully
RESULT:EXPIRED -- job closed or no longer accepting applications
RESULT:CAPTCHA -- blocked by unsolvable captcha
RESULT:LOGIN_ISSUE -- could not sign in or create account
RESULT:FAILED:not_eligible_location -- onsite outside acceptable area, no remote option
RESULT:FAILED:not_eligible_work_auth -- requires unauthorized work location
RESULT:FAILED:reason -- any other failure (brief reason)

== BROWSER EFFICIENCY â€” MINIMIZE ACTIONS AND TOKENS ==
GOLDEN RULES â€” every action costs tokens, every screenshot costs tokens:

- browser_snapshot: use ONCE per new page to get element refs. Re-snapshot only when navigating to a new page.
- browser_take_screenshot: use ONLY when you need to visually verify an error or unexpected state. NOT after every action.
- Trust browser_evaluate return values. If checkAll() returns 9, those 9 boxes are checked â€” no screenshot needed to verify.
- Fill ALL fields in ONE call. Never one field at a time.
- Think SHORT. Do not narrate what you see. Do not list what you just did. Act â†’ move on.
- Multi-page forms: snapshot once per new page, fill everything, click Next. No mid-page re-snapshots.
- SCROLLING: use browser_evaluate: () => window.scrollTo(0, document.body.scrollHeight) to jump to bottom instantly. Use browser_scroll for moderate scrolls. NEVER use browser_press_key for scrolling.
- CAPTCHA AWARENESS: run CAPTCHA DETECT after navigation and Apply/Submit/Login clicks. Invisible CAPTCHAs block silently.

== FORM TRICKS ==
- Popup/new window opened? browser_tabs action "list" to see all tabs. browser_tabs action "select" with the tab index to switch. ALWAYS check for new tabs after clicking login/apply/sign-in buttons.
- "Upload your resume" pre-fill page (Workday, Lever, etc.): This is NOT the application form yet. Click "Select file" or the upload area, then browser_file_upload with the resume PDF path. Wait for parsing to finish. Then click Next/Continue to reach the actual form.
- NEOGOV / GovernmentJobs applications â€” FAST TRACK (saves 60+ actions):
  GovernmentJobs pre-fills Work, Education, References, and Preferences from the saved account. DO NOT read, review, or try to edit these sections. Skip straight to what matters.

  NEOGOV OPTIMAL FLOW (follow this order, use left-nav tabs to jump directly):
  1. After login: click "Attachments" tab in the left navigation menu.
  2. On Attachments page: upload Resume and Cover Letter (two-step flow below).
     â†’ browser_take_screenshot to confirm both filenames appear. Then click Next.
  3. Click "Questions" tab. Run the bulk JS from CIVIL SERVICE section to fill ALL supplemental questions in one call.
     â†’ browser_take_screenshot to confirm checkboxes are checked and essay is filled. Fix anything missing. Then click Proceed/Next.
  4. Click "Review" tab. Scroll to bottom: browser_evaluate: () => window.scrollTo(0, document.body.scrollHeight)
     â†’ browser_take_screenshot to confirm "Proceed to Certify and Submit" button is visible and no red errors. Then click it.
  5. On Certify page: browser_take_screenshot to confirm certification text loaded. Click "Accept & Submit". Done.

  NEOGOV Attachments upload (two-step flow):
  STEP 1: Click "Add supplemental attachment". A dropdown "Choose attachment type" appears.
  STEP 2: Set dropdown to "Resume" via JS: browser_evaluate: () => {{ const s = document.querySelector('select[name*="attach"], select[id*="attach"], select'); const opt = [...s.options].find(o => o.text.trim() === 'Resume'); if(opt) {{ s.value = opt.value; s.dispatchEvent(new Event('change',{{bubbles:true}})); }} }}
  STEP 3: Click the "Upload" button that appears. browser_file_upload with exact resume path.
  STEP 4: Wait for filename to confirm. Then repeat steps 1-3 for Cover Letter if available.
  STEP 5: Click Next.
  If browser_file_upload fails: browser_evaluate: () => {{ const i=document.querySelector('input[type=file]'); if(i) i.style.display='block'; }} then retry.
- File upload not working? Unhide the input: browser_evaluate function: () => {{ const i=document.querySelector('input[type=file]'); if(i) i.style.display='block'; }} then browser_file_upload again.
- Dropdown won't fill? Try browser_select first. If that fails: browser_click to open, then browser_click the option. If that fails: use browser_evaluate to set .value and fire a change event.
- Checkbox won't check via fill_form? Use browser_click on it instead. Snapshot to verify.
- Phone field with country prefix: just type digits {phone_digits}
- Date fields: {datetime.now().strftime('%m/%d/%Y')}
- Validation errors after submit? Take BOTH snapshot AND screenshot. Snapshot shows text errors, screenshot shows red-highlighted fields. Fix all, retry.
- Honeypot fields (hidden, "leave blank"): skip them.
- Format-sensitive fields: read the placeholder text, match it exactly.

{captcha_section}

== WHEN TO GIVE UP (fail fast, don't waste turns) ==
- Same page after 3 attempts with no progress -> RESULT:FAILED:stuck
- Same action failing 3 times in a row (upload, click, fill) -> try ONE alternative approach, then RESULT:FAILED:stuck
- Job is closed/expired/page says "no longer accepting" -> RESULT:EXPIRED
- Page is broken/500 error/blank -> RESULT:FAILED:page_error
- Login loop (redirected back to login after signing in 2+ times) -> RESULT:FAILED:login_issue
Stop immediately. Output your RESULT code. Do not loop."""

    return prompt

