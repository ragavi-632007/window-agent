import os
import sys
import google.generativeai as genai


def load_dotenv(dotenv_path: str = None) -> None:
    if dotenv_path is None:
        dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(dotenv_path):
        return
    with open(dotenv_path, "r", encoding="utf-8") as dotenv_file:
        for line in dotenv_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_dotenv()

# ── Gemini ────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    print("ERROR: GEMINI_API_KEY environment variable is not set.", file=sys.stderr)
    print("       Set it with: set GEMINI_API_KEY=your_key_here", file=sys.stderr)

MODEL = "gemini-3.5-flash"
genai.configure(api_key=GEMINI_API_KEY)

# ── Groq ─────────────────────────────────────────────────────────────────
# Fast-path provider: command classification, intent disambiguation, GitPilot.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_ENABLED = bool(GROQ_API_KEY)

# ── LangSmith (opt-in) ────────────────────────────────────────────────────
LANGSMITH_ENABLED = os.environ.get("LANGSMITH_ENABLED", "false").lower() == "true"
if LANGSMITH_ENABLED:
    _ls_key = os.environ.get("LANGSMITH_API_KEY", "")
    _ls_project = os.environ.get("LANGCHAIN_PROJECT", "fixbot")
    if _ls_key:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_API_KEY", _ls_key)
        os.environ.setdefault("LANGCHAIN_PROJECT", _ls_project)
    else:
        print(
            "WARNING: LANGSMITH_ENABLED=true but LANGSMITH_API_KEY is not set — tracing disabled.",
            file=sys.stderr,
        )
        LANGSMITH_ENABLED = False

# ── Generation config defaults ────────────────────────────────────────────
# Use low temperature for deterministic structured tasks (command lookup,
# JSON output, repair planning), slightly higher for conversational replies.
STRUCTURED_TEMPERATURE = 0.2   # ask_for_command, JSON mode
CHAT_TEMPERATURE = 0.7         # ask_gemini_stream, conversational
EXPLAIN_TEMPERATURE = 0.3      # explain_file_stream, interpret_output
MAX_TOKENS_STRUCTURED = 512
MAX_TOKENS_CHAT = 2048
MAX_TOKENS_EXPLAIN = 1024
MAX_TOKENS_RAG_EXPLAIN = 4096  # RAG explain tasks need longer output for line-by-line detail

# Hard cap on file content sent to explain_file_stream to avoid token overflow
FILE_EXPLAIN_CHAR_LIMIT = 8000

# API call timeouts (seconds)
GEMINI_TIMEOUT_BLOCKING = 30
GEMINI_TIMEOUT_STREAMING = 60

SYSTEM_PROMPT = """You are Fixbot, an AI-powered Windows system support assistant running inside a terminal.

Behaviour rules:
- When greeted (hi, hello, hey, etc.), introduce yourself in 1-2 sentences and ask what system problem the user needs help with. Do NOT repeat the same greeting if the user has already been greeted this session.
- When the user asks what you do or what you are, explain briefly: you diagnose and fix real Windows issues — network, storage, CPU, dev-env — using live system data and Gemini AI.
- For technical problems (network, storage, CPU, Python/dev tools): state the root cause in 1-2 lines, then list fix options.
- For follow-up or clarification questions, answer in context of the conversation history.
- For general or off-topic questions, answer helpfully and concisely.
- If the user asks about open tabs, RAM, or processes, remind them they can run 'tabs', 'processes', or 'kill <pid>' in this terminal.

Format rules:
- Plain text only — no markdown, no asterisks, no bullet symbols, no headers.
- Keep replies short and terminal-friendly.
- Never say "I hope this helps"."""

THRESHOLDS = {
    "disk_critical": 90,
    "disk_warning": 80,
    "ram_warning": 85,
    "cpu_temp_warn": 80,
    "dns_warn_ms": 100,
    "packet_loss": 1.0,
}
