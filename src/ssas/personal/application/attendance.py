"""Attendance calculations for the employee's documented schedule."""

from datetime import datetime, time
from decimal import ROUND_HALF_UP, Decimal


def minutes_late(entry_local: datetime, scheduled_start: time) -> int:
    scheduled = entry_local.replace(
        hour=scheduled_start.hour, minute=scheduled_start.minute, second=0, microsecond=0
    )
    return max(0, int((entry_local - scheduled).total_seconds() // 60))


def worked_hours(
    entry: datetime, exit_at: datetime, break_minutes: int, scheduled_hours: Decimal
) -> tuple[Decimal, Decimal]:
    elapsed = Decimal(str((exit_at - entry).total_seconds())) / Decimal(3600)
    if elapsed <= 0 or elapsed > 24 or break_minutes < 0:
        raise ValueError("Duracion de asistencia invalida")
    worked = elapsed - Decimal(break_minutes) / Decimal(60)
    if worked < 0:
        raise ValueError("El descanso supera la jornada marcada")
    worked = worked.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    overtime = max(Decimal(0), worked - scheduled_hours).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return worked, overtime
