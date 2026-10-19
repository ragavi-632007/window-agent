

<h1 align="center">🤖 Fixbot v4.0</h1>

<p align="center">
  <strong>Autonomous Support Engineer & Real-Time Windows Diagnostics Agent</strong>
</p>





---

## ⚡ The Problem

Modern operating system diagnostics are fragmented, frustrating, and prone to user error:
* **Fragmented Tooling**: Diagnosing system issues requires bouncing between Task Manager, Resource Monitor, WMI command lines, `ipconfig`, event log viewers, and third-party temperature monitors.
* **Cryptic Telemetry**: Windows WMI counters, network route tables, and Event Viewer crash logs (like Kernel-Power Event ID 41) are notoriously difficult to read and interpret manually.
* **Static Solutions**: Copy-pasting recommendations from Stack Overflow or support forums is risky and often outdated.
* **Security Risks**: Blindly running troubleshooting scripts with Admin privileges can break system configurations or open backdoors.

---

## 💡 The Solution: Fixbot v4.0

Fixbot is an **autonomous support agent and interactive CLI** built for Windows. It couples raw system sensors and low-level kernel APIs with **Google Gemini 2.5 Flash**. 
<p align="center">
  <img src="https://github.com/user-attachments/assets/0c4156d5-0f49-4d00-bdc7-8a05d62eca59" alt="FixBot Banner" width="100%">
</p>

Instead of searching static guides, Fixbot queries the live OS state—collecting latency pings, disk offsets, WMI CPU metrics, open browser handles, and memory consumption. It then proposes targeted, automated repair scripts, walks you through confirmation gates, applies the remedies safely, and verifies success immediately.

```
  User Question/Command (e.g. "C: drive is full" or "scan")
                         │
                         ▼
             [ Intent Router Engine ]
             ├── Strict Commands ──► Bypass LLM (Fastpath)
             └── Natural Language ─► [ Gemini 2.5 Flash Parser ]
                                                 │
                                                 ▼
        [ State Telemetry Collector ] ◄── Live System Scrapes
        (Pings, WMI Temps, Memory Maps, Process Tables)
                         │
                         ▼
             [ Execution Controller ]
                         │
                         ▼
        [ Security Permission Gate ] ◄── Renders Plan Card & Prompts User
                         │
                         ▼
         [ OS Remediation Core ] ◄── Modifies OS (Diskpart, Netsh, Setx)
                         │
                         ▼
             [ Verifier Engine ] ◄── Validates post-fix system health
```

---

## 🚀 Features

### 🔍 Deep System Diagnostics
* **Network Health Auditor**: Scrapes adapters via `psutil`, resolves gateway IPs via `route print`, audits ping latency to DNS endpoints, and converts Wi-Fi percentages to decibel-milliwatts (dBm).
* **Storage Cache Sizer**: Walks and weighs directories like User Temp, Recycle Bin, Browser profiles (Chrome, Edge, Brave, Firefox), and System Caches (WER log dumps, prefetch arrays, and thumbnail databases).
* **System Metrics Monitor**: Extracts CPU core utilization, RAM loads, GPU details (via GPUtil/nvidia-smi), and hardware fan speeds.
* **Unexpected Shutdown Tracker**: Queries the Windows System Event Log for Event ID 41 unexpected power loss crash dumps.
* **Active Tab Scraper**: Lists active application windows and extracts titles and URLs of browser tabs using remote debugging protocol queries.

### ⚙️ Automated System Repair
* **Interactive Disk Partition Wizard**: Automatically scales adjacent partitions on a disk, generates and runs `diskpart` shrink/extend configurations inside thread animations, and triggers third-party partition masters on non-adjacency.
* **Locked-File Purger**: Employs the native Windows API `MoveFileExW` to mark locked files for automated deletion during the next system reboot.
* **DNS & Wi-Fi Restorer**: Performs DNS flushes, renews IP leases, and cycles active network adapters (`netsh interface set interface Wi-Fi disable -> enable`).
* **Environment Path Self-Healer**: Scans system directories to discover Python installations and writes missing folders and `/Scripts` subfolders to path variables using `setx`.
* **Python Virtual Environment Rebuilder**: Safely purges broken virtual environment files (clearing locked git folders) and runs clean rebuilds, auto-resolving pip version conflicts.

### 🎮 Built-in Sub-Applications
* **🌿 GitPilot**: A complete visual AI Git assistant designed to stage files, generate commit logs based on diff analysis, handle stashes, manage branches, and assist with merge conflicts.
* **🏃 Ticket Rush**: An arcade runner game rendered inside the console terminal where you control `BOT` to jump over incoming code bugs and server crashes.

