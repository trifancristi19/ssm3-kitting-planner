# SSM3 kitting planner

Code for SSM3, "LLM-guided robotics for flexible manufacturing", a project of the Applied AI programme at NHL Stenden for the Smart Sustainable Manufacturing research group (client: Mrs Johnson).

The system plans order-based kitting with kit correction in a simulated tabletop cell. An operator gives a kit order or a kit change in plain language. An LLM planner turns it into a plan of allowed function calls, a question or a refusal. A checker outside the LLM replays every plan on a copy of the cell state before anything moves, and a fixed, non-LLM baseline handles the same orders so the two can be compared. Only the planner uses a language model. Everything else is fixed Python code.

## Status

Study 1, the model tests (353 runs), is finished. Its task set and checker are in `study1/` and are the first tested code in this repository. Study 2, the main experiment, is next. The simulated cell with two levels per tray slot, the four plan functions, the checker (every code of Table 9 except AMBIGUOUS and RULE_OVERRIDE), the layout comparison of the baseline and the run limits of the orchestrator now work, following Design Document 0.4. The prompt builder, the response parser, the orchestrator loop for both variants, the run logger and the scripted operator also work, tested with a fake planner, so no test calls a language model. The model client (`call_model`, Groq through its OpenAI-compatible endpoint) works and is tested only with fake HTTP answers. The evaluator (`compute_measures`) computes the six measures from run logs and a task set, tested with hand-built logs and the demo runs. Its measure definitions are a proposal, because Chapter 6 of the project plan is not in this repository. The recipe table is still a documented stub. Some design questions are still open until the client approves the Design Document at Gate A (18 November 2026), so the code does not fix them.

## Layout

```
config/capability_example.json   example capability file from Design Document Chapter 6
config/capability_kitting.json   parts and bins of DD24: 2x2 and 2x4 bricks in three colours
src/ssm3/                        the system, one module per component (Design Document Chapter 4)
  planner.py                     LLM planner, Task A (Chapter 7)
  checker.py                     checker, Task B (Chapter 8)
  baseline.py                    non-LLM baseline, Task C (Chapter 11)
  orchestrator.py                orchestrator loop (Chapter 9)
  console.py                     operator console (Chapter 9)
  functions.py                   function library: move_to, pick, place, locate, ask_operator (Chapter 5)
  cell.py                        simulated kitting cell (Chapters 4 and 12)
  capability.py                  capability file loader (Chapter 6)
  logger.py                      run logger (Chapter 10)
  evaluator.py                   the six measures (Chapter 10)
  demo.py                        terminal demo for Gate A (Chapter 13)
  experiment.py                  runs one task with baseline, open loop and closed loop, then the evaluator  viewer.py, viewer_page.html    replay page of a run log, in 2D or 3D
  cell3d.js                      3D view of the cell and the pose of the arm, used by the replay and chat pages
  vendor/three.min.js            three.js 0.147.0 (MIT licence, vendor/three.LICENSE), for the 3D view
  chat.py, chat_server.py        chat mode: typed orders on a local web page (chat_page.html)
scripts/                         demo.py, view.py, chat.py, evaluate.py and experiment.py, which run from a fresh clone
study1/tasks.py                  Study 1 task set and checker, unchanged apart from the Excel logging
tests/                           pytest tests
```

## Design Document

The Design Document is not in this repository. It is in the team's shared OneDrive folder, as `SSM3 Project/Project Documents/SSM3_Design_Document.docx`. Every module docstring names the chapter it comes from.

## Setup on Windows

1. Install Python 3.12 or newer from python.org and Git for Windows.
2. Clone the repository and open a terminal in its folder:
   ```
   git clone https://github.com/trifancristi19/ssm3-kitting-planner.git
   cd ssm3-kitting-planner
   ```
3. Create and activate a virtual environment, then install the tools:
   ```
   py -m venv .venv
   .venv\Scripts\activate
   python -m pip install -r requirements.txt
   ```
   In PowerShell, if activation is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

## Running the checks

With the virtual environment active, run the linter and the tests from the repository folder:

```
ruff check .
pytest
```

`ruff check . --fix` repairs simple problems such as the order of imports. GitHub runs the same two checks on every push and pull request. Neither the tests nor GitHub ever call an LLM, and the tests block all network access, so they never use the free API limits we need for the experiment.

