# GHL Automation

## Overview
Browser automation tool for GoHighLevel (GHL) workflow auditing and editing. Uses Playwright + Ollama (local LLM).

## Run commands

```bash
# Interactive scanning of current GHL workflow
python ghl_auditor.py scan [--headless]

# Generate a plan from instructions
python ghl_auditor.py plan --instructions <file> [--ollama-summary]

# Apply a saved plan
python ghl_auditor.py apply --plan <file> [--headless]

# Legacy scripts (simpler)
python extractor_ghl.py
python analizador_pro.py
```

## Input directories

- `inputs/instructions/` - Natural language instruction files (.txt, .md, .json, .csv)
- `inputs/context/` - Credentials in `credentials.json`, business context
- `inputs/pipeline/` - Pipeline data
- `emails/` - Email templates (HTML/TXT)
- `attachments/` - File attachments
- `prompts/` - Prompt templates

## Output directories (auto-created)

- `.ghl_assistant/snapshots/` - GHL workflow snapshots + screenshots
- `.ghl_assistant/plans/` - Generated plan JSON files
- `.ghl_assistant/results/` - Action apply results
- `.ghl_assistant/docs/` - Cached GHL Help Center docs

## Configuration (.env)

```
OLLAMA_MODEL=llama3.2:latest
GHL_BASE_URL=https://app.gohighlevel.com
GHL_EMAIL=<email>
GHL_PASSWORD=<password>
```

## Key quirks

- **Wayland**: Detects `XDG_SESSION_TYPE=wayland` and passes `--ozone-platform=wayland` to Chromium
- **2FA**: Auto-pauses for manual 2FA completion when GHL requests it
- **Credentials**: Reads from `.env` or `inputs/context/credentials.json` (JSON or flat format)
- **Session persistence**: Stores browser session in `.ghl_assistant/storage_state.json` for reuse
- **Plan safety**: Most actions require manual confirmation; only `update_stage_message` is marked `safe_to_auto_apply`