---

## 📂 Folder Structure

```text
fixbot-v2-main/
├── sysdoc/                    # Primary application package
│   ├── core/                  # Core orchestration and pipeline logic
│   │   ├── conversation_memory.py  # Retains context in local JSON memory
│   │   ├── executor.py             # Executes system actions and commands
│   │   ├── gemini_client.py        # Connects to Google Gemini 2.5 Flash API
│   │   ├── intent_engine.py        # Classifies incoming commands/questions
│   │   ├── permission_gate.py      # Prompt protection card rendering
│   │   ├── prompt_builder.py       # Assembles LLM prompts with OS telemetry
│   │   ├── report_generator.py     # Generates diagnostics reports (MD/HTML)
│   │   └── verifier.py             # Validates system state post-remediation
│   ├── display/               # Console UI components
│   │   ├── animations.py           # CLI load bars and menu transitions
│   │   ├── banner.py               # ASCII arts and command help banners
│   │   └── formatter.py            # Rich panels, tables, and colors
│   ├── games/                 # Console arcade games
│   │   └── ticket_rush.py          # Retro jump game console engine
│   ├── gitpilot/              # AI-powered Git assistant
│   │   ├── ai_helper.py            # Generates commits and resolves merge blocks
│   │   ├── git_ops.py              # Executes local git command line arrays
│   │   └── main.py                 # Core GitPilot user console interface
│   ├── modules/               # Low-level diagnostic scans & scripts
│   │   ├── dev_env.py              # Audits paths, runtimes, and pip environments
│   │   ├── file_finder.py          # Performs fast searches and actions on disk
│   │   ├── installer.py            # Dynamic package installer via LLM strategy
│   │   ├── network.py              # Measures adapter latency, DNS, and signals
│   │   ├── storage.py              # Analyzes drive partitions and caches
│   │   ├── system_health.py        # Audits WMI temperatures, GPU, and crashes
│   │   └── updater.py              # Resolves updates via winget, pip, and npm
│   ├── tickets/               # Support tickets manager
│   │   └── ticket_manager.py       # Mimics helpdesk queue tickets
│   ├── main.py                # Main application loop entrypoint
│   ├── config.py              # System thresholds and configurations
│   └── requirements.txt       # Dependencies manifest
├── reports/                   # Output folder for HTML diagnostic reports
├── memory/                    # Local conversation memory storage
├── run.bat                    # CMD launcher
├── run.ps1                    # PowerShell launcher
├── run.sh                     # Bash launcher
└── README.md                  # Project documentation
```

---

## 💻 Terminal Showcase & Examples

### 📊 Full Diagnostic Sweeper (`scan`)
Fixbot queries WMI, pings default network gateways, maps partition tables, and outputs a diagnostic grid.

```text
YOU > scan

◉ Analyzing NETWORK subsystem...
◉ Analyzing STORAGE subsystem...
◉ Analyzing DEV-ENV subsystem...
◉ Analyzing SYSTEM subsystem...

╭────────────────────────────── DIAGNOSTIC REPORT ──────────────────────────────╮
│ SUBSYSTEM │ DIAGNOSTIC SUMMARY                                                 │
├───────────┼────────────────────────────────────────────────────────────────────┤
│ NETWORK   │ active_adapters=Wi-Fi, gateway_ip=192.168.1.1, gateway_ping_ms=4   │
│           │ dns_status=OK, internet=reachable, wifi_signal_dbm=-48             │
├───────────┼────────────────────────────────────────────────────────────────────┤
│ STORAGE   │ drives=C: (92% USED - CRITICAL), D: (12% USED), temp_folder=0.8GB  │
│           │ recycle_bin=3.2GB, top_large_files=setup.exe (450MB)...            │
├───────────┼────────────────────────────────────────────────────────────────────┤
│ DEV-ENV   │ python_in_path=YES, active_python=3.10.2, pip_status=OK,           │
│           │ node_version=18.16.0, dependency_conflicts=none                    │
├───────────┼────────────────────────────────────────────────────────────────────┤
│ SYSTEM    │ cpu_percent=14.2%, cpu_temp_c=58.2, ram_used_pct=72.1%,            │
│           │ gpu=NVIDIA GeForce RTX 3060 (load=8%, temp=45C), crashes=none      │
╰───────────┴────────────────────────────────────────────────────────────────────╯
```

---

### 💾 Partition Wizard Walkthrough (`fix disk space`)
Borrow space from a secondary drive (`D:`) to expand `C:` using an interactive volume manager.

