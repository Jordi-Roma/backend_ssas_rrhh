from pydantic import BaseModel, ConfigDict, Field


class CreateRoleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    codigo: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_]+$")
    description: str | None = Field(default=None, max_length=255)


class UpdateRoleRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class AssignPermissionsRequest(BaseModel):
    permission_ids: list[str] = Field(default_factory=list)


class PermissionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    resource: str
    action: str
    description: str | None = None


class RoleSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    empresa_id: str | None
    name: str
    codigo: str
    description: str | None = None
    es_base: bool
    is_active: bool
    permissions: list[PermissionSchema] = Field(default_factory=list)
