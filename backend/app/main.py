import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="F1 Telemetry & Tyre Analysis API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["GET"], allow_headers=["*"])
# Lap traces are large numeric arrays; gzip shrinks them ~5x.
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.include_router(router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
