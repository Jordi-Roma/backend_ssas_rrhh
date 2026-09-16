from datetime import datetime

from pydantic import BaseModel, Field


class RespaldoSchema(BaseModel):
    id: str
    nombre: str
    formato: str
    tamano_bytes: int | None
    sha256: str | None
    estado: str
    creado_por_id: str
    fecha_creacion: datetime
    fecha_finalizacion: datetime | None
    fecha_restauracion: datetime | None
    restaurado_por_id: str | None
    mensaje_error: str | None

    model_config = {"from_attributes": True}


class CrearRespaldoSchema(BaseModel):
    nombre: str | None = Field(default=None, max_length=180)


class RestaurarRespaldoSchema(BaseModel):
    confirmacion: str = Field(min_length=1, max_length=100)


class OperacionRespaldoSchema(BaseModel):
    id: str
    estado: str
    mensaje: str
