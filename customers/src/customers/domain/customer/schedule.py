from datetime import datetime, time, date
from typing import Dict, Set, Optional
from enum import Enum
from copy import deepcopy
from common.domain import BaseEntity, ValueObject
from common.util import ID, get_now

# Enum de días de la semana
class Weekday(Enum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"

# Value Objects
class Hour(ValueObject):
    open_time: time
    close_time: time
    service: str
    reservation_required: bool = False

class DailySchedule(ValueObject):
    open: bool
    hours: Set[Hour]

class ExceptionDay(ValueObject):
    date: date
    reason: str
    open: bool
    hours: Set[Hour]

class SeasonalModification(ValueObject):
    name: str
    start_date: date
    end_date: date
    modifications: Dict[Weekday, Set[Hour]]

class ServiceSchedule(ValueObject):
    description: str
    start_time: time
    end_time: time

# Schedule entity
class Schedule(BaseEntity):
    def __init__(
        self,
        id: ID,
        time_format: str,
        allow_reservations: bool,
        minimum_reservation_time: int,
        regular_schedule: Optional[Dict[Weekday, DailySchedule]] = None,
        exceptions: Optional[Set[ExceptionDay]] = None,
        seasonal_hours: Optional[Set[SeasonalModification]] = None,
        services_by_schedule: Optional[Dict[str, ServiceSchedule]] = None,
        last_updated: Optional[datetime] = None
    ):
        super().__init__(id)
        self._time_format = time_format
        self._allow_reservations = allow_reservations
        self._minimum_reservation_time = minimum_reservation_time

        # Inicializamos colecciones
        self._regular_schedule: Dict[Weekday, DailySchedule] = regular_schedule or {}
        self._exceptions: Set[ExceptionDay] = exceptions or set()
        self._seasonal_hours: Set[SeasonalModification] = seasonal_hours or set()
        self._services_by_schedule: Dict[str, ServiceSchedule] = services_by_schedule or {}

        # Fecha interna de última modificación
        self._last_updated = last_updated or get_now()

    # Properties de solo lectura con copias profundas
    @property
    def regular_schedule(self) -> Dict[Weekday, DailySchedule]:
        return deepcopy(self._regular_schedule)

    @property
    def exceptions(self) -> Set[ExceptionDay]:
        return deepcopy(self._exceptions)

    @property
    def seasonal_hours(self) -> Set[SeasonalModification]:
        return deepcopy(self._seasonal_hours)

    @property
    def services_by_schedule(self) -> Dict[str, ServiceSchedule]:
        return deepcopy(self._services_by_schedule)

    @property
    def time_format(self) -> str:
        return self._time_format

    @property
    def allow_reservations(self) -> bool:
        return self._allow_reservations

    @property
    def minimum_reservation_time(self) -> int:
        return self._minimum_reservation_time

    @property
    def last_updated(self) -> datetime:
        return self._last_updated

    # Classmethod de creación de nueva entidad (command)
    @classmethod
    def create(
        cls,
        id: ID,
        time_format: str = "24h",
        allow_reservations: bool = True,
        minimum_reservation_time: int = 30
    ) -> "Schedule":
        return cls(
            id=id,
            time_format=time_format,
            allow_reservations=allow_reservations,
            minimum_reservation_time=minimum_reservation_time
        )

    # Internal helper
    def _update_last_modified(self) -> None:
        self._last_updated = get_now()

    # Command methods
    def update_settings(
        self,
        time_format: str,
        allow_reservations: bool,
        minimum_reservation_time: int
    ) -> None:
        self._time_format = time_format
        self._allow_reservations = allow_reservations
        self._minimum_reservation_time = minimum_reservation_time
        self._update_last_modified()

    def add_daily_schedule(self, weekday: Weekday, daily_schedule: DailySchedule) -> None:
        self._regular_schedule[weekday] = daily_schedule
        self._update_last_modified()

    def remove_daily_schedule(self, weekday: Weekday) -> None:
        if weekday in self._regular_schedule:
            del self._regular_schedule[weekday]
            self._update_last_modified()

    def add_exception(self, exception: ExceptionDay) -> None:
        self._exceptions.add(exception)
        self._update_last_modified()

    def remove_exception(self, exception: ExceptionDay) -> None:
        self._exceptions.discard(exception)
        self._update_last_modified()

    def add_seasonal_modification(self, modification: SeasonalModification) -> None:
        self._seasonal_hours.add(modification)
        self._update_last_modified()

    def remove_seasonal_modification(self, modification: SeasonalModification) -> None:
        self._seasonal_hours.discard(modification)
        self._update_last_modified()

    def update_service_schedule(self, key: str, service_schedule: ServiceSchedule) -> None:
        self._services_by_schedule[key] = service_schedule
        self._update_last_modified()
