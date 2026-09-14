"""Repara el rol RECLUTADOR y elimina permisos huerfanos.

Las empresas aprovisionadas antes de la correccion de ``provision_empresa`` recibieron
un rol RECLUTADOR con dos codigos que nunca existieron en el catalogo
(``vacantes:gestionar`` y ``candidatos:gestionar``). El filtro que arma los permisos
del rol los descartaba en silencio, asi que el rol quedo con cero permisos utiles y
el actor principal del reclutamiento no podia invocar ningun endpoint.

Esta migracion:
1. Asigna a todo rol RECLUTADOR existente los ocho permisos reales de reclutamiento.
2. Borra los dos permisos huerfanos, que ningun endpoint exige.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0014"
down_revision: str | None = "20260908_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISOS_RECLUTADOR = (
    "vacantes:ver",
    "vacantes:crear",
    "vacantes:editar",
    "vacantes:publicar",
    "habilidades:ver",
    "postulantes:ver",
    "postulaciones:ver",
    "postulaciones:gestionar",
)

# (codigo, modulo, recurso, operacion, descripcion) de los permisos que se eliminan.
PERMISOS_HUERFANOS = (
    ("vacantes:gestionar", "reclutamiento", "vacantes", "gestionar", "Codigo obsoleto"),
    ("candidatos:gestionar", "reclutamiento", "candidatos", "gestionar", "Codigo obsoleto"),
)


def _lista(codigos) -> str:
    return ", ".join(f"'{codigo}'" for codigo in codigos)


def upgrade() -> None:
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) "
        "SELECT r.id, p.id FROM rol r CROSS JOIN permiso p "
        "WHERE r.empresa_id IS NOT NULL AND r.codigo = 'RECLUTADOR' "
        f"AND p.codigo IN ({_lista(PERMISOS_RECLUTADOR)}) "
        "ON CONFLICT DO NOTHING"
    )

    huerfanos = _lista(codigo for codigo, *_ in PERMISOS_HUERFANOS)
    op.execute(
        "DELETE FROM rol_permiso WHERE permiso_id IN "
        f"(SELECT id FROM permiso WHERE codigo IN ({huerfanos}))"
    )
    op.execute(f"DELETE FROM permiso WHERE codigo IN ({huerfanos})")


def downgrade() -> None:
    for codigo, modulo, recurso, operacion, descripcion in PERMISOS_HUERFANOS:
        op.execute(
            "INSERT INTO permiso (codigo, modulo, recurso, operacion, descripcion) "
            f"VALUES ('{codigo}', '{modulo}', '{recurso}', '{operacion}', '{descripcion}') "
            "ON CONFLICT DO NOTHING"
        )
    op.execute(
        "DELETE FROM rol_permiso WHERE rol_id IN "
        "(SELECT id FROM rol WHERE empresa_id IS NOT NULL AND codigo = 'RECLUTADOR') "
        f"AND permiso_id IN (SELECT id FROM permiso WHERE codigo IN ({_lista(PERMISOS_RECLUTADOR)}))"
    )
