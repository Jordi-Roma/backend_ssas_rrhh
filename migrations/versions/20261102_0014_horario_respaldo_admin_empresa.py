"""Permite al administrador de empresa configurar su horario de respaldo.

Revision ID: 20261102_0014
Revises: 20261030_0013
"""

from alembic import op

revision = "20261102_0014"
down_revision = "20261030_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO permiso (codigo, modulo, recurso, operacion, descripcion) "
        "VALUES ('backup:configurar', 'BACKUP', 'backup', 'configurar', "
        "'Configurar la hora del respaldo de la propia empresa') "
        "ON CONFLICT (codigo) DO NOTHING"
    )
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) "
        "SELECT r.id, p.id FROM rol r CROSS JOIN permiso p "
        "WHERE r.codigo = 'ADMIN_EMPRESA' AND r.empresa_id IS NOT NULL "
        "AND p.codigo = 'backup:configurar' ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM rol_permiso WHERE permiso_id IN "
        "(SELECT id FROM permiso WHERE codigo = 'backup:configurar')"
    )
    op.execute("DELETE FROM permiso WHERE codigo = 'backup:configurar'")