## Demo

A short terminal demo runs the worked example of Chapter 13 through the real cell, checker, orchestrator loop and run log. By default the planner is scripted, so the demo calls no language model and no API. From the repository folder:

```
.venv\Scripts\python scripts\demo.py
```

It pauses with "press Enter" between scenarios. `--no-pause` runs straight through and `--scenario 2` runs one scenario. The run logs go to `demo_logs/`, which git ignores.

Scenarios 4 and 5 show what happens when the checker allows a step but the gripper fails, a question of Mrs Johnson at Gate A. In scenario 4 the gripper gets no hold on the long spacer, so the pick fails. In scenario 5 the spacer slips out of the gripper after the lift and falls back into its bin. Both run in the open loop and the closed loop. The open loop stops safely at the failed step (DD16). The closed loop sends the failure and the new state to the planner, which picks the part again. The failures are injected by the simulated cell (FR11), so the runs repeat exactly.

```
.venv\Scripts\python scripts\demo.py --scenario 4
```

Every run also gets a replay page next to its log, with the same name and `.html`. It shows the bins, the tray with its two levels, the return position and the arm, and replays every planner answer, checker verdict and step, with Play, Back and Next. The arm is a six-axis arm on the middle of the table with a two-finger gripper, shaped like the Doosan M0609 in the lab. The shape and sizes are approximate and not to scale, and the arm and gripper are not chosen yet. A failed pick shows the gripper coming up empty, and a part that slips out falls back into its bin. A switch on the drawing picks the 3D view or the 2D side view. In 3D you drag to turn the cell, hold Ctrl and scroll to zoom and double-click to go back to the first view. Both views get the same drawing calls, so they always show the same state. The 3D view uses three.js, which is put into the page, so the page only reads the log and needs no internet connection. Without WebGL the page keeps the 2D view. `--view` opens the page of the last run in the browser. For any older log:

```
.venv\Scripts\python scripts\view.py demo_logs\<run>.jsonl
```

Without a file it opens the newest log in `demo_logs/`.

### Evaluator table

```
.venv\Scripts\python scripts\evaluate.py
```

prints the six measures of the evaluator (Chapter 10) as three tables: one row per run, one per variant (the main comparison of open loop, closed loop and baseline) and one per condition (variant, model and prompt version, with the runs per task), for the `demo-*.jsonl` logs in `demo_logs/`. Give log files as arguments to evaluate other runs, `--tasks <file>.json` to use another task set, and `--json <file>` to also write the runs and summaries as JSON. Each order of a task set has the fields of DD23: `order_id`, `kit_id`, `text`, `target`, `protected`, plus `expected_outcome` (`done`, `ask` or `refuse`) and `expected_tray`. The file is checked when it is loaded (`load_task_set`), and `--capability <file>.json` also checks its slots, parts and levels against a cell. The format is in the docstring of `src/ssm3/evaluator.py`. A refuse task also counts as right when the checker blocked the order with `RULE_OVERRIDE`, and the baseline needs no question for an ask task, because it gets the structured order (DD25). The run logs hold the token use of every model call in `planner_response` (`tokens`, none for a scripted planner). When a `planner_response` also holds the planner's `target` (DD25, DD26, not logged yet), the tables show whether the target was right and reached, so a wrong interpretation is told apart from a wrong plan. The default task set, `config/task_set_demo.json`, has only order K-17 of the demo, so logs of other orders, such as those of the chat mode, need their own task set. The demo logs are scripted runs, so their model times are close to 0.

### Comparing the baseline with the language model

```
.venv\Scripts\python scripts\experiment.py
```

runs order K-17 (the start tray of Chapter 13) with the three approaches of the comparison: the **baseline** (no language model, `plan_from_layout` on the structured order), the **open loop** and the **closed loop** (the real model on Groq, so it needs `GROQ_API_KEY` and uses the free-tier limit). Every approach runs a clean case and a case with a pick failure at the first pick (for the recovery measure), 5 times each by default (`--reps`, Chapter 8). All runs use the same cell, checker, loop and log, and the runner then prints the evaluator tables for each case. The logs are saved as `demo-exp-*.jsonl` in `demo_logs/`, so `scripts\evaluate.py` shows them too. Without a key only the baseline runs; `--no-llm` runs the baseline alone, `--local` uses Ollama, and `--model`, `--delay`, `--log-dir` and `--json <file>` are as in the demo and the evaluator. A run that hits a provider limit is repeated at most three times and then listed as not run (DD21). Pilot runs are exploratory (DD22).

