# 🤖 GHL Automation

> Asistente de automatización para GoHighLevel (GHL) que combina Playwright + Ollama para auditar, planificar y aplicar cambios en workflows.

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Playwright](https://img.shields.io/badge/Playwright-Browser%20Automation-green.svg)](https://playwright.dev)
[![Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-orange.svg)](https://ollama.ai)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📋 Tabla de contenidos

- [Características](#-características)
- [Requisitos](#-requisitos)
- [Instalación](#-instalación)
- [Uso](#-uso)
- [Estructura del proyecto](#-estructura-del-proyecto)
- [Configuración](#-configuración)
- [Modo de trabajo](#-modo-de-trabajo)
- [Contribuir](#-contribuir)
- [Licencia](#-licencia)

---

## ✨ Características

- 🔍 **Escaneo interactivo** de workflows de GHL
- 📝 **Generación de planes** a partir de instrucciones en texto libre
- 🎯 **Aplicación automatizada** de cambios en etapas específicas
- 🤖 **Asistente LLM local** con Ollama para análisis inteligente
- 📚 **Consulta automática** de documentación oficial de GHL
- 📸 **Captura de pantalla** y snapshots del estado actual
- 🔐 **Manejo de 2FA** y sesiones persistentes

---

## 📦 Requisitos

- Python 3.10+
- [Ollama](https://ollama.ai) instalado localmente
- Navegador Chromium (instalado automáticamente por Playwright)
- Cuenta de GoHighLevel

---

## 🚀 Instalación

```bash
# Clonar el repositorio
git clone https://github.com/Rukawua26/ghl-automation.git
cd ghl-automation

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate     # Windows

# Instalar dependencias
pip install -r requirements.txt  # Si existe
pip install playwright ollama

# Instalar navegador Chromium
playwright install chromium
```

---

## 🖥️ Uso

### Escaneo de workflow

```bash
python ghl_auditor.py scan
```

Abre el navegador, inicia sesión en GHL y deja visible el workflow a auditar.

### Generar plan de cambios

```bash
python ghl_auditor.py plan --instructions inputs/instructions/mis_instrucciones.txt
```

O con resumen de Ollama:

```bash
python ghl_auditor.py plan --instructions instrucciones.txt --ollama-summary
```

### Aplicar plan

```bash
python ghl_auditor.py apply --plan .ghl_assistant/plans/mi_plan.json
```

### Scripts heredados

```bash
# Análisis simple
python extractor_ghl.py

# Análisis profesional
python analizador_pro.py
```

---

## 📂 Estructura del proyecto

```
ghl-automation/
├── ghl_auditor.py        # Asistente principal v2
├── extractor_ghl.py     # Script heredado simple
├── analizador_pro.py    # Script heredado pro
├── AGENTS.md            # Guía para agentes IA
├── inputs/
│   ├── instructions/    # Archivos de instrucciones
│   ├── context/         # Credenciales y contexto
│   └── pipeline/        # Datos de pipeline
├── emails/              # Plantillas de correo
├── attachments/        # Archivos adjuntos
├── prompts/            # Plantillas de prompts
└── .ghl_assistant/     # Artefactos generados
    ├── snapshots/       # Fotos del estado actual
    ├── plans/           # Planes generados
    ├── results/         # Resultados de aplicación
    └── docs/            # Docs cacheadas de GHL
```

---

## ⚙️ Configuración

Crea un archivo `.env` en la raíz:

```env
# Modelo Ollama
OLLAMA_MODEL=llama3.2:latest

# URL de GHL
GHL_BASE_URL=https://app.gohighlevel.com

# Credenciales (alternativa: credentials.json)
GHL_EMAIL=tu@email.com
GHL_PASSWORD=tu_password
```

O usa `inputs/context/credentials.json`:

```json
{
  "default_account": "main",
  "accounts": {
    "main": {
      "email": "tu@email.com",
      "password": "tu_password"
    }
  }
}
```

---

## 🔧 Modo de trabajo

```
┌─────────────────────────────────────────────────────────┐
│                    FLUJO DE TRABAJO                     │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   📝 PLAN    │───▶│   🤖 AUDIT   │───▶│   ✅ APPLY   │
│  Instrucciones│    │   Snapshot   │    │   Cambios    │
└──────────────┘    └──────────────┘    └──────────────┘
                           │
                           ▼
                   ┌──────────────┐
                   │   📚 DOCS    │
                   │ GHL Help Center + API Local │
                   └──────────────┘
```

1. **Plan**: Escribe instrucciones en texto libre describiendo los cambios deseados
2. **Audit**: Escanea el workflow actual y genera un plan detallado
3. **Apply**: Aplica los cambios paso a paso (con confirmación manual)

### Documentación API local

El proyecto incluye la documentación oficial de GHL API v2 en `docs/ghl-api/`:

```bash
# Actualizar documentación
cd docs/ghl-api && git pull

# Buscar endpoint específico
python -c "
import json
with open('docs/ghl-api/toc.json') as f:
    toc = json.load(f)
for item in toc['items']:
    if item.get('type') == 'item' and 'contact' in item.get('title','').lower():
        print(item['title'], '->', item['uri'])
"
```

---

## 🤝 Contribuir

1. Fork el repositorio
2. Crea una rama (`git checkout -b feature/nueva-funcion`)
3. Commit tus cambios (`git commit -m 'Agregar nueva función'`)
4. Push a la rama (`git push origin feature/nueva-funcion`)
5. Abre un Pull Request

---

## 📄 Licencia

Este proyecto está bajo la Licencia MIT. Ver el archivo [LICENSE](LICENSE) para más detalles.

---

Hecho con ❤️ para automatizar workflows de GoHighLevel