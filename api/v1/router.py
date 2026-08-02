from fastapi import APIRouter

from modules.drivers.api import router as drivers_router
from modules.kyc.api import router as kyc_router
from modules.location.api import router as location_router
from modules.matching.api import router as matching_router
from modules.payments.api import router as payments_router
from modules.rides.api import router as rides_router
from modules.safety.api import router as safety_router
from modules.safety.websocket import ws_router as safety_ws_router
from modules.students.api import router as students_router
from modules.uploads.api import router as uploads_router
from modules.users.api import router as users_router
from modules.vehicles.api import router as vehicles_router
from modules.verification.api import router as verification_router

api_router = APIRouter()
api_router.include_router(drivers_router)
api_router.include_router(kyc_router)
api_router.include_router(location_router)
api_router.include_router(matching_router)
api_router.include_router(payments_router)
api_router.include_router(rides_router)
api_router.include_router(students_router)
api_router.include_router(uploads_router)
api_router.include_router(users_router)
api_router.include_router(vehicles_router)
api_router.include_router(verification_router)
api_router.include_router(safety_router)
api_router.include_router(safety_ws_router)