### Chat mode

The chat mode opens a page where you type a kit order in plain words and watch it run: the real model plans it, the checker tests every step on a copy of the cell, and the arm moves in a 3D or 2D view of the cell. The cell keeps its state from one order to the next. A question of the planner appears in the chat, and your answer goes back to the loop. "Reset cell" puts the start state of Chapter 13 back, clears the chat and sets the tick boxes as they were when the page opened, so the next demo starts afresh without restarting the server. The run logs in `demo_logs/` stay.

The "Keep unchanged" tick boxes choose the tray slots the checker protects for the next order (SLOT_1 and SLOT_3 when the page opens, as in Chapter 13). The checker rejects any plan that changes a ticked slot with PROTECTED_SLOT, whatever the order text says. Typing "leave slot 1 unchanged" without ticking the box is only a request to the model, not a rule the checker enforces.

The "Gripper fault, next order" tick boxes make the gripper fail once in the next order, as in scenarios 4 and 5 of the demo. "The pick fails" makes the next pick come up empty. "The part slips" makes the held part fall back into its bin (the bin the capability file names for it) at the next move. With the closed loop, the real model then has to notice the failure and recover, which takes a few more model calls. The boxes clear when the order is sent.

```
.venv\Scripts\python scripts\chat.py
```

It needs `GROQ_API_KEY` (see below) and opens `http://127.0.0.1:8765/` in the browser. Stop it with Ctrl+C. Every order uses the Groq free-tier limit: the open loop makes one model call, the closed loop one call per step (about ten for the Chapter 13 order). The server only listens on your own computer. `--port`, `--model`, `--delay` and `--no-open` change the defaults. Every order also writes a run log to `demo_logs/`, so `scripts\view.py` can replay it.

The cell cannot place a part into a bin, so an order like "put it back in the bin" is rejected by the checker (BAD_POSITION). Parts go to a tray slot or the return position.

`--live` runs the order of Chapter 13 once with the real model on Groq (`openai/gpt-oss-120b`, temperature 0, JSON mode), in the closed loop. It shows the raw answer of the model, the verdict of the checker and every step. `--variant open` makes a single model call. `--delay` sets the seconds between calls (2.5 by default, as in the model tests). Every live run uses the free-tier limit of the key's owner, which we also need for the experiment, so run it only when you mean to. If the key is missing or the call fails, the demo says why and offers the scripted run instead.

```
.venv\Scripts\python scripts\demo.py --live
```

### Local model with Ollama

Without a Groq key, the live demo and the chat mode can use a local model instead, through [Ollama](https://ollama.com). It runs on your own computer, needs no API key and uses no free-tier limit. Install Ollama, pull the model once and add `--local`:

```
ollama pull qwen3:8b
.venv\Scripts\python scripts\chat.py --local
.venv\Scripts\python scripts\demo.py --live --local
```

The default local model is `qwen3:8b` (5.2 GB). `--model` picks any other model you have pulled, for example `--local --model gpt-oss:20b`. A local model on a laptop is much slower than Groq, often minutes for one call, and a small model makes more mistakes. The checker still tests every plan before anything moves. The local model is only for the demo and the chat mode. The experiment keeps the model of the Design Document (DD17).

## API keys

The model client reads the key only from the environment variable `GROQ_API_KEY`, or from a local `.env` file with a line `GROQ_API_KEY=...`. Both `.env` and `demo_logs/` are ignored by git, and the run log removes the key from every record. To set the key on Windows, run `setx GROQ_API_KEY "your key"` once and open a new terminal. Never put a key in any other file in this repository, and check `git status` before every commit anyway.

## Working together

Read [CONTRIBUTING.md](CONTRIBUTING.md) before your first change.

## Licence

The code is released under the MIT licence, see [LICENSE](LICENSE). The 3D view uses three.js, which has its own MIT licence in [src/ssm3/vendor/three.LICENSE](src/ssm3/vendor/three.LICENSE).
