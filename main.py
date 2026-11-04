from fastapi import FastAPI

app = FastAPI(title="Study API")


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Hello FastAPI"}
