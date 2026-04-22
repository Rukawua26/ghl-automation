import ollama
from playwright.sync_api import sync_playwright


def ejecutar_automatizacion():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--enable-features=UseOzonePlatform", "--ozone-platform=wayland"],
        )

        context = browser.new_context()
        page = context.new_page()

        print("🚀 Abriendo GoHighLevel...")
        page.goto("https://gohighlevel.com")

        print("\n👉 ACCIÓN REQUERIDA:")
        print("1. Loguéate en tu cuenta.")
        print("2. Entra al Automation/Workflow que quieres analizar.")
        print(
            "3. Cuando estés viendo los pasos del workflow, presiona ENTER en esta terminal."
        )

        input("\nPresiona Enter cuando estés dentro del workflow...")

        print("🔍 Extrayendo configuración del workflow...")

        try:
            workflow_content = page.inner_text(
                ".workflow-builder-content", timeout=5000
            )
        except:
            workflow_content = None

        if not workflow_content:
            try:
                workflow_content = page.inner_text("body", timeout=5000)
            except:
                workflow_content = "No se pudo extraer el contenido"

        page.screenshot(path="debug_workflow.png")
        print("📸 Captura de pantalla guardada como debug_workflow.png")
        print(f"🌐 URL actual: {page.url}")

        print("\n✅ Datos extraídos. Consultando a Ollama local...")

        prompt = f"""
        Analiza este flujo de trabajo de GoHighLevel:
        ---
        {workflow_content}
        ---
        Basado en las mejores prácticas generales de GHL, ¿Ves algún error lógico o paso faltante?
        Responde de forma concisa en español.
        """

        try:
            response = ollama.generate(model="llama3.2", prompt=prompt)
            print("\n🤖 ANÁLISIS DE OLLAMA:")
            print(response["response"])
        except Exception as e:
            print(f"❌ Error al conectar con Ollama: {e}")

        input("\nRevisión terminada. Presiona Enter para cerrar el navegador...")
        browser.close()


if __name__ == "__main__":
    ejecutar_automatizacion()
