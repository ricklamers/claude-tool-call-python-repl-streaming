# Claude Python REPL Assistant

<img width="892" alt="Screenshot 2025-02-27 at 10 26 20 PM" src="https://github.com/user-attachments/assets/fe87bf77-ba19-4787-a201-2487a0c9d158" />

This Python script provides an interactive command-line interface that allows you to converse with Claude and execute Python code as needed. It features:

- A persistent Python REPL that maintains variables and state between executions
- Extended thinking/reasoning display with colored output 
- Streaming responses from Claude
- Real-time execution of Python code with stdout/stderr capture

## Requirements
- Python 3.8+
- An Anthropic API key

## Setup

1. Set up your environment variables:
   ```
   export ANTHROPIC_API_KEY="your-api-key-here"
   ```

2. Install the required packages:
   ```
   uv venv
   source .venv/bin/activate
   uv pip install anthropic
   ```
   Note: These instructions assume you're using [uv](https://github.com/astral-sh/uv), a fast Python package installer. If you don't have uv installed, go install it.

   Whatever packages are in your uv environment will be available to Claude.

3. Run the program:
   ```
   python main.py
   ```

## Usage

1. Type your question or prompt and press Enter.

2. If Claude decides it needs to run Python code, it will:
   - Display the code it's about to execute
   - Execute the code in a persistent environment
   - Show the results (stdout/stderr)
   - Continue the conversation based on the results

3. Type `exit` or `quit` at any time to end the program or hit Ctrl+C.

