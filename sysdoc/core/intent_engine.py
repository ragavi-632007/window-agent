from typing import Dict, List


class IntentEngine:
    def __init__(self) -> None:
        self.intent_map: Dict[str, List[str]] = {
            "GREETING": [
                "hi", "hello", "hey", "greetings",
                "good morning", "good afternoon", "good evening", "how are you",
            ],
            "NETWORK": [
                "slow internet", "wifi", "wi-fi", "no internet", "dns", "ping",
                "isp", "connection", "speed", "packet loss", "outage", "latency",
                "router", "still slow", "retest", "network", "speedtest",
                "signal", "bandwidth", "speed test", "internet speed",
            ],
            "STORAGE": [
                "drive", "c drive", "disk full", "no space", "storage", "full", "duplicate",
                "partition", "d drive", "temp files", "recycle bin", "large files",
                "disk usage", "junk", "clean disk", "low storage", "e drive",
                "shrink", "extend", "disk space", "free space", "my drive",
                "cache", "clear cache", "clean cache", "cached files", "improve performance",
                "boost performance", "speed up", "clean up pc", "free up space",
                "performance", "slow pc cache", "clear temp",
            ],
            "DEV_ENV": [
                "pip", "pip install", "python", "module not found", "import error",
                "venv", "virtualenv", "node", "npm", "vs code", "path",
                "dependency", "conflict", "requirements", "build fail", "corrupted",
                "broken install", "dev environment", "python error", "pypi",
            ],
            "SYSTEM": [
                "crash", "restart", "bsod", "blue screen", "freeze", "heat",
                "cpu", "ram", "overheating", "slow pc", "lagging", "memory",
                "fan", "temperature", "hang", "startup slow", "memory leak",
                "process", "task manager", "tabs", "live tabs", "open tabs",
                "browser tabs", "close app", "close apps", "background apps",
                "background process", "free memory", "free ram", "kill app",
                "optimize system", "restart explorer", "optimize pc",
            ],
            "SCAN": [
                "scan", "full scan", "check all", "diagnose", "everything",
                "health check", "system check", "full report", "all modules",
            ],
            "TICKET": [
                "ticket", "escalate", "technician", "report", "help desk",
                "create ticket", "open ticket", "support",
            ],
            "INSTALL": [
                "install", "download", "how to install", "how do i install",
                "i want to install", "i need to install", "can you install",
                "get me", "setup", "grab",
            ],
            "FILE_SEARCH": [
                "find file", "find folder", "find app", "find my file", "find my folder",
                "find my app", "find my", "where is the file", "where is the folder",
                "where is my", "where my", "where is", "locate file", "locate folder",
                "locate app", "search for file", "search for folder", "search for app",
                "look for file", "look for folder", "show me where", "find", "locate",
            ],

            "FILE_RAG": [
                "explain the", "summarize the", "summarise the",
                "what does this project", "architecture of",
                "explain architecture", "explain its architecture", "project structure",
                "answer questions about", "based on the file",
                "based on the folder", "from the pdf", "from the document",
                "generate outline", "presentation outline",
                "where is jwt", "where is authentication",
                "search inside", "search within",
                "compare the documents", "compare these files",
                "extract requirements", "key concepts in",
                "analyze the code", "analyze the project",
                "read the file and", "read the document and",
                "tell me about the file", "tell me about the project",
                "explain its architecture", "summarize chapter",
                "authentication flow",
                # Bare understanding verbs — enable hybrid FILE_SEARCH+RAG detection
                "explain", "summarize", "summarise", "analyse", "analyze",
                "describe", "what is in", "what does", "tell me about",
                "show me the code", "how does", "what does it do",
            ],

            "FILE_DELETE": [
                "delete file", "delete folder", "delete my file", "delete my folder",
                "delete my", "remove file", "remove folder", "remove my file",
                "remove my", "i want to delete", "can you delete", "please delete",
                "get rid of", "erase file", "erase folder", "erase my",
                "i need to delete", "help me delete", "how do i delete",
            ],
            "UPDATE": [
                "check for updates",
                "check for update",
                "available updates",
                "available update",
                "what needs updating",
                "what needs to be updated",
                "update apps",
                "update all apps",
                "update my apps",
                "updates available",
                "update available",
                "which apps need update",
                "which apps need updating",
                "what can i update",
                "outdated apps",
                "outdated packages",
                "pending updates",
                "pending update",
                "upgrade apps",
                "upgrade all",
                "app updates",
                "app update",
                "scan for updates",
                "scan for update",
                "list updates",
                "list update",
                "show updates",
                "show update",
                "any updates",
                "any update",
                "run updates",
                "apply updates",
                "check updates",
                "what updates",
                "updates",
                "outdated",
            ],
            "GIT": [
                "git status", "git log", "git diff", "git branch", "git remote",
                "git push", "git pull", "git commit", "git clone", "git stash",
                "git merge", "git checkout",
                "push this", "push my", "push to github", "push to git",
                "commit and push", "commit my", "pull latest", "pull rebase",
                "create branch", "switch branch", "new branch",
                "repo status", "what branch", "stash my", "clone repo",
                "fixgit", "gitpilot", "git pilot", "merge branch",
            ],
            "LAUNCHER": [
                "open chrome", "open edge", "open notepad", "open vscode",
                "close chrome", "close app", "force close", "kill chrome",
                "open recycle bin", "open downloads", "open documents",
                "open desktop", "open screenshot", "open file",
                "launch", "start app", "open folder",
                "not responding", "force kill",
            ],
        }

    def detect_intent(self, user_input: str) -> str:
        lowered = user_input.lower()
        # Fix #21 — weight multi-word keywords higher so "how to install" (3 words)
        # beats a single "install" match in another category.
        scores: Dict[str, float] = {cat: 0.0 for cat in self.intent_map}

        for category, keywords in self.intent_map.items():
            for keyword in keywords:
                if keyword in lowered:
                    scores[category] += len(keyword.split())

        # Quick launcher verbs
        if any(lowered.startswith(p) for p in (
            "open ", "close ", "launch ", "kill ", "force close", "start ",
        )) and scores.get("FILE_RAG", 0) == 0:
            # don't steal "open report and summarize" style RAG if those words present
            if not any(w in lowered for w in ("summarize", "explain", "chapter", "pdf about")):
                if scores.get("LAUNCHER", 0) > 0 or any(
                    lowered.startswith(p) for p in ("open ", "close ", "launch ", "kill ")
                ):
                    return "LAUNCHER"

        best_category = "GENERAL"

        best_score = 0.0
        tie = False

        for category, score in scores.items():
            if score > best_score:
                best_score = score
                best_category = category
                tie = False
            elif score == best_score and score > 0:
                tie = True

        if best_score == 0 or tie:
            return "GENERAL"

        # Prefer GIT when git verbs present
        if scores.get("GIT", 0) > 0 and best_category in ("GENERAL", "DEV_ENV"):
            if scores["GIT"] >= best_score:
                return "GIT"

        # Hybrid: locate + understand verbs -> prefer FILE_RAG over plain search
        if scores.get("FILE_SEARCH", 0) > 0 and scores.get("FILE_RAG", 0) > 0:
            return "FILE_RAG"

        return best_category

