import argparse
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

try:
    import ollama
except ImportError:
    ollama = None

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT_DIR = Path(__file__).resolve().parent


class HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def get_text(self) -> str:
        return "\n".join(self.parts)


@dataclass
class AssistantConfig:
    model: str = "llama3.2:latest"
    report_file: str = "analisis_reportes.txt"
    base_url: str = "https://app.gohighlevel.com"
    credentials_file: str = "inputs/context/credentials.json"
    storage_state_file: str = ".ghl_assistant/storage_state.json"
    login_email: str = ""
    login_password: str = ""


@dataclass
class StageInstruction:
    name: str
    raw_text: str
    replacement_message: str = ""
    email_requests: list[str] = field(default_factory=list)
    reminder_messages: dict[str, str] = field(default_factory=dict)
    extra_notes: list[str] = field(default_factory=list)


@dataclass
class InstructionSet:
    source_text: str
    no_sms: bool = False
    remove_items: list[str] = field(default_factory=list)
    sync_notes: list[str] = field(default_factory=list)
    stages: list[StageInstruction] = field(default_factory=list)


@dataclass
class MaterialBundle:
    combined_text: str
    instruction_files: list[str] = field(default_factory=list)
    context_files: list[str] = field(default_factory=list)
    pipeline_files: list[str] = field(default_factory=list)
    email_files: list[str] = field(default_factory=list)
    attachment_files: list[str] = field(default_factory=list)
    loose_files: list[str] = field(default_factory=list)
    ignored_files: list[str] = field(default_factory=list)


