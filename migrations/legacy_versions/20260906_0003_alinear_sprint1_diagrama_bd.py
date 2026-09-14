"""alinear sprint1 al diagrama bd

Revision ID: 20260906_0003
Revises: 0d142a1a7539
Create Date: 2026-09-06 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0003"
down_revision: str | None = "0d142a1a7539"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename_trigger_if_exists(table: str, old_name: str, new_name: str) -> None:
    """Renombra un trigger porque PostgreSQL no admite ALTER TRIGGER IF EXISTS."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgname = '{old_name}'
                  AND tgrelid = '{table}'::regclass
                  AND NOT tgisinternal
            ) THEN
                ALTER TRIGGER {old_name} ON {table} RENAME TO {new_name};
            END IF;
        END
        $$
        """
    )


def upgrade() -> None:
    op.add_column(
        "departamento",
        sa.Column("departamento_padre_id", sa.UUID(as_uuid=False), nullable=True),
    )
    op.add_column(
        "departamento",
        sa.Column("responsable_id", sa.UUID(as_uuid=False), nullable=True),
    )
    op.create_foreign_key(
        "fk_departamento_departamento_padre_id_departamento",
        "departamento",
        "departamento",
        ["departamento_padre_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_departamento_responsable_id_usuario",
        "departamento",
        "usuario",
        ["responsable_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_departamento_padre_id",
        "departamento",
        ["departamento_padre_id"],
        unique=False,
    )
    op.create_index(
        "idx_departamento_responsable_id",
        "departamento",
        ["responsable_id"],
        unique=False,
    )

    op.add_column("cargo", sa.Column("nivel", sa.String(length=80), nullable=True))
    op.add_column("cargo", sa.Column("salario_min", sa.Numeric(12, 2), nullable=True))
    op.add_column("cargo", sa.Column("salario_max", sa.Numeric(12, 2), nullable=True))
    op.create_check_constraint(
        "ck_cargo_salario_min_no_negativo",
        "cargo",
        "salario_min IS NULL OR salario_min >= 0",
    )
    op.create_check_constraint(
        "ck_cargo_salario_max_no_negativo",
        "cargo",
        "salario_max IS NULL OR salario_max >= 0",
    )
    op.create_check_constraint(
        "ck_cargo_rango_salario",
        "cargo",
        "salario_min IS NULL OR salario_max IS NULL OR salario_max >= salario_min",
    )

    op.add_column("habilidad", sa.Column("categoria", sa.String(length=120), nullable=True))

    op.add_column(
        "vacante",
        sa.Column(
            "fecha_registro",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.add_column(
        "vacante_habilidad",
        sa.Column(
            "id",
            sa.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=True,
        ),
    )
    op.alter_column("vacante_habilidad", "id", nullable=False)
    op.drop_constraint("vacante_habilidad_pkey", "vacante_habilidad", type_="primary")
    op.create_primary_key("pk_vacante_habilidad", "vacante_habilidad", ["id"])
    op.create_unique_constraint(
        "uq_vacante_habilidad_pair",
        "vacante_habilidad",
        ["vacante_id", "habilidad_id"],
    )

    op.rename_table("etapa_postulacion", "etapa_reclutamiento")
    _rename_trigger_if_exists(
        "etapa_reclutamiento",
        "trg_etapa_postulacion_updated_at",
        "trg_etapa_reclutamiento_updated_at",
    )
    op.drop_constraint(
        "uq_etapa_postulacion_codigo",
        "etapa_reclutamiento",
        type_="unique",
    )
    op.drop_constraint("uq_etapa_postulacion_orden", "etapa_reclutamiento", type_="unique")
    op.drop_constraint(
        "ck_etapa_postulacion_orden_positivo",
        "etapa_reclutamiento",
        type_="check",
    )
    op.add_column(
        "etapa_reclutamiento",
        sa.Column("empresa_id", sa.UUID(as_uuid=False), nullable=True),
    )
    op.add_column("etapa_reclutamiento", sa.Column("color", sa.String(30), nullable=True))
    op.add_column(
        "etapa_reclutamiento",
        sa.Column("es_inicial", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "etapa_reclutamiento",
        sa.Column("es_contratado", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "etapa_reclutamiento",
        sa.Column("es_rechazado", sa.Boolean(), server_default="false", nullable=False),
    )
    op.execute(
        """
        UPDATE etapa_reclutamiento
        SET
            nombre = CASE codigo
                WHEN 'POSTULADO' THEN 'Postulado'
                WHEN 'PRESELECCIONADO' THEN 'Preseleccionado'
                WHEN 'ENTREVISTA' THEN 'Entrevista'
                WHEN 'OFERTA' THEN 'Oferta'
                WHEN 'CONTRATADO' THEN 'Contratado'
                WHEN 'DESCARTADO' THEN 'Descartado'
                ELSE nombre
            END,
            color = CASE codigo
                WHEN 'POSTULADO' THEN '#64748b'
                WHEN 'PRESELECCIONADO' THEN '#2563eb'
                WHEN 'ENTREVISTA' THEN '#7c3aed'
                WHEN 'OFERTA' THEN '#f59e0b'
                WHEN 'CONTRATADO' THEN '#16a34a'
                WHEN 'DESCARTADO' THEN '#dc2626'
                ELSE color
            END,
            es_inicial = codigo = 'POSTULADO',
            es_contratado = codigo = 'CONTRATADO',
            es_rechazado = codigo = 'DESCARTADO'
        """
    )
    op.execute(
        """
        UPDATE etapa_reclutamiento
        SET empresa_id = (
            SELECT id
            FROM empresa
            ORDER BY fecha_registro NULLS LAST, id
            LIMIT 1
        )
        WHERE empresa_id IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO etapa_reclutamiento (
            empresa_id, nombre, orden, color, es_inicial, es_contratado, es_rechazado
        )
        SELECT e.id, base.nombre, base.orden, base.color,
               base.es_inicial, base.es_contratado, base.es_rechazado
        FROM empresa e
        CROSS JOIN (
            VALUES
                ('Postulado', 1, '#64748b', true, false, false),
                ('Preseleccionado', 2, '#2563eb', false, false, false),
                ('Entrevista', 3, '#7c3aed', false, false, false),
                ('Oferta', 4, '#f59e0b', false, false, false),
                ('Contratado', 5, '#16a34a', false, true, false),
                ('Descartado', 6, '#dc2626', false, false, true)
        ) AS base(nombre, orden, color, es_inicial, es_contratado, es_rechazado)
        WHERE NOT EXISTS (
            SELECT 1
            FROM etapa_reclutamiento er
            WHERE er.empresa_id = e.id AND er.orden = base.orden
        )
        """
    )
    op.alter_column("etapa_reclutamiento", "empresa_id", nullable=False)
    op.create_foreign_key(
        "fk_etapa_reclutamiento_empresa_id_empresa",
        "etapa_reclutamiento",
        "empresa",
        ["empresa_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_etapa_reclutamiento_orden_positivo",
        "etapa_reclutamiento",
        "orden > 0",
    )
    op.create_unique_constraint(
        "uq_etapa_reclutamiento_empresa_nombre",
        "etapa_reclutamiento",
        ["empresa_id", "nombre"],
    )
    op.create_unique_constraint(
        "uq_etapa_reclutamiento_empresa_orden",
        "etapa_reclutamiento",
        ["empresa_id", "orden"],
    )
    op.create_index(
        "idx_etapa_reclutamiento_empresa_id",
        "etapa_reclutamiento",
        ["empresa_id"],
        unique=False,
    )
    op.drop_column("etapa_reclutamiento", "codigo")

    op.create_table(
        "motivo_rechazo",
        sa.Column(
            "id",
            sa.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("empresa_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresa.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "nombre", name="uq_motivo_rechazo_empresa_nombre"),
    )
    op.create_index("idx_motivo_rechazo_empresa_id", "motivo_rechazo", ["empresa_id"])
    op.execute(
        "CREATE TRIGGER trg_motivo_rechazo_updated_at BEFORE UPDATE ON motivo_rechazo "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    op.add_column("postulante", sa.Column("empresa_id", sa.UUID(as_uuid=False), nullable=True))
    op.add_column("postulante", sa.Column("direccion", sa.Text(), nullable=True))
    op.add_column("postulante", sa.Column("cv_texto", sa.Text(), nullable=True))
    op.add_column(
        "postulante",
        sa.Column("en_banco_talento", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "postulante",
        sa.Column(
            "fecha_registro",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE postulante p
        SET empresa_id = v.empresa_id
        FROM postulacion po
        JOIN vacante v ON v.id = po.vacante_id
        WHERE po.postulante_id = p.id AND p.empresa_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE postulante
        SET empresa_id = (
            SELECT id
            FROM empresa
            ORDER BY fecha_registro NULLS LAST, id
            LIMIT 1
        )
        WHERE empresa_id IS NULL
        """
    )
    op.alter_column("postulante", "empresa_id", nullable=False)
    op.create_foreign_key(
        "fk_postulante_empresa_id_empresa",
        "postulante",
        "empresa",
        ["empresa_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_postulante_ci", "postulante", type_="unique")
    op.drop_index("uq_postulante_ci_ci", table_name="postulante")
    op.create_unique_constraint(
        "uq_postulante_empresa_ci",
        "postulante",
        ["empresa_id", "ci"],
    )
    op.create_index("idx_postulante_empresa_id", "postulante", ["empresa_id"])
    op.create_index(
        "uq_postulante_empresa_ci_ci",
        "postulante",
        ["empresa_id", sa.literal_column("lower(ci)")],
        unique=True,
    )

    op.add_column(
        "postulacion",
        sa.Column("motivo_rechazo_id", sa.UUID(as_uuid=False), nullable=True),
    )
    op.add_column("postulacion", sa.Column("empleado_id", sa.UUID(as_uuid=False), nullable=True))
    op.add_column("postulacion", sa.Column("puntaje_ia", sa.Numeric(5, 2), nullable=True))
    op.add_column(
        "postulacion",
        sa.Column(
            "fecha_postulacion",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "postulacion",
        sa.Column(
            "fecha_ultimo_cambio",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_postulacion_motivo_rechazo_id_motivo_rechazo",
        "postulacion",
        "motivo_rechazo",
        ["motivo_rechazo_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_postulacion_puntaje_ia",
        "postulacion",
        "puntaje_ia IS NULL OR (puntaje_ia >= 0 AND puntaje_ia <= 100)",
    )
    op.create_index(
        "idx_postulacion_motivo_rechazo_id",
        "postulacion",
        ["motivo_rechazo_id"],
    )
    op.create_index("idx_postulacion_empleado_id", "postulacion", ["empleado_id"])


def downgrade() -> None:
    op.drop_index("idx_postulacion_empleado_id", table_name="postulacion")
    op.drop_index("idx_postulacion_motivo_rechazo_id", table_name="postulacion")
    op.drop_constraint("ck_postulacion_puntaje_ia", "postulacion", type_="check")
    op.drop_constraint(
        "fk_postulacion_motivo_rechazo_id_motivo_rechazo",
        "postulacion",
        type_="foreignkey",
    )
    op.drop_column("postulacion", "fecha_ultimo_cambio")
    op.drop_column("postulacion", "fecha_postulacion")
    op.drop_column("postulacion", "puntaje_ia")
    op.drop_column("postulacion", "empleado_id")
    op.drop_column("postulacion", "motivo_rechazo_id")

    op.execute("DROP TRIGGER IF EXISTS trg_motivo_rechazo_updated_at ON motivo_rechazo")
    op.drop_index("idx_motivo_rechazo_empresa_id", table_name="motivo_rechazo")
    op.drop_table("motivo_rechazo")

    op.drop_index("uq_postulante_empresa_ci_ci", table_name="postulante")
    op.drop_index("idx_postulante_empresa_id", table_name="postulante")
    op.drop_constraint("uq_postulante_empresa_ci", "postulante", type_="unique")
    op.drop_constraint("fk_postulante_empresa_id_empresa", "postulante", type_="foreignkey")
    op.create_unique_constraint("uq_postulante_ci", "postulante", ["ci"])
    op.create_index(
        "uq_postulante_ci_ci",
        "postulante",
        [sa.literal_column("lower(ci)")],
        unique=True,
    )
    op.drop_column("postulante", "fecha_registro")
    op.drop_column("postulante", "en_banco_talento")
    op.drop_column("postulante", "cv_texto")
    op.drop_column("postulante", "direccion")
    op.drop_column("postulante", "empresa_id")

    op.add_column("etapa_reclutamiento", sa.Column("codigo", sa.String(40), nullable=True))
    op.execute(
        """
        UPDATE etapa_reclutamiento
        SET codigo = CASE orden
            WHEN 1 THEN 'POSTULADO'
            WHEN 2 THEN 'PRESELECCIONADO'
            WHEN 3 THEN 'ENTREVISTA'
            WHEN 4 THEN 'OFERTA'
            WHEN 5 THEN 'CONTRATADO'
            WHEN 6 THEN 'DESCARTADO'
            ELSE upper(replace(nombre, ' ', '_'))
        END
        """
    )
    op.alter_column("etapa_reclutamiento", "codigo", nullable=False)
    op.drop_index("idx_etapa_reclutamiento_empresa_id", table_name="etapa_reclutamiento")
    op.drop_constraint(
        "uq_etapa_reclutamiento_empresa_orden",
        "etapa_reclutamiento",
        type_="unique",
    )
    op.drop_constraint(
        "uq_etapa_reclutamiento_empresa_nombre",
        "etapa_reclutamiento",
        type_="unique",
    )
    op.drop_constraint(
        "ck_etapa_reclutamiento_orden_positivo",
        "etapa_reclutamiento",
        type_="check",
    )
    op.drop_constraint(
        "fk_etapa_reclutamiento_empresa_id_empresa",
        "etapa_reclutamiento",
        type_="foreignkey",
    )
    op.drop_column("etapa_reclutamiento", "es_rechazado")
    op.drop_column("etapa_reclutamiento", "es_contratado")
    op.drop_column("etapa_reclutamiento", "es_inicial")
    op.drop_column("etapa_reclutamiento", "color")
    op.drop_column("etapa_reclutamiento", "empresa_id")
    op.create_check_constraint(
        "ck_etapa_postulacion_orden_positivo",
        "etapa_reclutamiento",
        "orden > 0",
    )
    op.create_unique_constraint("uq_etapa_postulacion_orden", "etapa_reclutamiento", ["orden"])
    op.create_unique_constraint("uq_etapa_postulacion_codigo", "etapa_reclutamiento", ["codigo"])
    _rename_trigger_if_exists(
        "etapa_reclutamiento",
        "trg_etapa_reclutamiento_updated_at",
        "trg_etapa_postulacion_updated_at",
    )
    op.rename_table("etapa_reclutamiento", "etapa_postulacion")

    op.drop_constraint("uq_vacante_habilidad_pair", "vacante_habilidad", type_="unique")
    op.drop_constraint("pk_vacante_habilidad", "vacante_habilidad", type_="primary")
    op.drop_column("vacante_habilidad", "id")
    op.create_primary_key(
        "vacante_habilidad_pkey",
        "vacante_habilidad",
        ["vacante_id", "habilidad_id"],
    )

    op.drop_column("vacante", "fecha_registro")
    op.drop_column("habilidad", "categoria")
    op.drop_constraint("ck_cargo_rango_salario", "cargo", type_="check")
    op.drop_constraint("ck_cargo_salario_max_no_negativo", "cargo", type_="check")
    op.drop_constraint("ck_cargo_salario_min_no_negativo", "cargo", type_="check")
    op.drop_column("cargo", "salario_max")
    op.drop_column("cargo", "salario_min")
    op.drop_column("cargo", "nivel")

    op.drop_index("idx_departamento_responsable_id", table_name="departamento")
    op.drop_index("idx_departamento_padre_id", table_name="departamento")
    op.drop_constraint(
        "fk_departamento_responsable_id_usuario",
        "departamento",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_departamento_departamento_padre_id_departamento",
        "departamento",
        type_="foreignkey",
    )
    op.drop_column("departamento", "responsable_id")
    op.drop_column("departamento", "departamento_padre_id")
