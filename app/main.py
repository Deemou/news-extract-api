import os
import hmac
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from app.routers.extract import router as extract_router

app = FastAPI()

# 1) 환경변수에서 다중 키(콤마 구분) 로드
raw = os.getenv("API_KEYS", "")
API_KEYS = [k.strip() for k in raw.split(",") if k.strip()]
if not API_KEYS:
    # 필수 키 누락 시 명확한 실패 (부팅 실패 또는 이후 401 처리 중 택1)
    # 여기서는 부팅 실패로 빠르게 이슈를 드러내도록 함
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


@app.get("/")
def root():
    return {"ok": True, "service": "news-extract-api"}


@app.get("/health")
def health():
    return {"ok": True}


# 3) 추출 라우터 전체 보호: 라우터의 모든 엔드포인트에 인증 적용
app.include_router(extract_router, dependencies=[Depends(verify_api_key)])
