from fastapi import FastAPI
from app.routers.extract import router as extract_router

app = FastAPI()
app.include_router(extract_router)


@app.get("/")
def root():
    return {"ok": True, "service": "news-extract-api"}


@app.get("/health")
def health():
    return {"ok": True}
