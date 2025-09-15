from datetime import datetime, time, date

from common.mediator import Mediator, Command, CommandHadler
from common.ioc import component, inject, deps
from common.openapi import FeatureModel
from common.server import build_router,EMPTY
from common.security import Principal, authorize
from common.util import get_id
from customers.domain.customer.schedule import Schedule


router = build_router("schedules")


class Request(Command):
    time_format: str = "24h"
    allow_reservations: bool = True
    minimum_reservation_time: int = 30


class HourResponse(FeatureModel):
    open_time: str
    close_time: str
    service: str
    reservation_required: bool = False


class DailyScheduleResponse(FeatureModel):
    open: bool
    hours: list[HourResponse]


class ExceptionDayResponse(FeatureModel):
    date: date
    reason: str
    open: bool
    hours: list[HourResponse]


class SeasonalModificationResponse(FeatureModel):
    name: str
    start_date: date
    end_date: date
    modifications: dict[str, DailyScheduleResponse]  # claves = weekday en minúsculas


class ServiceScheduleResponse(FeatureModel):
    description: str
    start_time: str
    end_time: str    


class Response(FeatureModel):
    time_format: str
    allow_reservations: bool
    minimum_reservation_time: int
    last_updated: datetime
    
    regular_schedule: dict[str, DailyScheduleResponse]
    exceptions: list[ExceptionDayResponse]
    seasonal_hours: list[SeasonalModificationResponse]
    services_by_schedule: dict[str, ServiceScheduleResponse]




@component
class Service(CommandHadler[Request]):
    @inject
    async def handler(
        self, command: Request, principal: Principal = deps(Principal)
    ) -> Response:
        
        schedule = Schedule.create(
            get_id(),
            command.time_format,
            command.allow_reservations,
            command.minimum_reservation_time,
        )        
        return EMPTY


@router.post("", summary="create schedule", status_code=201)
@authorize(["admin"])
@inject
async def controller(request: Request, mediator: Mediator = deps(Mediator)) -> Response:
    return await mediator.send(request)
