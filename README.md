# SSM3 kitting planner

Code for SSM3, "LLM-guided robotics for flexible manufacturing", a project of the Applied AI programme at NHL Stenden for the Smart Sustainable Manufacturing research group (client: Mrs Johnson).

The system plans order-based kitting with kit correction in a simulated tabletop cell. An operator gives a kit order or a kit change in plain language. An LLM planner turns it into a plan of allowed function calls, a question or a refusal. A checker outside the LLM replays every plan on a copy of the cell state before anything moves, and a fixed, non-LLM baseline handles the same orders so the two can be compared. Only the planner uses a language model. Everything else is fixed Python code.

## Status

Study 1, the model tests (353 runs), is finished. Its task set and checker are in `study1/` and are the first tested code in this repository. Study 2, the main experiment, is next. The simulated cell with two levels per tray slot, the four plan functions, the checker (every code of Table 9 except AMBIGUOUS and RULE_OVERRIDE), the layout comparison of the baseline and the run limits of the orchestrator now work, following Design Document 0.4. The prompt builder, the response parser, the orchestrator loop for both variants, the run logger and the scripted operator also work, tested with a fake planner, so no test calls a language model. The model client (`call_model`), the evaluator and the recipe table are still documented stubs. Some design questions are still open until the client approves the Design Document at Gate A (18 November 2026), so the code does not fix them.

## Layout

```
config/capability_example.json   example capability file from Design Document Chapter 6
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

## API keys

API keys are read from environment variables, for example `GROQ_API_KEY`. Never put a key in a file in this repository. A local `.env` file is ignored by git, but check `git status` before every commit anyway.

## Working together

Read [CONTRIBUTING.md](CONTRIBUTING.md) before your first change.
