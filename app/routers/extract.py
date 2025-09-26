from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl
import httpx
from trafilatura import extract, extract_metadata  # 핵심 API만 임포트

router = APIRouter(prefix="/v1", tags=["extract"])


class ExtractIn(BaseModel):
    url: HttpUrl


class ExtractOut(BaseModel):
    title: str | None = None
    text: str
    lang: str | None = None
    source: str


@router.post("/extract", response_model=ExtractOut)
async def extract_endpoint(payload: ExtractIn):
    try:
        async with httpx.AsyncClient(
            timeout=15, headers={"User-Agent": "news-extract-api/1.0"}
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

    # 본문 + 메타데이터 추출
    text = extract(
        html,
        include_comments=False,
        include_tables=False,
        fast=True,
        with_metadata=True,
    )  # fast는 no_fallback 대체
    if not text:
        # 폴백 전략: 관대한 추출로 한 번 더 시도하거나 422로 반환
        text = extract(html, fast=False, with_metadata=True)  # fallbacks 허용
        if not text:
            raise HTTPException(status_code=422, detail="no content extracted")

    # 메타데이터를 별도로 뽑아 제목/언어 강화
    meta_doc = extract_metadata(
        html, default_url=str(payload.url)
    )  # 필요 시 date_config 등 옵션 추가
    title = getattr(meta_doc, "title", None) if meta_doc else None
    lang = getattr(meta_doc, "lang", None) if meta_doc else None

    return {"title": title, "text": text, "lang": lang, "source": str(payload.url)}
