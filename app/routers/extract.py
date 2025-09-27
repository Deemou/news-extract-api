from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, HttpUrl
import httpx
import re
import yaml
from trafilatura import extract, extract_metadata

router = APIRouter(prefix="/v1", tags=["extract"])


class ExtractIn(BaseModel):
    url: HttpUrl


class ExtractOut(BaseModel):
    title: str | None = None
    text: str
    meta: dict


# --- 유틸 ---


def normalize_newlines(text: str) -> str:
    # 개행/탭 정규화: CRLF/CR -> LF, 탭 -> 공백
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")


def strip_and_parse_front_matter(text: str) -> tuple[str, dict]:
    # 선두 YAML 프런트매터를 메타로 파싱해 반환(본문에서는 제거)
    if text.startswith("---"):
        parts = text.split("\n---\n", 1)
        if len(parts) == 2:
            fm_block = parts[0].lstrip("-\n")
            try:
                fm = yaml.safe_load(fm_block) or {}
            except Exception:
                fm = {}
            return parts[1], fm
    return text, {}


# 매우 보수적 라인 제거 패턴(라인 전체 매칭만)
SAFE_NOISE_PATTERNS = [
    r"^\s*무단\s*전재\s*[·,]?\s*재배포\s*금지\s*\.?\s*$",
    r"^\s*All\s+rights\s+reserved\.?\s*$",
    r"^\s*Copyright\b[^\n]{0,200}All\s+rights\s+reserved\.?\s*$",
    r"^\s*(문의|Contact)\s*[:]\s*\S+@\S+\s*$",
    r"^\s*[A-Za-z가-힣]+(?:\s+[A-Za-z가-힣]+)*\s*기자\s*[:]?\s*\S+@\S+\s*$",
    r"^\s*제보\s*[:]\s*\S+@\S+\s*$",
    r"^\s*\S+@\S+\s*$",  # 이메일만 있는 단독 라인
    r"^\s*\[?\s*\S+@\S+\s*\]?\s*\(\s*mailto\s*:\s*\S+@\S+\s*\)\s*$",  # [email](mailto:email)
    r"^\s*.+?\s+\[?\s*\S+@\S+\s*\]?\s*\(\s*mailto\s*:\s*\S+@\S+\s*\)\s*$",  # 브랜드 + mailto
    r"^\s*[\w\-\.\u3131-\u318E\uAC00-\uD7A3 ]+\s+\S+@\S+\s*$",  # 브랜드 + 이메일(평문)
]
SAFE_REGEXES = [re.compile(p, re.IGNORECASE) for p in SAFE_NOISE_PATTERNS]


def remove_noise_lines_safe_only(text: str) -> str:
    text = normalize_newlines(text)
    cleaned_lines = []
    for raw in text.splitlines():
        line = raw.rstrip()
        # 초장문 라인은 정규식 판단에서 제외(성능 안정)
        if len(line) > 5000:
            cleaned_lines.append(line)
            continue
        if any(rx.match(line) for rx in SAFE_REGEXES):
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    # 과도한 빈 줄 축소
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def collapse_newlines_to_spaces(s: str) -> str:
    # 여러 줄바꿈/공백을 단일 공백으로 축소(표시/전송용)
    s = re.sub(r"\s*\n\s*", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


@router.post("/extract", response_model=ExtractOut)
async def extract_endpoint(
    payload: ExtractIn,
    trim_newlines: bool = Query(
        False, description="True면 줄바꿈을 공백으로 치환해 반환"
    ),
):
    # 1) 다운로드
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=10.0, connect=5.0, read=8.0, write=8.0, pool=5.0
            ),
            headers={"User-Agent": "news-extract-api/1.0"},
        ) as client:
            resp = await client.get(str(payload.url))
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="upstream error")
    except httpx.RequestError:
        raise HTTPException(
            status_code=504, detail="timeout or connection error to source"
        )

    # 2) 본문 추출
    text = extract(
        html,
        include_comments=False,
        include_tables=False,
        fast=True,
        with_metadata=True,
    )
    if not text:
        text = extract(html, fast=False, with_metadata=True)
        if not text:
            raise HTTPException(status_code=422, detail="no content extracted")

    # 3) 프런트매터 제거 및 메타 보강용 파싱
    text, fm = strip_and_parse_front_matter(text)

    # 4) 매우 보수적 라인 소거(절단 없음)
    text = remove_noise_lines_safe_only(text)

    # 5) 줄바꿈 정책: 기본 유지(모델 입력 품질), 옵션으로 공백 치환
    final_text = collapse_newlines_to_spaces(text) if trim_newlines else text

    # 6) HTML 메타 추출(OG/구조화 데이터 기반)
    meta_doc = extract_metadata(html, default_url=str(payload.url))
    md = meta_doc.as_dict() if meta_doc and hasattr(meta_doc, "as_dict") else {}

    title = md.get("title")
    published_at = md.get("date") or fm.get("date") or fm.get("published_at")
    site = md.get("sitename") or fm.get("site") or md.get("hostname")

    # 7) 최종 응답
    return {
        "title": title,
        "text": final_text,
        "meta": {
            "source": str(payload.url),
            "published_at": published_at,
            "site": site,
        },
    }
