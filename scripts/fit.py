"""Fit score (0-100) of a lead against the user's resume. EDIT `HAVE` and `GAPS` below to match YOUR resume. Used by collect.py to skip off-target roles before
the agent ever claims them, and by pool.py to order work (fresh first, then best fit).

Parts: role 25 + skills 30 + experience 25 + location 10 + pay 10. The same rubric as logs/apply-yourself.md.
"""
import re

HAVE = {
    r'c\+\+': 'C++', r'\bpython\b': 'Python', r'typescript': 'TypeScript', r'javascript': 'JavaScript',
    r'\bjava\b': 'Java', r'\bsql\b|postgres|mysql': 'SQL', r'\bbash\b|shell script': 'Bash',
    r'\breact\b': 'React', r'next\.?js': 'Next.js', r'node\.?js': 'Node', r'\blinux\b': 'Linux',
    r'rest(ful)? api|\brest\b|\bapis?\b': 'REST/APIs', r'distributed system': 'distributed systems',
    r'load.?balanc|\bnat\b|tcp|networking|network': 'networking', r'observab|monitoring|alerting|dashboards': 'observability',
    r'ci/?cd|deployment pipeline': 'CI/CD', r'on-?call|incident': 'on-call/incidents', r'microservice': 'microservices',
    r'\bbackend\b|back-end': 'backend', r'full.?stack': 'full-stack', r'\bllm|generative ai|\bai\b': 'AI/LLM',
}
GAPS = {
    r'\bgo(lang)?\b': 'Go', r'\brust\b': 'Rust', r'kubernetes|\bk8s\b': 'Kubernetes', r'\bscala\b': 'Scala', r'\bruby\b|rails': 'Ruby',
    r'kotlin': 'Kotlin', r'swift': 'Swift', r'c#|\.net': 'C#/.NET', r'\bphp\b': 'PHP', r'terraform': 'Terraform',
    r'\baws\b': 'AWS', r'\bgcp\b|google cloud': 'GCP', r'azure': 'Azure', r'kafka': 'Kafka', r'spark': 'Spark',
    r'pytorch|tensorflow': 'ML frameworks', r'django|flask|fastapi': 'Python web frameworks', r'graphql': 'GraphQL',
    r'elixir|haskell|clojure|erlang': 'functional langs',
}

def title_score(t):
    t = t.lower()
    if re.search(r'backend|back-end|distributed|infrastructure|platform|site reliability|\bsre\b|devops|cloud|systems|core|network|dataplane', t): return 25
    if re.search(r'full.?stack|product engineer|software engineer|software development engineer|\bsde\b|developer', t): return 22
    if re.search(r'forward.?deployed|solutions|implementation', t): return 17
    if re.search(r'security', t): return 15
    if re.search(r'data|etl|pipeline', t): return 15
    if re.search(r'machine learning|\bml\b|\bai\b|research|inference|model', t): return 12
    return 14

def level_penalty(t):
    return -6 if re.search(r'\biii\b|\bsenior\b|\bstaff\b|lead\b|principal', t.lower()) else 0

def skills(desc):
    d = (desc or '').lower()
    return [lab for rx, lab in HAVE.items() if re.search(rx, d)], sorted({lab for rx, lab in GAPS.items() if re.search(rx, d)})

def exp_score(y, title):
    if y is None: s = 17
    elif y <= 2: s = 25
    elif y == 3: s = 20
    elif y == 4: s = 14
    elif y == 5: s = 10
    else: s = 4
    if re.search(r'\bii\b|mid.?level', title.lower()) and y is None: s = 19
    return s

def loc_score(loc):
    l = (loc or '').lower()
    if re.search(r'new york|nyc|brooklyn|manhattan|chicago|remote|anywhere', l): return 10
    if not l or 'see' in l or l == 'united states': return 7
    return 3

def pay_score(hi, lo):
    if hi is None: return 6
    return 10 if lo >= 150000 else 8 if hi >= 180000 else 6 if hi >= 150000 else 4 if hi >= 120000 else 2

def score(title, desc, years, location, band_lo, band_hi):
    have, gaps = skills((desc or '') + ' ' + title)
    ss = max(0, min(30, round(30 * min(1.0, len(have) / 6))) - min(10, 2 * len(gaps))) if desc else 14
    total = title_score(title) + level_penalty(title) + ss + exp_score(years, title) + loc_score(location) + pay_score(band_hi, band_lo)
    return max(0, min(100, total))