```text
YOU > my C drive is almost full, help

  Select a drive to take space from and add to C:

  #   Drive   Free GB   Total GB   Max you can take   Extend C:
  ─────────────────────────────────────────────────────────────
  1   D:\     284.1     500.0      198.8 GB           Yes
  2   E:\     89.4      200.0      62.5 GB            Maybe*

  * Maybe = non-adjacent partition. If extend fails, we will launch MiniTool.

  ❯ Enter drive number: 1
  
  Drive selected : D:\
  Free space     : 284.1 GB
  Max takeable   : 198.8 GB  (70% of free)

  > How many GB to take from D:\ and add to C:? 30

  ╭─────────────────────────────── Deployment Plan ───────────────────────────────╮
  │ Engine: diskpart                                                              │
  │ Exec:   select volume 2; shrink desired=30720; select volume 1; extend        │
  │ Description: Shrinks volume D by 30GB and allocates it to primary drive C.    │
  ╰───────────────────────────────────────────────────────────────────────────────╯

  ❯ Apply? [y/n]: y

  D:  *  .  .  .  .  .  .  .  C:\   Transferring 30 GB...
  D:  .  *  .  .  .  .  .  .  C:\   Transferring 30 GB...
  D:  ========>  C:\   Finalising...

  ✓ Done! C:\ extended by 30 GB. New status: 42.5 GB free.
```

---

### 📦 Smart App Installer (`install <app_name>`)
Install software seamlessly using the best package manager automatically selected by the LLM.

```text
YOU > install visual studio code

  ◉ Resolving installation strategy for: visual studio code

  ╭─────────────────────────────── Deployment Plan ───────────────────────────────╮
  │ Engine: winget                                                                │
  │ Exec:   winget install --id Microsoft.VisualStudioCode                        │
  │         --accept-package-agreements --accept-source-agreements                │
  │ Description: Installs Microsoft VS Code via the Windows Package Manager.      │
  ╰───────────────────────────────────────────────────────────────────────────────╯

  ❯ 1. Run it
  ❯ 2. Cancel
  
  Menu Choice: 1
  
  Running: winget install --id Microsoft.VisualStudioCode...
  [███████████████████████████████] 100% Downloaded vscode
  ✓ vscode installed successfully.
```

---

## ⚡ Technical Deep Dive

Fixbot communicates directly with the Windows kernel and subsystem APIs:

### 1. Locked File Erasure via `MoveFileExW`
When logs, temp databases, or profiles are locked by active processes, typical deletion triggers a `PermissionError`. Fixbot implements the `ctypes` library to access Windows system routines, calling the kernel API `MoveFileExW` directly:
```python
import ctypes
# 0x4 = MOVEFILE_DELAY_UNTIL_REBOOT
ctypes.windll.kernel32.MoveFileExW(file_path, None, 0x4)
```
The operating system caches this file handle and deletes it during the boot initialization phase before applications lock it.

### 2. Browser Tab Remote Scraping
To scrape open browser tabs without loading expensive web drivers, Fixbot scans active processes for chromium-based parameters containing `--remote-debugging-port`. It resolves debugging ports, calls the local endpoint `http://127.0.0.1:{port}/json/list`, parses titles/URLs, and closes tabs by sending requests to `http://127.0.0.1:{port}/json/close/{id}`.

### 3. OpenHardwareMonitor integration
For CPU temperatures and fan speeds, standard WMI namespaces fail to expose hardware levels. Fixbot links to `OpenHardwareMonitor` dynamically. When running, Fixbot queries the namespace `root\OpenHardwareMonitor` to extract sensor values without requiring heavy system utilities.

### 4. Partition Adjacency Resolution
To confirm if a secondary partition can extend `C:`, Fixbot queries disk indices via PowerShell:
```powershell
Get-Partition | Select-Object DriveLetter,DiskNumber,Offset,Size | Sort-Object DiskNumber,Offset
```
It computes the byte boundary end of `C:` (Offset + Size) and compares it with adjacent partition offsets. If the gap falls below a 5MB threshold, the wizard applies the merge. Otherwise, it detects installed software (e.g. AOMEI Partition Assistant, EaseUS Partition Master) using system paths and registry checks to launch it for the user.

---

## 🛠️ Installation & Setup

