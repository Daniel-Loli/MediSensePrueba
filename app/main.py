from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.webhook import router

app = FastAPI(title="MediSense AI Backend")

# CORS Config
origins = ["*"] # Ajustar en producción

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

@app.get("/")
def home():
    return {"status": "AI Backend Online (RAG Mode)"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)