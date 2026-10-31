from typing import Literal

PlanFeature = Literal[
    "importacion_masiva",
    "reportes_avanzados",
    "analisis_cv_ia",
    "reportes_ia_voz",
    "horario_respaldo",
]

PLAN_FEATURES: tuple[str, ...] = (
    "importacion_masiva",
    "reportes_avanzados",
    "analisis_cv_ia",
    "reportes_ia_voz",
    "horario_respaldo",
)
