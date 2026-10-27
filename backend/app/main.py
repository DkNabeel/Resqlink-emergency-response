from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Emergency Response API")


@app.get("/")
def home():
    return {"message": "Emergency Response API is running"}


class EmergencyRequest(BaseModel):
    message: str = Field(min_length=1)


@app.post("/emergency")
def receive_emergency(request: EmergencyRequest):
    return {
        "status": "received",
        "message": request.message
    }