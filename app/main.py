import os
import hmac
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from dotenv import load_dotenv

# 전역 리밋(만일의 사태 대비)용
from redis.asyncio import from_url
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

from app.routers.extract import router as extract_router

load_dotenv()

# 1) 환경변수에서 다중 키(콤마 구분) 로드
raw = os.getenv("API_KEYS", "")
API_KEYS = [k.strip() for k in raw.split(",") if k.strip()]
if not API_KEYS:
    # 필수 키 누락 시 명확한 실패(부팅 실패로 빠르게 드러냄)
    raise RuntimeError("API_KEYS is required but missing")

# 2) 헤더 기반 API 키 인증 (X-API-Key)
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(x_api_key: str | None = Depends(API_KEY_HEADER)):
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
        )
    # 상수시간 비교로 안전한 비교
    for k in API_KEYS:
        if hmac.compare_digest(x_api_key, k):
            return True
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


# 2.5) 전역 얇은 리밋(만일의 사태 대비) 설정값 — 60초 동안 최대 50회가 기본
GLOBAL_LIMIT_TIMES = int(os.getenv("GLOBAL_LIMIT_TIMES", "50"))  # 허용 횟수
GLOBAL_LIMIT_SECONDS = int(os.getenv("GLOBAL_LIMIT_SECONDS", "60"))  # 윈도우(초)


# 3) Lifespan으로 Redis/리미터 초기화(권장 방식)
@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_url = os.getenv("REDIS_URL")
    redis = from_url(redis_url, encoding="utf-8", decode_responses=True)
    await FastAPILimiter.init(redis)  # 전역 리미터 초기화
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
def root():
    return {"ok": True, "service": "news-extract-api"}


@app.get("/health")
def health():
    return {"ok": True}


# 4) 추출 라우터 전체 보호: 인증 + 전역 얇은 리밋
app.include_router(
    extract_router,
    dependencies=[
        Depends(verify_api_key),
        Depends(RateLimiter(times=GLOBAL_LIMIT_TIMES, seconds=GLOBAL_LIMIT_SECONDS)),
    ],
)
