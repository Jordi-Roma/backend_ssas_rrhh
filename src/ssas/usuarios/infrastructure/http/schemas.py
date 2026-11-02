from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class NuevaFichaEmpleado(BaseModel):
    codigo: str = Field(min_length=1, max_length=40)
    nombres: str = Field(min_length=1, max_length=120)
    apellido_paterno: str = Field(min_length=1, max_length=120)
    apellido_materno: str | None = Field(default=None, max_length=120)
    ci: str = Field(min_length=1, max_length=30)
    ci_expedido: str = Field(min_length=1, max_length=10)
    fecha_ingreso: date


class VinculoEmpleadoRequest(BaseModel):
    empleado_id: str | None = None
    nueva_ficha: NuevaFichaEmpleado | None = None

    @field_validator("empleado_id")
    @classmethod
    def valid_employee_id(cls, value: str | None) -> str | None:
        if value is not None:
            UUID(value)
        return value

    @model_validator(mode="after")
    def exactly_one_option(self) -> "VinculoEmpleadoRequest":
        if (self.empleado_id is None) == (self.nueva_ficha is None):
            raise ValueError("Elige una ficha existente o completa una ficha nueva")
        return self


class CrearUsuarioRequest(BaseModel):
    empresa_id: str | None = None
    nombre: str = Field(min_length=2, max_length=120)
    apellido: str = Field(min_length=1, max_length=120)
    email: EmailStr
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=12, max_length=72)
    telefono: str | None = Field(default=None, max_length=40)
    role_ids: list[str] = Field(min_length=1)
    ficha_empleado: VinculoEmpleadoRequest | None = None
    email_verificado: bool = Field(
        default=True,
        description=(
            "Marca el correo como verificado. Por omisión es verdadero porque la cuenta "
            "la crea un administrador con contraseña provisional; ponlo en falso para "
            "obligar al titular a verificar su correo antes de poder iniciar sesión."
        ),
    )


class ActualizarUsuarioRequest(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    apellido: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    username: str | None = Field(default=None, min_length=3, max_length=80)
    telefono: str | None = Field(default=None, max_length=40)
    role_ids: list[str] | None = None
    ficha_empleado: VinculoEmpleadoRequest | None = None


class ActualizarMiPerfilRequest(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    apellido: str | None = Field(default=None, min_length=1, max_length=120)
    telefono: str | None = Field(default=None, max_length=40)


class UsuarioResponse(BaseModel):
    id: str
    empresa_id: str | None
    nombre: str
    apellido: str
    email: EmailStr
    username: str
    telefono: str | None = None
    is_active: bool
    email_verified: bool
    must_change_password: bool
    failed_login_attempts: int
    locked_until: datetime | None = None
    eliminado_at: datetime | None = None
    eliminado_por_id: str | None = None
    is_deleted: bool = False
    roles: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UsuarioPageResponse(BaseModel):
    items: list[UsuarioResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class CambiarPasswordUsuarioRequest(BaseModel):
    new_password: str = Field(min_length=12, max_length=72)
    must_change: bool = True
