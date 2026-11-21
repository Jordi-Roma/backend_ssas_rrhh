# Verificación técnica local de T4-25 y T4-26

Se creó un clúster PostgreSQL 16 temporal en el equipo local y dos bases nuevas:
`ssas_source_sprint4` y `ssas_restore_sprint4`. Ninguna era la base de producción.

1. Se aplicaron todas las migraciones hasta `20261117_0015` en la base origen.
2. Se insertaron dos empresas distintas, cada una con un departamento, cargo, empleado,
   contrato, curso, lección e inscripción.
3. `backup_global_programado.py` generó un dump custom y un manifiesto SHA-256.
4. `verificar_restore_global.py` comprobó que la base destino no tenía tablas y restauró el dump.
5. Los conteos por empresa coincidieron en **todas las tablas con `empresa_id`**. Para cada empresa
   hubo un empleado, contrato, curso, lección e inscripción; los contratos cruzados fueron cero.

Resultado: `VERIFICADO` en la prueba técnica local. Esta ejecución fue realizada por quien
implementó el script. La aceptación formal T4-26 requiere que otra persona repita el paso 4,
conserve la salida y firme el resultado.
