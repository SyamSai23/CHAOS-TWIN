from fastapi import FastAPI

app = FastAPI(title="Chaos Twin API")

@app.get("/health")
def health():
    return {"status": "ok"}