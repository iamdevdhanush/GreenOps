from fastapi import FastAPI

app = FastAPI(title="GreenOps API")

@app.get("/")
def root():
    return {"message": "GreenOps API running 🚀"}