### 📋 Prerequisites
* **Operating System**: Windows 10 or 11 (requires running as **Administrator** to perform WMI queries, set environment paths, and run disk modifications).
* **Python**: Version 3.9 or higher.
* **API Key**: A Google Gemini API Key (Get one for free at [Google AI Studio](https://aistudio.google.com/)).

### 🔧 Setup Steps

1. **Clone the Repository**:
   ```powershell
   git clone https://github.com/dineshkumarAS-creator/fixbot-v2.git
   cd fixbot-v2
   ```

2. **Install Subsystem Requirements**:
   Open a terminal as Administrator and install dependencies:
   ```powershell
   pip install -r sysdoc/requirements.txt
   ```

3. **Configure Environment Variables**:
   Create a `.env` file in the `sysdoc/` directory:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

4. **Launch Fixbot**:
   Run the launcher script corresponding to your terminal shell:
   - **Command Prompt (CMD)**: `run.bat`
   - **PowerShell**: `./run.ps1`
   - **Git Bash / WSL**: `./run.sh`

---

## ⌨️ Command Reference

| Command | Usage Syntax | Actions Executed |
| :--- | :--- | :--- |
| **scan** | `scan` | Sweeps CPU, RAM, GPU, storage levels, network speeds, path entries, and dev version systems. |
| **processes** | `processes` or `ps` | Renders a table of the top 20 active processes sorted by CPU usage. |
| **free ram** | `free memory` or `free ram` | Analyzes background applications, filters system processes, and bulk closes selected apps to free RAM. |
| **kill** | `kill <pid>` \| `kill <app_name>` | Closes a process. If matching a browser tab title, closes the specific browser tab via DevTools/HWND hooks. |
| **tabs** | `tabs` or `live tabs` | Prints all open browser windows and active Chrome debugging tabs with their URLs and PIDs. |
| **install** | `install <app_name>` | Maps app to best manager (winget/pip/npm/choco), checks status, and installs or updates. |
| **tickets** | `tickets` | Lists mocked active support tickets inside your diagnostic database queue. |
| **ticket** | `ticket <ticket_id>` | Inspects the details, stack trace, and priority flags of a specific support ticket. |
| **find** | `find <query>` | Searches local storage drives for matching files or folders and displays an interactive operations menu. |
| **delete** | `delete <query>` | Interactively searches for a file/folder and prompts you to delete it. |
| **explorer** | `restart explorer` | Safely terminates and restarts `explorer.exe` to restore frozen Windows taskbars or menus. |
| **optimize** | `optimize system` | Estimates and clears user temps, system caches, prefetch files, error dumps, and empties the Recycle Bin. |
| **report** | `report` | Formats all diagnostic scans into an interactive HTML/Markdown support report inside the `reports/` folder. |
| **gitpilot** | `fixgit` or `\fixgit` | Launches the interactive GitPilot console. |
| **game** | `game` or `/fixgame` | Launches the console arcade runner Ticket Rush. |
| **clear** | `clear` | Clears the terminal. |
| **exit** | `exit` or `quit` | Closes Fixbot. |

---

## 🗺️ Roadmap
* [ ] **Subsystem Virtualization**: Add sandboxing support to run repair commands inside an isolated environment before writing changes to host OS.
* [ ] **Local LLM Offline Mode**: Provide fallback support for local models (e.g. Llama 3) via Ollama integration for air-gapped environments.
* [ ] **Enterprise Report Portal**: Multi-agent telemetry aggregation to export corporate compliance and health logs in JSON format.
* [ ] **Active Memory Optimization**: Real-time memory pressure monitoring to automatically yield RAM based on user threshold settings.

---

## 🤝 Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

1. Fork the Project.
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`).
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the Branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

---

## ❓ FAQ

#### Q: Is it safe to let Fixbot run commands on my system?
A: **Yes.** Fixbot never runs remediation scripts silently. Every action is routed through the security *Permission Gate*, showing you the exact CLI script, flags, and parameter changes before asking for your confirmation.

#### Q: Does it require an internet connection?
A: An internet connection is required to call the Gemini API. If the API key is offline, Fixbot falls back to strict local commands (like `scan`, `processes`, `free ram`), bypassing AI translation models.

#### Q: Can I run this on macOS or Linux?
A: While core scripts (like pings or python virtual environments) contain fallback implementations for Linux, Fixbot's advanced features—such as `MoveFileExW` scheduling, `diskpart` extensions, `wevtutil` crash checking, and WMI monitoring—are explicitly tailored for **Windows**.

---

## 📄 License
Distributed under the MIT License. See [LICENSE](file:///c:/Users/sridh/Downloads/fixbot-v2-main/fixbot-v2-main/LICENSE) for more information.

---

<p align="center">
  Made with ❤️ by the Fixbot Open-Source Contributors
</p>
