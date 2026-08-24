"""
从 OpenAlex 拉取作者论文列表，并过滤预印本/仓库条目。

默认输出字段兼容现有 auto-pub-list.json 的结构：
{
  "last_updated": "...",
  "source": "OpenAlex",
  "total_count": N,
  "publications": [
    {
      "id": "...",
      "title": "...",
      "authors": ["..."],
      "venue": "...",
      "year": "2025",
      "publication_date": "2025-01-01",
      "link": "...",
      "type": "Journal|Conference|Unknown",
      "doi": "..."
    }
  ]
}
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

OPENALEX_API = "https://api.openalex.org"
CROSSREF_API = "https://api.crossref.org/works"
DEFAULT_AUTHOR_NAME = "Mingming Fan"
DEFAULT_OUTPUT_FILE = "assets/data/auto-pub-list-openalex.json"
DEFAULT_DBLP_FILE = "assets/data/auto-pub-list.json"
REQUEST_TIMEOUT = 20
PREPRINT_KEYWORDS = ("arxiv", "corr", "preprint", "biorxiv", "medrxiv", "ssrn")

# OpenAlex 偶发把材料/催化等领域同名「Mingming Fan」误挂到 HCI 作者 id，且 authorship 无单位文本；
# 用标题与 primary_topic 做兜底排除（与单位白名单互补）。
EXCLUDE_TITLE_SUBSTRINGS = (
    "high-entropy",
    "high entropy",
    "intermetallic",
    "intermetallics",
    "advanced catalysis",
)
EXCLUDE_PRIMARY_TOPIC_SUBSTRINGS = (
    "high entropy",
    "intermetallic",
    "entropy alloys",
)

# OpenAlex 常把同名作者合并到同一 author id；用「该条 authorship 上的单位/affiliation」
# 与 HCI 方向 Mingming Fan 常见单位对齐，过滤掉误挂论文（如 Energy / Fuel 上 SUFE 等）。
DEFAULT_AFFILIATION_SUBSTRINGS = (
    "hong kong university of science and technology",
    "hkust",
    "university of hong kong",
    "hku",
    "university of toronto",
    "utoronto",
)

# DBLP id 前缀到全称 venue（优先用于 2020 年前条目，避免缩写）
DBLP_VENUE_CODE_TO_FULLNAME = {
    "chi": "ACM Conference on Human Factors in Computing Systems",
    "assets": "International ACM SIGACCESS Conference on Computers and Accessibility",
    "ubicomp": "ACM International Joint Conference on Pervasive and Ubiquitous Computing (UbiComp)",
    "huc": "ACM International Joint Conference on Pervasive and Ubiquitous Computing (UbiComp)",
    "uist": "ACM Symposium on User Interface Software and Technology",
    "mm": "ACM International Conference on Multimedia",
    "vrst": "ACM Symposium on Virtual Reality Software and Technology",
    "iswc": "IEEE International Symposium on Wearable Computers",
    "hotmobile": "Workshop on Mobile Computing Systems and Applications",
    "wmcsa": "Workshop on Mobile Computing Systems and Applications",
    "www": "The Web Conference",
    "mhci": "International Conference on Human-Computer Interaction with Mobile Devices and Services",
    "cscw": "Conference on Computer Supported Cooperative Work",
    "hci": "International Conference on Human-Computer Interaction",
    "imwut": "Proceedings of the ACM on Interactive, Mobile, Wearable and Ubiquitous Technologies",
    "pacmhci": "Proceedings of the ACM on Human-Computer Interaction",
    "tochi": "ACM Transactions on Computer-Human Interaction",
    "taccess": "ACM Transactions on Accessible Computing",
    "tvcg": "IEEE Transactions on Visualization and Computer Graphics",
    "iwc": "Interacting with Computers",
    "cacm": "Communications of the ACM",
    "tiis": "ACM Transactions on Interactive Intelligent Systems",
    "iot": "Internet of Things",
    "corr": "Computing Research Repository",
    "ijhci": "International Journal of Human-Computer Interaction",
    "ijmms": "International Journal of Human-Computer Studies",
}


def request_json(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = {
        "User-Agent": "APEX-Web-publication-sync/1.0 (mailto:example@example.com)"
    }
    query = urlencode(params or {})
    full_url = f"{url}?{query}" if query else url
    req = Request(full_url, headers=headers)
    with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:  # nosec B310
        payload = resp.read().decode("utf-8")
    return json.loads(payload)


def normalize_doi(doi: str) -> str:
    if not doi:
        return ""
    doi = doi.strip()
    lower = doi.lower()
    if lower.startswith("https://doi.org/"):
        return doi[16:]
    if lower.startswith("http://doi.org/"):
        return doi[15:]
    if lower.startswith("doi.org/"):
        return doi[8:]
    return doi


def fetch_crossref_by_doi(doi: str) -> Optional[Dict[str, Any]]:
    normalized = normalize_doi(doi)
    if not normalized:
        return None
    url = f"{CROSSREF_API}/{quote(normalized, safe='')}"
    try:
        payload = request_json(url)
    except Exception:
        return None
    return payload.get("message") if isinstance(payload, dict) else None


def extract_crossref_authors(message: Dict[str, Any]) -> List[str]:
    authors = []
    for a in message.get("author", []) or []:
        name = (a.get("name") or "").strip()
        if not name:
            given = (a.get("given") or "").strip()
            family = (a.get("family") or "").strip()
            name = f"{given} {family}".strip()
        if name:
            authors.append(name)
    return authors


def extract_crossref_venue(message: Dict[str, Any]) -> str:
    container = message.get("container-title") or []
    if container and isinstance(container, list) and container[0]:
        return str(container[0]).strip()
    short_container = message.get("short-container-title") or []
    if short_container and isinstance(short_container, list) and short_container[0]:
        return str(short_container[0]).strip()
    return ""


def infer_type_from_crossref(message: Dict[str, Any]) -> str:
    # Crossref type 参考: journal-article / proceedings-article / posted-content ...
    raw_type = (message.get("type") or "").strip().lower()
    if raw_type in {"journal-article", "journal", "journal-volume", "journal-issue"}:
        return "Journal"
    if raw_type in {
        "proceedings-article",
        "proceedings",
        "book-chapter",
        "reference-entry",
    }:
        return "Conference"

    container = " ".join(message.get("container-title") or []).lower()
    if any(k in container for k in ["proceedings", "conference", "symposium", "workshop"]):
        return "Conference"
    if any(
        k in container
        for k in ["journal", "transactions", "letters", "review", "interacting with computers"]
    ):
        return "Journal"
    return "Unknown"


def print_progress(current: int, total: int, prefix: str = "") -> None:
    if total <= 0:
        return
    width = 30
    ratio = current / total
    done = int(width * ratio)
    bar = "=" * done + "." * (width - done)
    print(f"\r{prefix} [{bar}] {current}/{total} ({ratio * 100:5.1f}%)", end="", flush=True)
    if current >= total:
        print()


def backfill_from_crossref(
    publications: List[Dict[str, Any]],
    reprocess: bool = False,
) -> Dict[str, int]:
    cache: Dict[str, Optional[Dict[str, Any]]] = {}
    need_backfill = [
        pub
        for pub in publications
        if reprocess or not pub.get("backfill_processed", False)
    ]
    print(f"[INFO] Crossref backfill candidates: {len(need_backfill)}")

    stats = {
        "candidates": len(need_backfill),
        "updated_venue": 0,
        "updated_authors": 0,
        "updated_type": 0,
        "skipped_no_doi": 0,
        "not_found": 0,
        "processed": 0,
    }

    for idx, pub in enumerate(need_backfill, start=1):
        doi = normalize_doi(pub.get("doi", ""))
        if not doi:
            pub["backfill_processed"] = True
            pub["backfill_source"] = "crossref"
            pub["backfill_status"] = "skipped_no_doi"
            pub["backfill_updated_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            stats["skipped_no_doi"] += 1
            stats["processed"] += 1
            print_progress(idx, len(need_backfill), prefix="[Backfill]")
            continue
        if doi not in cache:
            cache[doi] = fetch_crossref_by_doi(doi)
        message = cache[doi]
        if not message:
            pub["backfill_processed"] = True
            pub["backfill_source"] = "crossref"
            pub["backfill_status"] = "not_found"
            pub["backfill_updated_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            stats["not_found"] += 1
            stats["processed"] += 1
            print_progress(idx, len(need_backfill), prefix="[Backfill]")
            continue

        if not (pub.get("venue") or "").strip():
            venue = extract_crossref_venue(message)
            if venue:
                pub["venue"] = venue
                stats["updated_venue"] += 1

        authors = extract_crossref_authors(message)
        if authors:
            pub["authors"] = authors
            stats["updated_authors"] += 1

        inferred_type = infer_type_from_crossref(message)
        old_type = (pub.get("type") or "Unknown").strip()
        if old_type not in {"Journal", "Conference"} and inferred_type in {"Journal", "Conference"}:
            pub["type"] = inferred_type
            stats["updated_type"] += 1

        pub["backfill_processed"] = True
        pub["backfill_source"] = "crossref"
        pub["backfill_status"] = "ok"
        pub["backfill_updated_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stats["processed"] += 1
        print_progress(idx, len(need_backfill), prefix="[Backfill]")

    return stats


def find_author_id(author_name: str) -> Optional[str]:
    data = request_json(
        f"{OPENALEX_API}/authors",
        {"search": author_name, "per-page": 10},
    )
    results = data.get("results", [])
    if not results:
        return None

    target = author_name.strip().lower()
    for author in results:
        name = (author.get("display_name") or "").strip().lower()
        if name == target:
            return author.get("id")

    return results[0].get("id")


def looks_like_preprint_or_repository(work: Dict[str, Any]) -> bool:
    work_type = (work.get("type") or "").lower()
    if work_type == "preprint":
        return True

    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    source_type = (source.get("type") or "").lower()
    source_name = (source.get("display_name") or "").lower()

    if source_type == "repository":
        return True
    return any(k in source_name for k in PREPRINT_KEYWORDS)


def looks_like_non_hci_merged_work(work: Dict[str, Any]) -> bool:
    """明显非 HCI 方向、常为同名误合并的论文。"""
    title = (work.get("display_name") or "").lower()
    if any(s in title for s in EXCLUDE_TITLE_SUBSTRINGS):
        return True
    pt = work.get("primary_topic") or {}
    ptn = (pt.get("display_name") or "").lower()
    return any(s in ptn for s in EXCLUDE_PRIMARY_TOPIC_SUBSTRINGS)


def infer_entry_type(work: Dict[str, Any]) -> str:
    source = ((work.get("primary_location") or {}).get("source") or {})
    source_type = (source.get("type") or "").lower()
    if source_type == "journal":
        return "Journal"
    if source_type == "conference":
        return "Conference"
    return "Unknown"


def _author_id_suffix(author_id: str) -> str:
    s = (author_id or "").strip().rstrip("/")
    return s.split("/")[-1] if s else ""


def _authorship_affiliation_blob(ash: Dict[str, Any]) -> str:
    parts: List[str] = []
    for inst in ash.get("institutions") or []:
        if not isinstance(inst, dict):
            continue
        n = (inst.get("display_name") or "").strip()
        if n:
            parts.append(n)
    for raw in ash.get("raw_affiliation_strings") or []:
        if isinstance(raw, str) and raw.strip():
            parts.append(raw.strip())
    return " ".join(parts).lower()


def _affiliation_blob_matches_phrases(blob: str, phrases: Tuple[str, ...]) -> bool:
    """在规范化 affiliation 文本中匹配白名单；短缩写用词边界，避免 ` the hong kong...` 与 ` hong kong...` 对不齐。"""
    blob_norm = " ".join(blob.lower().split())
    if not blob_norm:
        return False
    for raw in phrases:
        p = raw.strip().lower()
        if not p:
            continue
        if " " in p or len(p) > 6:
            if p in blob_norm:
                return True
        else:
            if re.search(
                rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", blob_norm, re.IGNORECASE
            ):
                return True
    return False


def work_authorship_matches_affiliation(
    work: Dict[str, Any],
    author_id: str,
    phrases: Tuple[str, ...],
) -> bool:
    """仅保留：该 work 里对应 author_id 的那条 authorship，其单位/affiliation 命中白名单之一。"""
    target = _author_id_suffix(author_id)
    if not target:
        return True
    for ash in work.get("authorships") or []:
        au = ash.get("author") or {}
        aid = _author_id_suffix(au.get("id") or "")
        if aid != target:
            continue
        blob = _authorship_affiliation_blob(ash)
        if not blob.strip():
            # 无单位信息时不误杀（很多 HCI 论文只有 raw string，上面已并入 blob）
            return True
        return _affiliation_blob_matches_phrases(blob, phrases)
    return True


def normalize_work(
    work: Dict[str, Any],
    author_id: str,
    affiliation_substrings: Tuple[str, ...],
    use_affiliation_filter: bool,
) -> Optional[Dict[str, Any]]:
    if looks_like_preprint_or_repository(work):
        return None

    title = (work.get("display_name") or "").strip()
    year = work.get("publication_year")
    publication_date = (work.get("publication_date") or "").strip()
    if not title or not year:
        return None

    if looks_like_non_hci_merged_work(work):
        return None

    if use_affiliation_filter and not work_authorship_matches_affiliation(
        work, author_id, affiliation_substrings
    ):
        return None

    authorships = work.get("authorships") or []
    authors = []
    for a in authorships:
        author_name = ((a.get("author") or {}).get("display_name") or "").strip()
        if author_name:
            authors.append(author_name)

    source = ((work.get("primary_location") or {}).get("source") or {})
    venue = (source.get("display_name") or "").strip()

    link = (work.get("primary_location") or {}).get("landing_page_url") or work.get("id") or ""
    doi = work.get("doi") or ""
    openalex_id = work.get("id") or ""

    return {
        "id": openalex_id,
        "title": title,
        "authors": authors,
        "venue": venue,
        "year": str(year),
        "publication_date": publication_date,
        "link": link,
        "type": infer_entry_type(work),
        "doi": doi,
    }


def fetch_all_works(author_id: str, max_items: int = 500) -> List[Dict[str, Any]]:
    works: List[Dict[str, Any]] = []
    cursor = "*"

    while True:
        params = {
            "filter": f"authorships.author.id:{author_id}",
            "per-page": 200,
            "cursor": cursor,
            "sort": "publication_year:desc",
        }
        data = request_json(f"{OPENALEX_API}/works", params)
        batch = data.get("results", [])
        works.extend(batch)

        meta = data.get("meta", {})
        next_cursor = meta.get("next_cursor")
        if not next_cursor or len(works) >= max_items:
            break
        cursor = next_cursor

    return works[:max_items]


def dedupe_publications(publications: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped = []
    for pub in publications:
        key = (pub.get("doi") or "").lower().strip()
        if not key:
            key = f'{pub.get("title", "").lower().strip()}::{pub.get("year", "").strip()}'
        if key in seen:
            continue
        seen.add(key)
        deduped.append(pub)
    return deduped


def publication_key(pub: Dict[str, Any]) -> str:
    doi_key = normalize_doi(pub.get("doi", "")).lower().strip()
    if doi_key:
        return f"doi::{doi_key}"
    openalex_id = (pub.get("id") or "").strip().lower()
    if openalex_id:
        return f"id::{openalex_id}"
    return f'ty::{pub.get("title", "").strip().lower()}::{str(pub.get("year", "")).strip()}'


def year_as_int(pub: Dict[str, Any]) -> int:
    try:
        return int(str(pub.get("year", "")).strip())
    except Exception:
        return 0


def load_existing_output(output_file: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    output_path = Path(output_file)
    if not output_path.exists():
        return [], {}
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception:
        return [], {}
    pubs = data.get("publications") or []
    if not isinstance(pubs, list):
        pubs = []
    return pubs, data


def load_dblp_publications(dblp_file: str) -> List[Dict[str, Any]]:
    path = Path(dblp_file)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    pubs = data.get("publications") or []
    if not isinstance(pubs, list):
        return []
    return pubs


def expand_dblp_venue(pub: Dict[str, Any]) -> Dict[str, Any]:
    pid = str(pub.get("id") or "")
    parts = pid.split("/")
    if len(parts) >= 2 and parts[0] in {"conf", "journals"}:
        code = parts[1].lower()
        full = DBLP_VENUE_CODE_TO_FULLNAME.get(code)
        if full:
            pub = dict(pub)
            pub["venue"] = full
    return pub


def apply_dblp_priority_before_year(
    publications: List[Dict[str, Any]],
    dblp_publications: List[Dict[str, Any]],
    cutoff_year: int,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """year < cutoff_year 的条目优先用 DBLP。"""
    kept_modern = [p for p in publications if year_as_int(p) >= cutoff_year]
    removed_early = len(publications) - len(kept_modern)

    chosen_dblp = [
        expand_dblp_venue(p) for p in dblp_publications if 0 < year_as_int(p) < cutoff_year
    ]
    merged = dedupe_publications(kept_modern + chosen_dblp)
    return merged, removed_early, len(chosen_dblp)


def enrich_titles_from_dblp(
    publications: List[Dict[str, Any]],
    dblp_publications: List[Dict[str, Any]],
) -> int:
    """若 DBLP 同 DOI 的标题更完整，则覆盖当前标题。"""
    doi_to_title: Dict[str, str] = {}
    for p in dblp_publications:
        doi = normalize_doi(p.get("link", "") if "doi.org" in str(p.get("link", "")) else p.get("doi", ""))
        if not doi:
            doi = normalize_doi(p.get("doi", ""))
        title = str(p.get("title", "")).strip()
        if doi and title:
            old = doi_to_title.get(doi, "")
            if len(title) > len(old):
                doi_to_title[doi] = title

    updated = 0
    for p in publications:
        doi = normalize_doi(p.get("doi", ""))
        if not doi:
            continue
        dblp_title = doi_to_title.get(doi, "")
        if not dblp_title:
            continue
        cur = str(p.get("title", "")).strip()
        if len(dblp_title) > len(cur) + 8:
            p["title"] = dblp_title
            updated += 1
    return updated


def merge_incremental(
    existing_pubs: List[Dict[str, Any]],
    fetched_pubs: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int]:
    merged = list(existing_pubs)
    existing_by_key = {publication_key(p): p for p in existing_pubs}
    added = 0
    for pub in fetched_pubs:
        k = publication_key(pub)
        if k in existing_by_key:
            existing_by_key[k]["publication_date"] = pub.get("publication_date", "")
            continue
        merged.append(pub)
        existing_by_key[k] = pub
        added += 1
    return merged, added


def prune_existing_not_in_kept(
    existing_pubs: List[Dict[str, Any]],
    author_work_ids: set,
    kept_ids: set,
) -> Tuple[List[Dict[str, Any]], int]:
    """从旧 JSON 里删掉：OpenAlex 仍挂在该 author 下、但本次已被过滤规则排除的 work。"""
    kept: List[Dict[str, Any]] = []
    removed = 0
    for pub in existing_pubs:
        pid = pub.get("id") or ""
        if pid in author_work_ids and pid not in kept_ids:
            removed += 1
            continue
        kept.append(pub)
    return kept, removed


def save_json(publications: List[Dict[str, Any]], output_file: str) -> None:
    output = {
        "last_updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "OpenAlex",
        "total_count": len(publications),
        "publications": publications,
    }
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch publications from OpenAlex.")
    parser.add_argument(
        "--author-name",
        default=DEFAULT_AUTHOR_NAME,
        help="Author display name for OpenAlex author search.",
    )
    parser.add_argument(
        "--author-id",
        default="",
        help="OpenAlex author id, e.g. https://openalex.org/A1234567890",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_FILE,
        help="Output JSON file path.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=500,
        help="Maximum works to fetch before filtering/dedup.",
    )
    parser.add_argument(
        "--reprocess-backfill",
        action="store_true",
        help="Reprocess backfill for all existing publications.",
    )
    parser.add_argument(
        "--no-affiliation-filter",
        action="store_true",
        help="Disable affiliation-based filtering (may include namesake papers).",
    )
    parser.add_argument(
        "--affiliation-substring",
        action="append",
        default=[],
        help="Extra affiliation substring (repeatable). Matched case-insensitively in author affiliation text.",
    )
    parser.add_argument(
        "--dblp-file",
        default=DEFAULT_DBLP_FILE,
        help="DBLP-derived JSON file used for early-year override.",
    )
    parser.add_argument(
        "--dblp-priority-before-year",
        type=int,
        default=2020,
        help="Use DBLP as primary source for publications with year < this value.",
    )
    args = parser.parse_args()

    author_id = args.author_id.strip() or find_author_id(args.author_name)
    if not author_id:
        print(f"[ERROR] Cannot find OpenAlex author for name: {args.author_name}")
        return 1

    print(f"[INFO] Using author id: {author_id}")
    works = fetch_all_works(author_id, max_items=args.max_items)
    use_affiliation = not args.no_affiliation_filter
    extra_subs = tuple(
        s.strip().lower()
        for s in (args.affiliation_substring or [])
        if s and s.strip()
    )
    affiliation_substrings = tuple(
        s.strip().lower() for s in DEFAULT_AFFILIATION_SUBSTRINGS
    ) + extra_subs

    normalized = []
    for work in works:
        item = normalize_work(
            work,
            author_id,
            affiliation_substrings,
            use_affiliation_filter=use_affiliation,
        )
        if item:
            normalized.append(item)
    normalized = dedupe_publications(normalized)

    author_work_ids = {w.get("id") for w in works if w.get("id")}
    kept_ids = {p.get("id") for p in normalized if p.get("id")}
    existing_pubs, _ = load_existing_output(args.output)
    existing_pubs, pruned = prune_existing_not_in_kept(
        existing_pubs, author_work_ids, kept_ids
    )
    if pruned:
        print(
            f"[INFO] Pruned {pruned} existing publications no longer passing fetch filters"
        )

    merged, added_count = merge_incremental(existing_pubs, normalized)
    print(
        f"[INFO] Existing: {len(existing_pubs)}, fetched: {len(normalized)}, added new: {added_count}"
    )

    backfill_stats = backfill_from_crossref(
        merged,
        reprocess=args.reprocess_backfill,
    )

    dblp_publications = load_dblp_publications(args.dblp_file)
    merged, removed_early, added_dblp = apply_dblp_priority_before_year(
        merged,
        dblp_publications,
        cutoff_year=args.dblp_priority_before_year,
    )
    title_updates = enrich_titles_from_dblp(merged, dblp_publications)
    print(
        "[INFO] Early-year override: "
        f"cutoff<{args.dblp_priority_before_year}, "
        f"removed_openalex_early={removed_early}, "
        f"added_dblp_early={added_dblp}, "
        f"title_updated_from_dblp={title_updates}"
    )

    merged.sort(
        key=lambda x: (
            int(x.get("year", "0") or 0),
            x.get("publication_date", ""),
            x.get("title", "").lower(),
        ),
        reverse=True,
    )

    save_json(merged, args.output)
    print(
        "[INFO] Backfill stats: "
        f"processed={backfill_stats['processed']}, "
        f"authors_updated={backfill_stats['updated_authors']}, "
        f"venue_updated={backfill_stats['updated_venue']}, "
        f"type_updated={backfill_stats['updated_type']}, "
        f"no_doi={backfill_stats['skipped_no_doi']}, "
        f"not_found={backfill_stats['not_found']}"
    )
    print(f"[INFO] Saved {len(merged)} publications -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
