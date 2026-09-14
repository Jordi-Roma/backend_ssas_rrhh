"""Normaliza permiso.modulo contra el catalogo de modulos.

Cuatro permisos de empresa quedaron registrados con modulos que no existen en la
tabla ``modulo`` (``seguridad`` y ``configuracion``). La consecuencia es que
``GET /api/v1/permisos`` los omite para cualquier empresa, porque filtra por los
codigos del catalogo, y por tanto no se pueden asignar a un rol desde la interfaz:

    bitacora:ver        seguridad     -> BITACORA
    roles:gestionar     seguridad     -> ROLES
    usuarios:crear      seguridad     -> USUARIOS
    usuarios:editar     seguridad     -> USUARIOS
    parametros:ver      configuracion -> EMPRESAS
    parametros:editar   configuracion -> EMPRESAS

Es un cambio de metadatos: no altera que un rol tenga o no el permiso, solo bajo
que modulo se agrupa y, con ello, su visibilidad en el catalogo y el filtrado por
modulo habilitado.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0013"
down_revision: str | None = "20260908_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# codigo de permiso -> (modulo correcto, modulo anterior)
REASIGNACIONES = [
    ("bitacora:ver", "BITACORA", "seguridad"),
    ("roles:gestionar", "ROLES", "seguridad"),
    ("usuarios:crear", "USUARIOS", "seguridad"),
    ("usuarios:editar", "USUARIOS", "seguridad"),
    ("parametros:ver", "EMPRESAS", "configuracion"),
    ("parametros:editar", "EMPRESAS", "configuracion"),
]


def upgrade() -> None:
    for codigo, modulo_nuevo, _ in REASIGNACIONES:
        op.execute(
            f"UPDATE permiso SET modulo = '{modulo_nuevo}', updated_at = now() "
            f"WHERE codigo = '{codigo}'"
        )


def downgrade() -> None:
    for codigo, _, modulo_anterior in REASIGNACIONES:
        op.execute(
            f"UPDATE permiso SET modulo = '{modulo_anterior}', updated_at = now() "
            f"WHERE codigo = '{codigo}'"
        )