class GHLAssistant:
    DOC_TOPICS = {
        "workflow": "workflow automation",
        "pipeline": "pipeline opportunities",
        "appointment": "appointments reminder",
        "custom_field": "custom fields",
        "email": "email action workflow",
        "whatsapp": "whatsapp workflow",
        "trigger": "workflow trigger filters",
    }

    def __init__(self) -> None:
        self.root = ROOT_DIR
        self.config = self._load_config()
        self.is_wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland"
        self.report_path = self.root / self.config.report_file
        self.assistant_dir = self.root / ".ghl_assistant"
        self.snapshots_dir = self.assistant_dir / "snapshots"
        self.plans_dir = self.assistant_dir / "plans"
        self.results_dir = self.assistant_dir / "results"
        self.docs_dir = self.assistant_dir / "docs"
        self.storage_state_path = self.root / self.config.storage_state_file
        self.input_dirs = {
            "instructions": self.root / "inputs/instructions",
            "pipeline": self.root / "inputs/pipeline",
            "context": self.root / "inputs/context",
            "emails": self.root / "emails",
            "attachments": self.root / "attachments",
            "prompts": self.root / "prompts",
        }
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        for path in (
            self.assistant_dir,
            self.snapshots_dir,
            self.plans_dir,
            self.results_dir,
            self.docs_dir,
            self.input_dirs["instructions"],
            self.input_dirs["pipeline"],
            self.input_dirs["context"],
            self.input_dirs["emails"],
            self.input_dirs["attachments"],
            self.input_dirs["prompts"],
        ):
            path.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> AssistantConfig:
        env_path = self.root / ".env"
        env_data: dict[str, str] = {}
        if env_path.exists():
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env_data[key.strip()] = value.strip()

        return AssistantConfig(
            model=env_data.get("OLLAMA_MODEL", AssistantConfig.model),
            report_file=env_data.get("REPORT_FILE", AssistantConfig.report_file),
            base_url=env_data.get("GHL_BASE_URL", AssistantConfig.base_url),
            credentials_file=env_data.get(
                "GHL_CREDENTIALS_FILE", AssistantConfig.credentials_file
            ),
            storage_state_file=env_data.get(
                "GHL_STORAGE_STATE_FILE", AssistantConfig.storage_state_file
            ),
            login_email=env_data.get("GHL_EMAIL", ""),
            login_password=env_data.get("GHL_PASSWORD", ""),
        )

    def get_browser_args(self) -> list[str]:
        args = ["--no-sandbox", "--disable-setuid-sandbox"]
        if self.is_wayland:
            args.extend(
                ["--enable-features=UseOzonePlatform", "--ozone-platform=wayland"]
            )
        return args

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    def _clean_multiline(self, value: str) -> str:
        lines = [line.rstrip() for line in value.splitlines()]
        cleaned: list[str] = []
        blank_pending = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if cleaned:
                    blank_pending = True
                continue
            if blank_pending:
                cleaned.append("")
                blank_pending = False
            cleaned.append(stripped)
        return "\n".join(cleaned).strip()

    def _save_json(self, folder: Path, prefix: str, payload: dict[str, Any]) -> Path:
        path = folder / f"{self._timestamp()}_{prefix}.json"
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return path

    def _latest_json(self, folder: Path) -> Path | None:
        candidates = sorted(folder.glob("*.json"))
        return candidates[-1] if candidates else None

    def _pause(self, message: str) -> None:
        print(message)
        input("Presiona ENTER para continuar... ")

    def _safe_inner_text(
        self, page: Any, selectors: list[str], minimum_length: int = 0
    ) -> str:
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if locator.count() == 0:
                    continue
                text = locator.first.inner_text(timeout=2500)
                if len(text.strip()) >= minimum_length:
                    return text
            except PlaywrightTimeoutError:
                continue
            except Exception:
                continue
        return ""

    def debug_page_state(self, page: Any, context: str = "") -> dict[str, Any]:
        """Captura estado debug del navegador: URL, titulo, console errors, estructura DOM."""
        debug_info = {
            "context": context,
            "url": page.url,
            "title": page.title() if page.title else "N/A",
        }
        try:
            console_logs = []
            page.on("console", lambda msg: console_logs.append(f"{msg.type}: {msg.text}"))
            debug_info["console_messages"] = console_logs[:10]
        except Exception:
            debug_info["console_messages"] = []

        for selector in ["body", ".workflow-builder-content", "#workflow-builder"]:
            try:
                if page.locator(selector).count() > 0:
                    debug_info["main_content_length"] = len(
                        page.locator(selector).first.inner_text()
                    )
                    break
            except Exception:
                continue

        return debug_info

    def _detect_candidate_labels(self, text: str) -> list[str]:
        candidates: list[str] = []
        ignored_prefixes = (
            "descripcion",
            "acciones",
            "objetivo",
            "mensaje",
            "trigger",
            "filters",
            "published",
            "draft",
            "search",
        )
        for raw_line in text.splitlines():
            line = self._clean_text(raw_line)
            if not line or len(line) > 70 or len(line.split()) > 8:
                continue
            if line.lower().startswith(ignored_prefixes):
                continue
            if line not in candidates:
                candidates.append(line)
        return candidates[:50]

    def _read_json_file(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _looks_like_logged_in(self, page: Any) -> bool:
        current_url = page.url.lower()
        if "app.gohighlevel.com" in current_url and not any(
            token in current_url for token in ("login", "signin", "forgot")
        ):
            return True
        visible_text = self._safe_inner_text(page, ["body"], minimum_length=1).lower()
        return any(
            token in visible_text
            for token in ("workflow", "opportunities", "automation", "dashboard")
        )

    def _credentials(self) -> dict[str, str]:
        credentials = {
            "email": self.config.login_email,
            "password": self.config.login_password,
        }
        credentials_path = self.root / self.config.credentials_file
        if credentials_path.exists():
            data = self._read_json_file(credentials_path)
            if "accounts" in data:
                default_account = data.get("default_account")
                selected = (
                    data["accounts"].get(default_account, {}) if default_account else {}
                )
                credentials["email"] = selected.get("email", credentials["email"])
                credentials["password"] = selected.get(
                    "password", credentials["password"]
                )
            else:
                credentials["email"] = data.get("email", credentials["email"])
                credentials["password"] = data.get("password", credentials["password"])
        return credentials

    def _fill_first(self, page: Any, selectors: list[str], value: str) -> bool:
        if not value:
            return False
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if locator.count() == 0:
                    continue
                locator.first.click(timeout=2000)
                locator.first.fill(value, timeout=2000)
                return True
            except Exception:
                continue
        return False

    def _click_first(self, page: Any, selectors: list[str]) -> bool:
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if locator.count() == 0:
                    continue
                locator.first.click(timeout=2000)
                return True
            except Exception:
                continue
        return False

    def _needs_two_factor(self, page: Any) -> bool:
        text = self._safe_inner_text(page, ["body"], minimum_length=1).lower()
        return any(
            token in text
            for token in (
                "verification code",
                "two-factor",
                "2-factor",
                "2fa",
                "codigo de verificacion",
                "authentication code",
            )
        )

    def _attempt_login(self, page: Any) -> str:
        credentials = self._credentials()
        if not credentials.get("email") or not credentials.get("password"):
            return "Credenciales no configuradas. Se requiere login manual."

        page.goto(self.config.base_url, wait_until="domcontentloaded")
        if self._looks_like_logged_in(page):
            return "Sesion existente reutilizada."

        page.goto("https://app.gohighlevel.com/", wait_until="domcontentloaded")
        self._fill_first(
            page,
            [
                "input[type='email']",
                "input[name='email']",
                "input[placeholder*='Email']",
            ],
            credentials["email"],
        )
        self._fill_first(
            page,
            [
                "input[type='password']",
                "input[name='password']",
                "input[placeholder*='Password']",
            ],
            credentials["password"],
        )
        self._click_first(
            page,
            [
                "button[type='submit']",
                "button:has-text('Sign in')",
                "button:has-text('Login')",
            ],
        )
        page.wait_for_timeout(2500)

        if self._needs_two_factor(page):
            self._pause(
                "GHL solicito 2FA. Completa el codigo en el navegador y luego continua."
            )

        if not self._looks_like_logged_in(page):
            self._pause(
                "No se completo el login automatico. Inicia sesion manualmente en el navegador."
            )

        if self._looks_like_logged_in(page):
            page.context.storage_state(path=str(self.storage_state_path))
            return "Sesion autenticada y guardada."
        return "No se logro autenticar la sesion."

    def _new_context(
        self, playwright: Any, headless: bool = False
    ) -> tuple[Any, Any, Any]:
        browser = playwright.chromium.launch(
            headless=headless, args=self.get_browser_args()
        )
        if self.storage_state_path.exists():
            context = browser.new_context(storage_state=str(self.storage_state_path))
        else:
            context = browser.new_context()
        page = context.new_page()
        return browser, context, page

    def open_authenticated_page(self, page: Any, target_message: str) -> dict[str, Any]:
        login_result = self._attempt_login(page)
        self._pause(target_message)
        page.wait_for_load_state("domcontentloaded")
        if self._looks_like_logged_in(page):
            page.context.storage_state(path=str(self.storage_state_path))
        return {
            "login_result": login_result,
            "authenticated": self._looks_like_logged_in(page),
        }

    def capture_snapshot(
        self, page: Any, session_info: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        header = self._safe_inner_text(
            page, [".workflow-builder-header", ".hl-topbar", "header"]
        )
        workflow_name = self._safe_inner_text(
            page,
            [
                ".workflow-name-input",
                "h1",
                "h2.workflow-name",
                ".workflow-builder-header h1",
            ],
        )
        body_text = self._safe_inner_text(
            page,
            [
                ".workflow-builder-content",
                "#workflow-builder",
                ".workflow-nodes-container",
                ".workflow-scroll-container",
                "body",
            ],
            minimum_length=20,
        )
        state = "PUBLICADO (PUBLISHED)" if "Published" in header else "BORRADOR (DRAFT)"
        clean_body = self._clean_multiline(body_text)
        screenshot_path = self.snapshots_dir / f"{self._timestamp()}_scan.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        snapshot = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "url": page.url,
            "workflow_name": workflow_name or "Desconocido",
            "state": state,
            "header": header,
            "body_excerpt": clean_body[:5000],
            "candidate_labels": self._detect_candidate_labels(clean_body),
            "screenshot": str(screenshot_path),
            "session": session_info or {},
        }
        snapshot_path = self._save_json(self.snapshots_dir, "snapshot", snapshot)
        snapshot["snapshot_file"] = str(snapshot_path)
        return snapshot

    def scan(self, headless: bool = False) -> dict[str, Any]:
        with sync_playwright() as playwright:
            browser, context, page = self._new_context(playwright, headless=headless)
            session_info = self.open_authenticated_page(
                page,
                "Abre la automatizacion o workflow que quieres revisar y deja visible el diagrama.",
            )
            snapshot = self.capture_snapshot(page, session_info=session_info)
            context.close()
            browser.close()
            return snapshot

    def _is_text_material(self, path: Path) -> bool:
        return path.suffix.lower() in {".txt", ".md", ".html", ".json", ".csv"}

    def _material_text(self, path: Path) -> str:
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = path.read_text(encoding="latin-1")
        return self._clean_multiline(raw)

    def _workspace_materials(self) -> MaterialBundle:
        text_chunks: list[str] = []
        instruction_files: list[str] = []
        context_files: list[str] = []
        pipeline_files: list[str] = []
        email_files: list[str] = []
        attachment_files: list[str] = []
        loose_files: list[str] = []
        ignored_files: list[str] = []

        for category in ("instructions", "pipeline", "context"):
            base = self.input_dirs[category]
            for path in sorted(base.glob("**/*")):
                if not path.is_file():
                    continue
                if path.name == "credentials.json" or ".example." in path.name:
                    ignored_files.append(str(path.relative_to(self.root)))
                    continue
                rel = str(path.relative_to(self.root))
                if self._is_text_material(path):
                    text_chunks.append(
                        f"\n### FILE: {rel}\n{self._material_text(path)}"
                    )
                if category == "instructions":
                    instruction_files.append(rel)
                elif category == "pipeline":
                    pipeline_files.append(rel)
                else:
                    context_files.append(rel)

        for path in sorted(self.input_dirs["emails"].glob("**/*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(self.root))
            email_files.append(rel)
            if self._is_text_material(path):
                text_chunks.append(
                    f"\n### EMAIL FILE: {rel}\n{self._material_text(path)}"
                )

        for path in sorted(self.input_dirs["attachments"].glob("**/*")):
            if path.is_file():
                attachment_files.append(str(path.relative_to(self.root)))

        excluded_roots = {
            "venv",
            ".ghl_assistant",
            "docs",
            "__pycache__",
            "inputs",
            "emails",
            "attachments",
            "prompts",
        }
        ignored_loose_names = {
            "analisis_reportes.txt",
            "ghl_auditor.py",
            ".env",
            "debug_workflow.png",
            "last_audit_scan.png",
            "analizador_pro.py",
            "extractor_ghl.py",
        }
        for path in sorted(self.root.iterdir()):
            if path.name in excluded_roots or not path.is_file():
                continue
            if not self._is_text_material(path):
                continue
            if path.name in ignored_loose_names or ".example." in path.name:
                ignored_files.append(str(path.relative_to(self.root)))
                continue
            rel = str(path.relative_to(self.root))
            loose_files.append(rel)

        return MaterialBundle(
            combined_text=self._clean_multiline("\n\n".join(text_chunks)),
            instruction_files=instruction_files,
            context_files=context_files,
            pipeline_files=pipeline_files,
            email_files=email_files,
            attachment_files=attachment_files,
            loose_files=loose_files,
            ignored_files=ignored_files,
        )

    def _looks_like_stage_heading(self, line: str) -> bool:
        value = line.strip()
        if not value or len(value) > 90 or ":" in value:
            return False
        lowered = value.lower()
        if lowered.startswith(
            (
                "descripcion",
                "acciones",
                "objetivo",
                "mensaje",
                "nota",
                "campos",
                "vamos",
                "aqui",
                "tambien",
                "es importante",
                "si por alguna razon",
                "requisito",
            )
        ):
            return False
        return value[0].isdigit() or value[0] in "🔟"

    def _strip_heading_prefix(self, line: str) -> str:
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and (parts[0][0].isdigit() or parts[0][0] in "🔟"):
            return parts[1].strip()
        return line.strip()

    def _extract_remove_items(self, text: str) -> list[str]:
        match = re.search(
            r"tambien\s+eliminar\s*(.*?)(?:\n\s*\n|$)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return []
        return [
            self._clean_text(line)
            for line in match.group(1).splitlines()
            if self._clean_text(line)
        ]

    def _extract_block_after_markers(
        self, text: str, markers: list[str], stop_markers: list[str]
    ) -> str:
        upper_text = text.upper()
        start_index = -1
        matched_marker = ""
        for marker in markers:
            position = upper_text.find(marker.upper())
            if position != -1:
                start_index = position
                matched_marker = marker
                break
        if start_index == -1:
            return ""
        extracted = text[start_index + len(matched_marker) :].lstrip(" :\n")
        upper_extracted = extracted.upper()
        end_index = len(extracted)
        for marker in stop_markers:
            position = upper_extracted.find(marker.upper())
            if position != -1 and position < end_index:
                end_index = position
        return self._clean_multiline(extracted[:end_index])

    def _extract_time_block(self, text: str, label: str, stop_labels: list[str]) -> str:
        pattern = re.compile(
            rf"^\s*-?\s*{re.escape(label)}\s*$", flags=re.IGNORECASE | re.MULTILINE
        )
        match = pattern.search(text)
        if not match:
            return ""
        extracted = text[match.end() :].lstrip(" :\n")
        end_index = len(extracted)
        for stop_label in stop_labels:
            stop_pattern = re.compile(
                rf"^\s*-?\s*{re.escape(stop_label)}\s*$",
                flags=re.IGNORECASE | re.MULTILINE,
            )
            stop_match = stop_pattern.search(extracted)
            if stop_match and stop_match.start() < end_index:
                end_index = stop_match.start()
        return self._clean_multiline(extracted[:end_index])

    def parse_instruction_text(self, text: str) -> InstructionSet:
        lines = text.splitlines()
        no_sms = "NO SMS" in text.upper() or "NO SE USARA SMS" in text.upper()
        remove_items = self._extract_remove_items(text)
        sync_notes: list[str] = []
        if "clientes potenciales" in text.lower():
            sync_notes.append(
                "Alinear nombres y etapas entre el tablero Clientes potenciales y la automatizacion."
            )

        sections: list[tuple[str, list[str]]] = []
        current_name = ""
        current_lines: list[str] = []
        for raw_line in lines:
            line = raw_line.rstrip()
            if self._looks_like_stage_heading(line):
                if current_name:
                    sections.append((current_name, current_lines))
                current_name = self._strip_heading_prefix(line)
                current_lines = []
                continue
            if current_name:
                current_lines.append(line)
        if current_name:
            sections.append((current_name, current_lines))

        stop_markers = [
            "VAMOS A CONFIGURAR",
            "AQUI QUIERO",
            "TAMBIEN ELIMINAR",
            "ES IMPORTANTE",
            "- 24 HORAS ANTE",
            "- 3 HORAS ANTES",
            "-1 HORA ANTES",
            "- 1 HORA ANTES",
        ]
        stages: list[StageInstruction] = []
        for stage_name, stage_lines in sections:
            stage_text = self._clean_multiline("\n".join(stage_lines))
            replacement_message = self._extract_block_after_markers(
                stage_text,
                [
                    "VAMOS A CAMBIARLO A",
                    "CAMBIAR A",
                    "CAMBIEMOS A DETALLE PARA LAS HORAS ESPECIFICAS SEGUN EL DIA",
                ],
                stop_markers,
            )
            email_requests = []
            for raw_line in stage_text.splitlines():
                line = self._clean_text(raw_line)
                if "CORREO" in line.upper() or "EMAIL" in line.upper():
                    email_requests.append(line)
            reminder_messages = {
                "24h": self._extract_time_block(
                    stage_text, "24 HORAS ANTE", ["3 HORAS ANTES", "1 HORA ANTES"]
                ),
                "3h": self._extract_time_block(
                    stage_text, "3 HORAS ANTES", ["1 HORA ANTES"]
                ),
                "1h": self._extract_time_block(stage_text, "1 HORA ANTES", []),
            }
            reminder_messages = {
                key: value for key, value in reminder_messages.items() if value
            }
            extra_notes = []
            if "FORMULARIO DMA" in stage_text.upper():
                extra_notes.append("Usar el recurso Formulario DMA en esta etapa.")
            if "DOS CORREOS" in stage_text.upper() or "1 POR MES" in stage_text.upper():
                extra_notes.append(
                    "Configurar una secuencia de 2 correos, uno por mes despues de la ultima conversacion."
                )
            if "REAGENDAR" in stage_text.upper():
                extra_notes.append(
                    "La automatizacion debe reaccionar cuando el lead escriba REAGENDAR."
                )
            if (
                "FECHA Y HORA" in stage_text.upper()
                or "DIA DE SU CITA" in stage_text.upper()
            ):
                extra_notes.append(
                    "Se requiere un campo de fecha y hora de cita para disparar recordatorios."
                )
            if (
                replacement_message
                or email_requests
                or reminder_messages
                or extra_notes
                or stage_text
            ):
                stages.append(
                    StageInstruction(
                        name=stage_name,
                        raw_text=stage_text,
                        replacement_message=replacement_message,
                        email_requests=email_requests,
                        reminder_messages=reminder_messages,
                        extra_notes=extra_notes,
                    )
                )

        return InstructionSet(
            source_text=text,
            no_sms=no_sms,
            remove_items=remove_items,
            sync_notes=sync_notes,
            stages=stages,
        )

    def _topics_from_context(
        self, snapshot: dict[str, Any] | None, text: str
    ) -> list[str]:
        haystack = text.lower()
        if snapshot:
            haystack = f"{haystack}\n{snapshot.get('body_excerpt', '').lower()}\n{snapshot.get('header', '').lower()}"
        topics = {"workflow", "pipeline"}
        if any(
            token in haystack
            for token in ("cita", "appointment", "24 horas", "1 hora", "3 horas")
        ):
            topics.add("appointment")
        if any(
            token in haystack for token in ("campo", "custom field", "fecha y hora")
        ):
            topics.add("custom_field")
        if any(token in haystack for token in ("correo", "email")):
            topics.add("email")
        if any(token in haystack for token in ("whatsapp", "wa")):
            topics.add("whatsapp")
        if any(token in haystack for token in ("trigger", "disparador", "filtro")):
            topics.add("trigger")
        return sorted(topics)

    def _search_url_for_topic(self, topic: str) -> str:
        query = self.DOC_TOPICS[topic]
        return f"https://help.gohighlevel.com/support/search?term={quote_plus(query)}"

    def _fetch_doc_text(self, url: str) -> dict[str, Any]:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 GHLAssistant/2.0"})
        try:
            with urlopen(request, timeout=20) as response:
                html = response.read().decode("utf-8", errors="ignore")
            parser = HTMLTextExtractor()
            parser.feed(html)
            text = self._clean_multiline(parser.get_text())[:6000]
            return {"url": url, "status": "ok", "excerpt": text[:2000]}
        except HTTPError as exc:
            return {"url": url, "status": f"http_error_{exc.code}", "excerpt": ""}
        except URLError as exc:
            return {"url": url, "status": f"url_error_{exc.reason}", "excerpt": ""}
        except Exception as exc:
            return {"url": url, "status": f"error_{type(exc).__name__}", "excerpt": ""}

    def consult_official_docs(
        self, snapshot: dict[str, Any] | None, instruction_text: str
    ) -> list[dict[str, Any]]:
        notes: list[dict[str, Any]] = []
        for topic in self._topics_from_context(snapshot, instruction_text):
            cache_file = self.docs_dir / f"{topic}.json"
            doc_url = self._search_url_for_topic(topic)
            payload = self._fetch_doc_text(doc_url)
            payload["topic"] = topic
            cache_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            notes.append(payload)
        return notes

    def _snapshot_contains(self, snapshot: dict[str, Any] | None, text: str) -> bool:
        if not snapshot:
            return False
        haystack = " ".join(
            [
                snapshot.get("workflow_name", ""),
                snapshot.get("header", ""),
                snapshot.get("body_excerpt", ""),
                " ".join(snapshot.get("candidate_labels", [])),
            ]
        ).lower()
        return text.lower() in haystack

    def _detect_missing_information(
        self,
        instructions: InstructionSet,
        snapshot: dict[str, Any] | None,
        materials: MaterialBundle,
    ) -> list[str]:
        missing: list[str] = []
        if (
            any(stage.email_requests for stage in instructions.stages)
            and not materials.email_files
        ):
            missing.append(
                "Hay solicitudes de correo, pero no hay archivos de correo en la carpeta emails/."
            )
        if (
            "adjunto" in instructions.source_text.lower()
            and not materials.attachment_files
        ):
            missing.append(
                "Se menciona un adjunto, pero la carpeta attachments/ esta vacia."
            )
        reminder_stages = [
            stage.name for stage in instructions.stages if stage.reminder_messages
        ]
        if reminder_stages:
            haystack = ""
            if snapshot:
                haystack += (
                    f" {snapshot.get('body_excerpt', '')} {snapshot.get('header', '')}"
                )
            haystack += f" {instructions.source_text} {materials.combined_text}"
            if not any(
                token in haystack.lower()
                for token in ("fecha y hora", "appointment", "cita", "custom field")
            ):
                missing.append(
                    "Hay recordatorios por cita, pero no se detecta claramente el campo origen de fecha y hora de la cita."
                )
        if not snapshot:
            missing.append(
                "No hay snapshot actual de GHL. La fuente principal de verdad debe escanearse antes de aplicar cambios."
            )
        return missing

    def build_plan(
        self,
        instructions: InstructionSet,
        snapshot: dict[str, Any] | None,
        materials: MaterialBundle,
        docs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        actions: list[dict[str, Any]] = []
        warnings: list[str] = []
        missing = self._detect_missing_information(instructions, snapshot, materials)

        if instructions.no_sms:
            actions.append(
                {
                    "id": f"A{len(actions) + 1:02d}",
                    "kind": "channel_policy",
                    "target": "global",
                    "summary": "Desactivar o evitar SMS y usar solo WhatsApp o correo.",
                    "safe_to_auto_apply": False,
                }
            )

        for item in instructions.remove_items:
            actions.append(
                {
                    "id": f"A{len(actions) + 1:02d}",
                    "kind": "remove_stage",
                    "target": item,
                    "summary": f"Eliminar etapa o bloque '{item}'.",
                    "safe_to_auto_apply": False,
                    "found_in_snapshot": self._snapshot_contains(snapshot, item),
                }
            )

        for note in instructions.sync_notes:
            actions.append(
                {
                    "id": f"A{len(actions) + 1:02d}",
                    "kind": "sync_pipeline",
                    "target": "Clientes potenciales",
                    "summary": note,
                    "safe_to_auto_apply": False,
                }
            )

        for stage in instructions.stages:
            if stage.replacement_message:
                actions.append(
                    {
                        "id": f"A{len(actions) + 1:02d}",
                        "kind": "update_stage_message",
                        "target": stage.name,
                        "summary": f"Actualizar el mensaje principal de '{stage.name}'.",
                        "message": stage.replacement_message,
                        "safe_to_auto_apply": True,
                        "found_in_snapshot": self._snapshot_contains(
                            snapshot, stage.name
                        ),
                    }
                )
            if stage.email_requests:
                actions.append(
                    {
                        "id": f"A{len(actions) + 1:02d}",
                        "kind": "configure_email",
                        "target": stage.name,
                        "summary": f"Configurar correos relacionados con '{stage.name}'.",
                        "details": stage.email_requests,
                        "safe_to_auto_apply": False,
                    }
                )
            if stage.reminder_messages:
                actions.append(
                    {
                        "id": f"A{len(actions) + 1:02d}",
                        "kind": "schedule_reminders",
                        "target": stage.name,
                        "summary": f"Configurar recordatorios temporizados para '{stage.name}'.",
                        "reminders": stage.reminder_messages,
                        "safe_to_auto_apply": False,
                    }
                )
            for note in stage.extra_notes:
                actions.append(
                    {
                        "id": f"A{len(actions) + 1:02d}",
                        "kind": "note",
                        "target": stage.name,
                        "summary": note,
                        "safe_to_auto_apply": False,
                    }
                )
            if snapshot and not self._snapshot_contains(snapshot, stage.name):
                warnings.append(
                    f"No se detecto la etapa '{stage.name}' en el ultimo snapshot. Puede estar oculta, tener otro nombre o faltar en la automatizacion."
                )

        if snapshot and snapshot.get("state") == "BORRADOR (DRAFT)":
            warnings.append(
                "El workflow esta en borrador. Aunque se edite, no se disparara hasta publicarlo."
            )

        docs_ok = [doc for doc in docs if doc.get("status") == "ok"]
        if not docs_ok:
            warnings.append(
                "No se pudo recuperar documentacion oficial util desde GHL Help Center en este intento."
            )

        return {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "workflow_name": snapshot.get("workflow_name", "Sin snapshot")
            if snapshot
            else "Sin snapshot",
            "snapshot_file": snapshot.get("snapshot_file") if snapshot else None,
            "snapshot_url": snapshot.get("url") if snapshot else None,
            "global_rules": {"no_sms": instructions.no_sms, "source_of_truth": "ghl"},
            "materials": asdict(materials),
            "docs_consulted": docs,
            "actions": actions,
            "warnings": warnings,
            "missing_information": missing,
            "stage_count": len(instructions.stages),
        }

    def _load_snapshot(self, path: str | None) -> dict[str, Any] | None:
        if path:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        latest = self._latest_json(self.snapshots_dir)
        if not latest:
            return None
        return json.loads(latest.read_text(encoding="utf-8"))

    def _stdin_text(self) -> str:
        print("Pega texto libre. Finaliza con CTRL+D:\n")
        try:
            import sys

            return sys.stdin.read().strip()
        except Exception:
            return ""

    def _read_instruction_text(
        self, inline_text: str | None, file_path: str | None, materials: MaterialBundle
    ) -> str:
        chunks: list[str] = []
        if inline_text:
            chunks.append(inline_text.strip())
        if file_path:
            chunks.append(Path(file_path).read_text(encoding="utf-8").strip())
        if materials.combined_text:
            chunks.append(materials.combined_text)
        if not chunks:
            raw = self._stdin_text()
            if raw:
                chunks.append(raw)
        return self._clean_multiline("\n\n".join(chunks))

    def create_plan(
        self,
        instruction_text: str,
        snapshot: dict[str, Any] | None,
        materials: MaterialBundle,
        docs: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], Path]:
        instructions = self.parse_instruction_text(instruction_text)
        plan = self.build_plan(instructions, snapshot, materials, docs)
        plan["instructions_preview"] = instruction_text[:5000]
        plan_path = self._save_json(self.plans_dir, "plan", plan)
        return plan, plan_path

    def print_plan(self, plan: dict[str, Any]) -> None:
        print("\n" + "=" * 72)
        print(f"PLAN | Workflow: {plan['workflow_name']}")
        print("=" * 72)
        print(f"Fuente principal: {plan['global_rules']['source_of_truth']}")
        print(
            f"Regla global no SMS: {'si' if plan['global_rules']['no_sms'] else 'no'}"
        )
        print(f"Acciones detectadas: {len(plan['actions'])}")
        print(f"Archivos de correo: {len(plan['materials']['email_files'])}")
        print(f"Adjuntos: {len(plan['materials']['attachment_files'])}")
        for action in plan["actions"]:
            auto_flag = "AUTO" if action.get("safe_to_auto_apply") else "MANUAL"
            print(f"- {action['id']} [{auto_flag}] {action['summary']}")
            if action.get("message"):
                print(f"  Mensaje: {action['message'].replace(chr(10), ' ')[:120]}")
        if plan["docs_consulted"]:
            print("\nDocs oficiales consultadas:")
            for doc in plan["docs_consulted"]:
                print(f"- {doc['topic']}: {doc['status']} -> {doc['url']}")
        if plan["missing_information"]:
            print("\nFaltantes detectados:")
            for item in plan["missing_information"]:
                print(f"- {item}")
        if plan["warnings"]:
            print("\nAdvertencias:")
            for warning in plan["warnings"]:
                print(f"- {warning}")
        print("=" * 72)

    def append_report(self, title: str, content: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        block = f"=== {title} ===\nFecha: {timestamp}\n\n{content}\n\n{'=' * 50}\n\n"
        with self.report_path.open("a", encoding="utf-8") as handle:
            handle.write(block)

    def summarize_with_ollama(
        self, snapshot: dict[str, Any], plan: dict[str, Any]
    ) -> str:
        if ollama is None:
            return "Ollama no esta instalado en este entorno."
        prompt = f"""
Actua como un arquitecto de automatizaciones GHL.

Workflow: {snapshot.get("workflow_name", "Desconocido")}
Estado: {snapshot.get("state", "Desconocido")}
Texto visible: {snapshot.get("body_excerpt", "")[:2500]}
Plan: {json.dumps(plan.get("actions", []), ensure_ascii=False, indent=2)[:5000]}
Faltantes: {json.dumps(plan.get("missing_information", []), ensure_ascii=False)}
Docs oficiales: {json.dumps(plan.get("docs_consulted", []), ensure_ascii=False)[:3000]}

Responde en espanol con:
- riesgos criticos
- preguntas minimas al usuario
- orden recomendado de ejecucion
""".strip()
        try:
            response = ollama.generate(model=self.config.model, prompt=prompt)
            return response["response"].strip()
        except Exception as exc:
            return f"No se pudo obtener resumen con Ollama: {exc}"

    def _locate_by_text(self, page: Any, text: str) -> Any | None:
        try:
            locator = page.get_by_text(text, exact=False)
            if locator.count() > 0:
                return locator.first
        except Exception:
            return None
        return None

    def _focus_stage(self, page: Any, stage_name: str) -> bool:
        locator = self._locate_by_text(page, stage_name)
        if locator is None:
            return False
        try:
            locator.click(timeout=2500)
            page.wait_for_timeout(500)
            return True
        except Exception:
            return False

    def _fill_visible_editor(self, page: Any, message: str) -> bool:
        selectors = [
            "textarea",
            "input[type='text']",
            "[contenteditable='true']",
            "div[role='textbox']",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if locator.count() == 0:
                    continue
                editor = locator.first
                editor.click(timeout=2000)
                try:
                    editor.fill(message, timeout=2000)
                except Exception:
                    page.keyboard.press("Control+A")
                    page.keyboard.insert_text(message)
                return True
            except Exception:
                continue
        return False

    def _click_action_button(self, page: Any, labels: list[str]) -> bool:
        for label in labels:
            locator = self._locate_by_text(page, label)
            if locator is None:
                continue
            try:
                locator.click(timeout=2000)
                page.wait_for_timeout(500)
                return True
            except Exception:
                continue
        return False

    def apply_action(self, page: Any, action: dict[str, Any]) -> dict[str, Any]:
        result = {
            "id": action["id"],
            "kind": action["kind"],
            "target": action.get("target"),
            "status": "skipped",
            "details": "",
        }
        if action["kind"] == "update_stage_message":
            if not self._focus_stage(page, action["target"]):
                result["details"] = "No se encontro la etapa por texto visible."
                return result
            if self._fill_visible_editor(page, action["message"]):
                result["status"] = "applied"
                result["details"] = "Mensaje actualizado en un editor visible."
            else:
                result["details"] = (
                    "Se encontro la etapa, pero no un editor visible para escribir."
                )
            return result
        if action["kind"] == "remove_stage":
            if not self._focus_stage(page, action["target"]):
                result["details"] = (
                    "No se encontro el bloque a eliminar por texto visible."
                )
                return result
            if self._click_action_button(
                page, ["Delete", "Eliminar", "Remove", "Trash"]
            ):
                self._click_action_button(page, ["Confirm", "Delete", "Eliminar"])
                result["status"] = "applied"
                result["details"] = (
                    "Se intento eliminar el bloque usando botones visibles."
                )
            else:
                result["details"] = "No se detecto un boton visible de eliminacion."
            return result
        if action["kind"] == "configure_email":
            if self._click_action_button(
                page, ["+", "Add", "Add Action", "Nueva accion"]
            ):
                if self._fill_visible_editor(page, "Email"):
                    page.keyboard.press("Enter")
                    result["status"] = "partial"
                    result["details"] = (
                        "Se intento iniciar la adicion de una accion de email."
                    )
                else:
                    result["details"] = (
                        "Se abrio una accion, pero no se pudo buscar Email automaticamente."
                    )
            else:
                result["details"] = (
                    "No se encontro un disparador visible para agregar accion."
                )
            return result
        if action["kind"] in {
            "channel_policy",
            "sync_pipeline",
            "schedule_reminders",
            "note",
        }:
            result["status"] = "manual_required"
            result["details"] = (
                "Esta accion necesita validacion o datos adicionales antes de automatizarla."
            )
            return result
        result["details"] = "Tipo de accion sin implementacion automatica en la v2."
        return result

    def apply_plan(
        self, plan: dict[str, Any], headless: bool = False
    ) -> tuple[list[dict[str, Any]], Path]:
        results: list[dict[str, Any]] = []
        with sync_playwright() as playwright:
            browser, context, page = self._new_context(playwright, headless=headless)
            self.open_authenticated_page(
                page, "Abre la automatizacion o etapa que quieres modificar."
            )
            for action in plan["actions"]:
                print(f"\n{action['id']} | {action['summary']}")
                decision = input("Aplicar esta accion ahora? [y/N/q]: ").strip().lower()
                if decision == "q":
                    break
                if decision != "y":
                    results.append(
                        {
                            "id": action["id"],
                            "kind": action["kind"],
                            "target": action.get("target"),
                            "status": "skipped_by_user",
                            "details": "El usuario decidio no ejecutar esta accion.",
                        }
                    )
                    continue
                outcome = self.apply_action(page, action)
                results.append(outcome)
                if outcome["status"] in {"manual_required", "skipped"}:
                    self._pause(
                        "Se requiere tu ayuda o revision para continuar con este paso."
                    )
            screenshot_path = self.results_dir / f"{self._timestamp()}_apply.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            context.close()
            browser.close()
        payload = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "plan_workflow_name": plan.get("workflow_name"),
            "results": results,
            "final_screenshot": str(screenshot_path),
        }
        result_path = self._save_json(self.results_dir, "apply_results", payload)
        return results, result_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Asistente hibrido v2 para ajustar workflows de GHL usando el estado real de la cuenta."
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="assist",
        choices=["scan", "plan", "apply", "assist"],
    )
    parser.add_argument(
        "--instructions",
        help="Ruta a un archivo principal de instrucciones en texto libre.",
    )
    parser.add_argument("--prompt", help="Texto libre adicional para el asistente.")
    parser.add_argument("--snapshot", help="Ruta a un snapshot JSON para comparar.")
    parser.add_argument("--plan", help="Ruta a un plan JSON ya generado.")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Ejecuta Playwright sin abrir la ventana del navegador.",
    )
    parser.add_argument(
        "--ollama-summary",
        action="store_true",
        help="Genera un resumen adicional con Ollama si esta disponible.",
    )
    return parser


def main() -> None:
    assistant = GHLAssistant()
    parser = build_arg_parser()
    args = parser.parse_args()
    materials = assistant._workspace_materials()

    if args.command == "scan":
        snapshot = assistant.scan(headless=args.headless)
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
        assistant.append_report(
            "SCAN GHL V2", json.dumps(snapshot, indent=2, ensure_ascii=False)
        )
        return

    if args.command == "plan":
        instruction_text = assistant._read_instruction_text(
            args.prompt, args.instructions, materials
        )
        if not instruction_text:
            raise SystemExit(
                "No se recibieron instrucciones o materiales para planificar."
            )
        snapshot = assistant._load_snapshot(args.snapshot)
        docs = assistant.consult_official_docs(snapshot, instruction_text)
        plan, plan_path = assistant.create_plan(
            instruction_text, snapshot, materials, docs
        )
        assistant.print_plan(plan)
        print(f"Plan guardado en: {plan_path}")
        assistant.append_report(
            "PLAN GHL V2", json.dumps(plan, indent=2, ensure_ascii=False)
        )
        if args.ollama_summary and snapshot:
            print("\nResumen con Ollama:\n")
            print(assistant.summarize_with_ollama(snapshot, plan))
        return

    if args.command == "apply":
        plan_path = (
            Path(args.plan)
            if args.plan
            else assistant._latest_json(assistant.plans_dir)
        )
        if plan_path is None:
            raise SystemExit("No hay un plan disponible para aplicar.")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        assistant.print_plan(plan)
        if plan.get("missing_information"):
            print(
                "\nHay faltantes detectados. Se recomienda resolverlos antes de aplicar."
            )
        confirmation = input("\nAplicar este plan en GHL? [y/N]: ").strip().lower()
        if confirmation != "y":
            raise SystemExit("Aplicacion cancelada por el usuario.")
        results, result_path = assistant.apply_plan(plan, headless=args.headless)
        print(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"Resultados guardados en: {result_path}")
        assistant.append_report(
            "APPLY GHL V2", json.dumps(results, indent=2, ensure_ascii=False)
        )
        return

    if args.command == "assist":
        snapshot = assistant.scan(headless=args.headless)
        instruction_text = assistant._read_instruction_text(
            args.prompt, args.instructions, materials
        )
        if not instruction_text:
            raise SystemExit(
                "No se recibieron instrucciones o materiales para el asistente."
            )
        docs = assistant.consult_official_docs(snapshot, instruction_text)
        plan, plan_path = assistant.create_plan(
            instruction_text, snapshot, materials, docs
        )
        assistant.print_plan(plan)
        print(f"Plan guardado en: {plan_path}")
        if args.ollama_summary:
            print("\nResumen con Ollama:\n")
            print(assistant.summarize_with_ollama(snapshot, plan))
        confirmation = (
            input("\nQuieres aplicar ahora las acciones del plan? [y/N]: ")
            .strip()
            .lower()
        )
        if confirmation == "y":
            results, result_path = assistant.apply_plan(plan, headless=args.headless)
            print(json.dumps(results, indent=2, ensure_ascii=False))
            print(f"Resultados guardados en: {result_path}")
            assistant.append_report(
                "ASSIST GHL V2", json.dumps(results, indent=2, ensure_ascii=False)
            )
        else:
            assistant.append_report(
                "ASSIST GHL V2", json.dumps(plan, indent=2, ensure_ascii=False)
            )


if __name__ == "__main__":
    main()
