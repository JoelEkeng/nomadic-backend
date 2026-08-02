from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.v1.router import api_router
from core.verification import VerificationRequiredError
from modules.drivers.api import router as drivers_router
from modules.kyc.api import router as kyc_router
from modules.location.api import router as location_router
from modules.matching.api import router as matching_router
from modules.payments.api import router as payments_router
from modules.rides.api import router as rides_router
from modules.students.api import router as students_router
from modules.safety.api import router as safety_router
from modules.safety.websocket import ws_router as safety_ws_router
from modules.uploads.api import router as uploads_router
from modules.users.api import router as users_router
from modules.vehicles.api import router as vehicles_router
from modules.verification.api import router as verification_router
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(CORSMiddleware,
    allow_origins=["http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"],
    expose_headers=["Content-Length"],
    max_age=600,
)

app.include_router(drivers_router)
app.include_router(kyc_router)
app.include_router(location_router)
app.include_router(matching_router)
app.include_router(payments_router)
app.include_router(rides_router)
app.include_router(students_router)
app.include_router(users_router)
app.include_router(vehicles_router)
app.include_router(verification_router)
app.include_router(safety_router)
app.include_router(safety_ws_router)
app.include_router(uploads_router)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.include_router(api_router, prefix="/api/v1")


@app.exception_handler(VerificationRequiredError)
async def handle_verification_required(
    request: Request, exc: VerificationRequiredError
) -> JSONResponse:
    """Render every verification failure as one stable 403 contract.

    The frontend keys its blocking registration modal off this body, so the
    shape must stay identical for every guarded endpoint.
    """
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content=exc.to_payload(),
    )




@app.get("/")
def read_root():
    return {"message": "Welcome to Nomadic Ride Backend"}
