"""
agent_search.py — Search Kaggle and GitHub for STEP file datasets relevant
to weak MFCAD++ feature classes. Returns candidate datasets for Gemini to rank.

Kaggle auth: supports both new KGAT_ bearer tokens (access_token file or
KAGGLE_API_TOKEN env var) and the classic kaggle.json (username + key).
"""

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Kaggle search (REST API with Bearer token — no kaggle CLI needed)
# ---------------------------------------------------------------------------

KAGGLE_KEYWORDS = [
    "STEP file 3D CAD dataset",
    "mechanical part CAD dataset",
    "3D CAD machining dataset",
    "solid model manufacturing dataset",
    "CAD geometry dataset labeled",
    "B-Rep STEP annotated",
    "ABC dataset mechanical",
    "Fusion360 CAD dataset",
    "PartNet mechanical parts",
    "engineering CAD STEP files",
]

GITHUB_KEYWORDS = [
    "STEP+files+CAD+dataset+labeled",
    "mechanical+part+3D+dataset+annotated",
    "B-Rep+machining+dataset",
    "CAD+feature+recognition+dataset",
    "ABC+dataset+CAD+mechanical",
    "Fusion360+gallery+dataset",
    "PartNet+CAD+segmentation",
]


def _get_kaggle_token() -> str | None:
    """
    Return a Kaggle auth token string, trying in order:
      1. KAGGLE_API_TOKEN env var (new KGAT_ bearer token)
      2. ~/.kaggle/access_token file (new KGAT_ bearer token)
      3. ~/.kaggle/kaggle.json (classic username:key — returned as Basic auth header value)
    Returns None if no credentials found.
    """
    # New-style bearer token
    token = os.environ.get("KAGGLE_API_TOKEN", "")
    if token:
        return token

    token_file = Path.home() / ".kaggle" / "access_token"
    if token_file.exists():
        t = token_file.read_text().strip()
        if t:
            return t

    # Classic kaggle.json
    json_file = Path.home() / ".kaggle" / "kaggle.json"
    if json_file.exists():
        try:
            creds = json.loads(json_file.read_text())
            import base64
            pair = f"{creds['username']}:{creds['key']}"
            return "basic:" + base64.b64encode(pair.encode()).decode()
        except Exception:
            pass

    return None


def _kaggle_api_request(path: str, token: str) -> dict | None:
    """Make a Kaggle REST API request. Returns parsed JSON or None on error."""
    url = f"https://www.kaggle.com/api/v1/{path}"
    headers = {"Content-Type": "application/json"}
    if token.startswith("basic:"):
        headers["Authorization"] = f"Basic {token[6:]}"
    else:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[search] Kaggle API error ({path}): {e}")
        return None


def search_kaggle(weak_classes: list[str], max_results: int = 5) -> list[dict]:
    """
    Search Kaggle datasets via REST API.
    Returns list of {title, ref, url, size_mb, downloads, search_term}.
    """
    token = _get_kaggle_token()
    if not token:
        print("[search] No Kaggle credentials found — skipping Kaggle search")
        return []

    candidates = []
    seen_refs  = set()
    search_terms = KAGGLE_KEYWORDS + [cls.replace("_", " ") for cls in weak_classes[:3]]

    for term in search_terms:
        params = urllib.parse.urlencode({"search": term})
        data = _kaggle_api_request(f"datasets/list?{params}", token)
        if not data or not isinstance(data, list):
            continue

        for ds in data:
            ref = ds.get("ref", "")
            total_bytes = ds.get("totalBytes", 0) or 0
            if not ref or ref in seen_refs:
                continue
            if total_bytes > 5 * 1024 ** 3:  # skip datasets > 5 GB
                continue
            seen_refs.add(ref)
            candidates.append({
                "source":      "kaggle",
                "title":       ds.get("title", ref),
                "ref":         ref,
                "url":         f"https://www.kaggle.com/datasets/{ref}",
                "size_mb":     round(total_bytes / 1e6, 1),
                "downloads":   ds.get("downloadCount", 0),
                "description": ds.get("subtitle", ""),
                "search_term": term,
            })

        if len(candidates) >= max_results * 2:
            break

    return candidates[:max_results]


def search_github(weak_classes: list[str], max_results: int = 5) -> list[dict]:
    """
    Search GitHub for STEP dataset repositories using the GitHub REST API.
    No token required for basic search (60 req/hr limit).
    """
    import urllib.request
    import urllib.parse

    candidates = []
    seen_urls  = set()
    headers_http = {
        "User-Agent": "ShiaanX-CAPP-Agent/1.0",
        "Accept": "application/vnd.github+json",
    }

    gh_token = os.environ.get("GITHUB_TOKEN", "")
    if gh_token:
        headers_http["Authorization"] = f"Bearer {gh_token}"

    queries = GITHUB_KEYWORDS + [
        urllib.parse.quote(cls.replace("_", "+") + "+STEP+machining") for cls in weak_classes[:2]
    ]

    for q in queries:
        url = f"https://api.github.com/search/repositories?q={q}+in:readme+in:description&sort=stars&per_page=5"
        try:
            req = urllib.request.Request(url, headers=headers_http)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"[search] GitHub query failed: {e}")
            continue

        for item in data.get("items", []):
            repo_url = item.get("html_url", "")
            if repo_url in seen_urls:
                continue
            seen_urls.add(repo_url)
            candidates.append({
                "source":      "github",
                "title":       item.get("full_name", ""),
                "ref":         item.get("full_name", ""),
                "url":         repo_url,
                "stars":       item.get("stargazers_count", 0),
                "description": item.get("description", ""),
                "search_term": q,
            })

        if len(candidates) >= max_results * 2:
            break

    # Sort by stars descending
    candidates.sort(key=lambda x: x.get("stars", 0), reverse=True)
    return candidates[:max_results]


def search_all(weak_classes: list[str]) -> dict:
    """Run both searches and return combined results."""
    print(f"[search] Searching for data to improve: {weak_classes}")

    kaggle_results = search_kaggle(weak_classes)
    github_results = search_github(weak_classes)

    print(f"[search] Found {len(kaggle_results)} Kaggle + {len(github_results)} GitHub candidates")
    return {
        "weak_classes":  weak_classes,
        "kaggle":        kaggle_results,
        "github":        github_results,
        "total_found":   len(kaggle_results) + len(github_results),
    }


if __name__ == "__main__":
    # Quick test
    results = search_all(["rectangular_blind_slot", "triangular_passage", "chamfer"])
    print(json.dumps(results, indent=2))
