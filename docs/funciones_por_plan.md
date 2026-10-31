# Funciones por plan

El catálogo de planes permite marcar funciones adicionales existentes. Los módulos y los permisos de usuario siguen siendo controles independientes: para usar una acción hacen falta el permiso correspondiente y la función incluida en el plan de la empresa.

| Función | Básico | Profesional | Empresarial |
| --- | --- | --- | --- |
| Importación masiva de datos | No | Sí | Sí |
| Reportes avanzados (vista previa, guardar y exportar) | No | Sí | Sí |
| Análisis de CV con IA | No | Sí | Sí |
| Interpretación de reportes por IA o voz | No | No | Sí |
| Elegir la hora del respaldo automático | No | No | Sí |

La migración `20261030_0013` asigna estas funciones a los planes existentes según su precio: el menor queda sin funciones adicionales, los intermedios reciben las tres primeras y el mayor recibe las cinco. Antes de desplegar, revisar los planes reales en el catálogo si hay más de tres o precios iguales. Un administrador global puede modificar las casillas después desde **Planes y suscripciones**.

Si se retira una función, el backend rechaza las nuevas acciones con HTTP 403. Los datos y resultados históricos permanecen consultables con sus permisos habituales. Si se retira **Elegir la hora del respaldo automático**, el horario efectivo vuelve a las 02:00 de Bolivia; el horario personalizado guardado se conserva por si la función se vuelve a conceder. Los respaldos manuales y automáticos siguen disponibles para todos los planes.

Para activar en producción: desplegar primero el backend con las migraciones `20261030_0012` y `20261030_0013`, después el frontend. Comprobar las casillas y los permisos con una empresa de cada plan.
