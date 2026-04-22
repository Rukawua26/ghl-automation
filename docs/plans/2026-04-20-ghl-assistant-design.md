## GHL Assistant v1

### Objetivo

Convertir el script actual en un asistente operativo para GoHighLevel que pueda:

- escanear la automatizacion actual
- interpretar instrucciones de negocio en texto libre
- convertirlas a una estructura interna confiable
- generar un plan de cambios antes de ejecutar
- aplicar cambios con confirmacion y trazabilidad

### Alcance v1

- Un solo script principal: `ghl_auditor.py`
- Modos `scan`, `plan`, `apply` y `assist`
- Entrada hibrida: texto libre convertido a acciones estructuradas
- Regla global para excluir SMS cuando el pedido lo indique
- Deteccion de etapas a eliminar, mensajes a reemplazar y correos a configurar
- Soporte para recordatorios por cita basados en un campo de fecha y hora
- Guardado de snapshots, planes y resultados en un directorio local de trabajo

### Arquitectura

1. Scanner GHL

Abre GHL con Playwright, espera a que el usuario entre a la pantalla correcta y captura:

- URL actual
- header visible
- texto visible del canvas o pagina
- screenshot
- candidatos de nombres de etapas visibles

2. Parser hibrido

Convierte instrucciones libres a una estructura con:

- reglas globales
- etapas objetivo
- mensaje nuevo por etapa
- solicitudes de correo
- recordatorios por tiempo
- etapas a eliminar

3. Planner

Genera una lista de acciones tipadas y advertencias. El plan se guarda como JSON para poder reutilizarse sin volver a interpretar el pedido.

4. Executor seguro

Aplica cambios uno por uno y pide confirmacion antes de cada accion destructiva o de escritura. Si no encuentra un selector confiable, no fuerza el cambio y deja evidencia para revision.

5. Memoria local

El asistente guarda:

- snapshots
- planes
- resultados de aplicacion

Todo queda en `.ghl_assistant/` dentro del proyecto.

### Riesgos controlados

- Se elimina el uso de `except:` vacio en el flujo critico.
- Se reducen esperas fijas y se reemplazan por esperas condicionadas.
- Ollama deja de ser requisito para generar un plan confiable.
- Los cambios automaticos no se ejecutan sin confirmacion.
- Se guardan artefactos de debug con timestamp para facilitar correccion.

### Evolucion posterior

La siguiente iteracion puede ampliar:

- creacion mas completa de workflows desde cero
- plantillas persistentes por cliente
- soporte directo para adjuntos de correo
- comparacion real entre pipeline CRM y automatizacion en distintas pantallas de GHL
