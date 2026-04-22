import os
import ollama
from playwright.sync_api import sync_playwright


def buscar_documentacion(browser, tema_corto):
    print(f"📖 Buscando técnica en GHL: {tema_corto}...")
    page_doc = browser.new_page()
    try:
        tema_url = tema_corto.replace(" ", "+").replace('"', "")
        page_doc.goto(
            f"https://help.gohighlevel.com/search?q={tema_url}", timeout=10000
        )
        page_doc.wait_for_selector("a[href*='/support/solutions/']", timeout=8000)
        page_doc.locator("a[href*='/support/solutions/']").first.click()
        page_doc.wait_for_load_state("networkidle")
        texto_doc = page_doc.inner_text("article")[:2500]
        page_doc.close()
        return texto_doc
    except:
        page_doc.close()
        return (
            "No se encontró documentación específica. Aplica Best Practices generales."
        )


def ejecutar_analisis_completo():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False, args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = browser.new_context()
        page = context.new_page()

        print("\n🚀 ANALIZADOR PRO ACTIVADO")
        tema_tecnico = input(
            "¿Qué componente revisamos? (ej: Triggers, Webhooks, WhatsApp): "
        )

        page.goto("https://app.gohighlevel.com")
        page.wait_for_timeout(5000)
        page.wait_for_load_state("domcontentloaded")
        print("\n👉 ACCIÓN: Ve al workflow y NO te muevas de la pantalla del diagrama.")
        input("Presiona ENTER cuando veas los pasos del workflow en pantalla...")

        print("🔍 Escaneando con precisión...")

        header_area = (
            page.locator(".workflow-builder-header").inner_text()
            if page.locator(".workflow-builder-header").count() > 0
            else ""
        )
        estado = (
            "PUBLICADO (PUBLISHED)"
            if "Published" in header_area
            else "BORRADOR (DRAFT)"
        )

        canvas_content = ""
        selectors = [
            ".workflow-builder-content",
            "#workflow-builder",
            ".workflow-nodes-container",
        ]
        for sel in selectors:
            if page.locator(sel).count() > 0:
                canvas_content = page.inner_text(sel)
                break

        clean_content = " ".join(canvas_content.split())[:3500]

        doc = buscar_documentacion(browser, tema_tecnico)

        prompt = f"""
        Actúa como un Auditor Senior de GoHighLevel.
        ESTADO DEL WORKFLOW: {estado}
        COMPONENTES DETECTADOS: {clean_content}
        REFERENCIA TÉCNICA: {doc}

        INSTRUCCIONES DE RESPUESTA:
        - Si el estado es DRAFT, advierte que el flujo no se disparará.
        - Analiza si el Trigger tiene condiciones (filtros).
        - Revisa si hay pasos de comunicación (email/SMS) sin un 'Wait' de seguridad.
        - Sé crítico, directo y breve. No uses introducciones amables.
        """

        print("🤖 Ollama analizando datos locales...")
        try:
            response = ollama.generate(model="llama3.2", prompt=prompt)

            print("\n" + "=" * 60)
            print(f"📌 RESULTADO DEL EXAMEN | ESTADO: {estado}")
            print("=" * 60)
            print(response["response"].strip())
            print("=" * 60)

            reporte = f"=== ANALISIS GHL - {tema_tecnico} ===\nEstado: {estado}\n\n{response['response'].strip()}"
            with open("analisis_reportes.txt", "a") as f:
                f.write(reporte + "\n\n")
            print("\n💾 Reporte guardado en analisis_reportes.txt")

            os.system(
                f"notify-send 'GHL Auditor' 'Estado: {estado} - Análisis completo'"
            )

        except Exception as e:
            print(f"❌ Error en Ollama: {e}")

        input("\nAnálisis finalizado. Presiona Enter para salir...")
        browser.close()


if __name__ == "__main__":
    ejecutar_analisis_completo()
