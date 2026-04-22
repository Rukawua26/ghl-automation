## GHL Assistant v2

### Objetivo

Extender la v1 para que el asistente trabaje a partir del estado real de GHL, consuma materiales mixtos sin obligar al usuario a estructurarlos a mano y consulte documentacion oficial antes de planear o ejecutar.

### Decisiones aprobadas

- La fuente principal de verdad es lo que ya existe en GHL.
- El asistente acepta mezcla de texto, capturas, correos, adjuntos y archivos sueltos.
- Debe consultar documentacion oficial de GHL siempre.
- El login puede usar credenciales en archivo.
- Si aparece 2FA o un bloqueo, debe pausar y pedir ayuda al usuario.

### Alcance v2

- Estructura mixta de carpetas: `inputs/`, `emails/`, `attachments/`, `prompts/`
- Ingesta automatica de materiales locales y archivos sueltos relevantes
- Carga de credenciales desde archivo local o variables de entorno
- Reutilizacion de sesion mediante `storage_state`
- Escaneo del workflow actual antes de planificar cambios
- Consulta y cache de documentacion del Help Center oficial de GHL
- Deteccion de faltantes antes de aplicar cambios
- Flujo `assist` con escaneo, plan, resumen y aplicacion

### Riesgos que cubre

- El usuario ya no tiene que preparar todo manualmente en formato rigido.
- La herramienta no asume que su lectura local es la verdad; primero revisa GHL.
- Si no puede completar login o 2FA, se detiene sin perder la sesion.
- Si faltan correos, adjuntos o un campo de cita, lo informa antes de ejecutar.

### Limites de esta iteracion

- La ejecucion automatica sigue siendo conservadora porque los selectores de GHL pueden variar.
- La consulta de documentacion se apoya en busquedas del dominio oficial, no en una API formal.
- La creacion completa de workflows desde cero todavia requiere mas conocimiento empirico de la interfaz exacta de la cuenta.
