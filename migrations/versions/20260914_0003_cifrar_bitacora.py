"""cifrar detalles y encadenar integridad de bitacora

Revision ID: 20260914_0003
Revises: 20260914_0002
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from ssas.bitacora.infrastructure.crypto import AuditCipher, record_hash
from ssas.config.settings import settings

revision: str = "20260914_0003"
down_revision: str | None = "20260914_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _metadata(row) -> dict:
    return {
        "id": str(row.id),
        "empresa_id": str(row.empresa_id) if row.empresa_id else None,
        "usuario_id": str(row.usuario_id) if row.usuario_id else None,
        "modulo": row.modulo,
        "accion": row.accion,
        "nivel": row.nivel,
        "tabla_afectada": row.tabla_afectada,
        "registro_id": str(row.registro_id) if row.registro_id else None,
        "fecha": row.fecha.isoformat(),
    }


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_bitacora_inmutable ON bitacora")
    op.drop_constraint("bitacora_empresa_id_fkey", "bitacora", type_="foreignkey")
    op.drop_constraint("bitacora_usuario_id_fkey", "bitacora", type_="foreignkey")
    op.create_foreign_key(
        "bitacora_empresa_id_fkey",
        "bitacora",
        "empresa",
        ["empresa_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "bitacora_usuario_id_fkey",
        "bitacora",
        "usuario",
        ["usuario_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column("bitacora", sa.Column("datos_cifrados", sa.LargeBinary(), nullable=True))
    op.add_column("bitacora", sa.Column("nonce_cifrado", sa.LargeBinary(12), nullable=True))
    op.add_column(
        "bitacora",
        sa.Column("version_cifrado", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("bitacora", sa.Column("hash_anterior", sa.String(64), nullable=True))
    op.add_column("bitacora", sa.Column("hash_registro", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_bitacora_hash_registro", "bitacora", ["hash_registro"])

    if not context.is_offline_mode():
        cipher = AuditCipher(settings.app_audit_encryption_key)
        connection = op.get_bind()
        rows = connection.execute(
            sa.text(
                "SELECT id, empresa_id, usuario_id, actor_etiqueta, modulo, accion, nivel, "
                "descripcion, tabla_afectada, registro_id, datos_previos, datos_nuevos, "
                "ip_origen, user_agent, fecha FROM bitacora "
                "ORDER BY empresa_id NULLS FIRST, fecha, id"
            )
        ).fetchall()
        previous_by_scope: dict[str, str | None] = {}
        for raw in rows:
            row = raw._mapping
            scope = str(row.empresa_id) if row.empresa_id else "PLATFORM"
            previous = previous_by_scope.get(scope)
            payload = {
                "actor_label": row.actor_etiqueta,
                "description": row.descripcion,
                "previous_data": row.datos_previos,
                "new_data": row.datos_nuevos,
                "source_ip": str(row.ip_origen) if row.ip_origen else None,
                "user_agent": row.user_agent,
            }
            metadata = _metadata(row)
            ciphertext, nonce = cipher.encrypt(payload, metadata)
            current = record_hash(previous, metadata, nonce, ciphertext)
            connection.execute(
                sa.text(
                    "UPDATE bitacora SET actor_etiqueta=NULL, descripcion='[CIFRADO]', "
                    "datos_previos=NULL, datos_nuevos=NULL, ip_origen=NULL, user_agent=NULL, "
                    "datos_cifrados=:ciphertext, nonce_cifrado=:nonce, version_cifrado=1, "
                    "hash_anterior=:previous, hash_registro=:current WHERE id=:id"
                ),
                {
                    "ciphertext": ciphertext,
                    "nonce": nonce,
                    "previous": previous,
                    "current": current,
                    "id": row.id,
                },
            )
            previous_by_scope[scope] = current
        op.alter_column("bitacora", "datos_cifrados", nullable=False)
        op.alter_column("bitacora", "nonce_cifrado", nullable=False)
        op.alter_column("bitacora", "hash_registro", nullable=False)

    op.execute(
        "CREATE TRIGGER trg_bitacora_inmutable BEFORE UPDATE OR DELETE ON bitacora "
        "FOR EACH ROW EXECUTE FUNCTION proteger_bitacora()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_bitacora_inmutable ON bitacora")
    if not context.is_offline_mode():
        cipher = AuditCipher(settings.app_audit_encryption_key)
        connection = op.get_bind()
        rows = connection.execute(
            sa.text(
                "SELECT id, empresa_id, usuario_id, modulo, accion, nivel, tabla_afectada, "
                "registro_id, fecha, datos_cifrados, nonce_cifrado FROM bitacora"
            )
        ).fetchall()
        for raw in rows:
            row = raw._mapping
            payload = cipher.decrypt(row.datos_cifrados, row.nonce_cifrado, _metadata(row))
            connection.execute(
                sa.text(
                    "UPDATE bitacora SET actor_etiqueta=:actor, descripcion=:description, "
                    "datos_previos=CAST(:previous AS jsonb), datos_nuevos=CAST(:new AS jsonb), "
                    "ip_origen=CAST(:ip AS inet), user_agent=:agent WHERE id=:id"
                ),
                {
                    "actor": payload.get("actor_label"),
                    "description": payload.get("description") or "",
                    "previous": json.dumps(payload["previous_data"]) if payload.get("previous_data") is not None else None,
                    "new": json.dumps(payload["new_data"]) if payload.get("new_data") is not None else None,
                    "ip": payload.get("source_ip"),
                    "agent": payload.get("user_agent"),
                    "id": row.id,
                },
            )
    op.drop_constraint("uq_bitacora_hash_registro", "bitacora", type_="unique")
    op.drop_column("bitacora", "hash_registro")
    op.drop_column("bitacora", "hash_anterior")
    op.drop_column("bitacora", "version_cifrado")
    op.drop_column("bitacora", "nonce_cifrado")
    op.drop_column("bitacora", "datos_cifrados")
    op.drop_constraint("bitacora_usuario_id_fkey", "bitacora", type_="foreignkey")
    op.drop_constraint("bitacora_empresa_id_fkey", "bitacora", type_="foreignkey")
    op.create_foreign_key(
        "bitacora_empresa_id_fkey",
        "bitacora",
        "empresa",
        ["empresa_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "bitacora_usuario_id_fkey",
        "bitacora",
        "usuario",
        ["usuario_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "CREATE TRIGGER trg_bitacora_inmutable BEFORE UPDATE OR DELETE ON bitacora "
        "FOR EACH ROW EXECUTE FUNCTION proteger_bitacora()"
    )
