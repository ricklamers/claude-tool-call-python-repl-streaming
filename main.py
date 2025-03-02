import os
import sys
import signal
import subprocess
import anthropic
from typing import List, Dict, Any, Optional, Union
import io
import contextlib
import json
import traceback
import threading
import time
import readline  # For better input handling

# Debug mode flag - set to False to hide debug prints
DEBUG = False

# Configure signal handling for graceful shutdown
def signal_handler(sig, frame):
    print("\nShutting down gracefully...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# Initialize Anthropic client
client = anthropic.Anthropic()
MODEL = "claude-3-7-sonnet-20250219"

class PythonREPL:
    """A persistent Python REPL for executing code from Claude"""
    
    def __init__(self):
        # Create a dictionary to store the persistent globals
        self.globals_dict = {
            "__builtins__": __builtins__,
            "__name__": "__main__",
            "__doc__": None,
        }
        
    def execute(self, code: str) -> dict:
        """
        Execute Python code in the persistent environment and capture stdout/stderr
        
        Returns:
            dict: Contains 'stdout', 'stderr', and 'error' keys
        """
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        result = {
            "stdout": "",
            "stderr": "",
            "error": None
        }
        
        try:
            # Capture stdout and stderr
            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                # Execute the code in the persistent globals dictionary
                exec(code, self.globals_dict)
                
            result["stdout"] = stdout_capture.getvalue()
            result["stderr"] = stderr_capture.getvalue()
            
        except Exception as e:
            # Capture the full traceback
            result["error"] = traceback.format_exc()
            result["stderr"] = stderr_capture.getvalue()
            
        return result

class ClaudeChat:
    def __init__(self, model: str = MODEL):
        self.client = client
        self.model = model
        self.python_repl = PythonREPL()
        self.messages = []
        self.last_assistant_message = None
        self.output_char_limit = 4000  # Character limit for output display
        
    def add_user_message(self, content: str):
        """Add a user message to the conversation"""
        self.messages.append({
            "role": "user",
            "content": content
        })
    
    def add_tool_result(self, tool_use_id: str, content: Union[str, List], is_error: bool = False):
        """Add a tool result to the conversation"""
        # Create the tool result content block
        tool_result = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content,
            "is_error": is_error
        }
        
        # Create a new user message with just the tool result
        self.messages.append({
            "role": "user",
            "content": [tool_result]
        })
    
    def process_thinking(self, thinking: str):
        """Process and display the thinking content from Claude"""
        print("\033[36m" + thinking + "\033[0m", end="", flush=True)
    
    def _truncate_output(self, text, output_type):
        """Helper to truncate and format output with consistent style"""
        # Trim trailing whitespace
        text = text.rstrip() if text else ""
        
        # Check if truncation is needed
        if len(text) > self.output_char_limit:
            truncated = text[:self.output_char_limit]
            truncation_msg = f"\n[... {output_type} truncated to {self.output_char_limit} characters]"
            return truncated, True, truncation_msg
        return text, False, ""
    
    def _print_output(self, text, output_type, was_truncated, truncation_msg):
        """Helper to print output with appropriate styling"""
        # Define color codes for different output types
        colors = {
            "stdout": "\033[34m",  # Blue
            "stderr": "\033[31m",  # Red
            "error": "\033[31m"    # Red
        }
        color = colors.get(output_type, "\033[0m")
        
        # Print the header
        print(f"{color}[{output_type}]:\033[0m")
        
        # Print the content
        print(text, end="")
        
        # Print truncation message if needed
        if was_truncated:
            print(f"{color}{truncation_msg}\033[0m")
    
    def call_claude(self):
        """Call Claude with the current messages and tools configuration"""
        thinking_content = ""
        text_content = ""
        tool_use_blocks = []
        thinking_signature = ""
        
        # Define thinking budget
        thinking_budget = 16000
        max_tokens = thinking_budget + 4000
        
        # Simple system prompt with very explicit instructions
        # Get installed packages using pip
        import subprocess
        import sys
        
        def get_installed_packages():
            try:
                result = subprocess.run(
                    ["uv", "pip", "list"], 
                    capture_output=True, 
                    text=True, 
                    check=True
                )
                return result.stdout.strip()
            except Exception as e:
                return f"Error getting package list: {str(e)}"
        
        packages = get_installed_packages()
        
        system_prompt = f"""You are a helpful assistant with access to a Python REPL tool.
        
The following Python packages are available in the environment:
{packages}

You can try to install any package by using `subprocess.run(["uv", "pip", "install", "package_name"])`, note we use uv to install packages.

Code you provide will directly be executed and variables will persist between executions. So you can are also allowed to make partial progress on a task.

You can use these packages in your Python code when using the python_repl tool."""
        
        # Define tools with more explicit description
        tools = [
        {
            "name": "python_repl",
            "description": "Execute Python code and return the results. This tool runs code in a persistent Python REPL environment. Variables and functions defined in one execution will be available in subsequent executions. The code is executed in a sandboxed environment. The tool returns stdout, stderr, and any errors. Use this tool to run calculations, generate visualizations, process data, or test code.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "code_string": {
                        "type": "string",
                        "description": "The Python code to execute"
                    }
                },
                "required": [
                    "code_string"
                ]
            }
        }
    ]
        
        try:
            if DEBUG:
                print("\033[34m[DEBUG] Starting Claude API call\033[0m")
                print(f"\033[34m[DEBUG] Message history: {len(self.messages)} messages\033[0m")
            
            # Print the last user message for debugging
            if DEBUG and self.messages and self.messages[-1]["role"] == "user":
                print(f"\033[34m[DEBUG] Last user message: {json.dumps(self.messages[-1], indent=2)}\033[0m")
            
            # Print the tools being sent
            if DEBUG:
                print(f"\033[34m[DEBUG] Tools definition: {json.dumps(tools, indent=2)}\033[0m")
            
            with client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=self.messages,
                tools=tools,
                thinking={"type": "enabled", "budget_tokens": thinking_budget}
            ) as stream:
                # Process the stream
                final_content = []
                current_tool_block = None
                thinking_block = None
                
                for event in stream:
                    # Print raw event for debugging
                    if DEBUG:
                        print(f"\033[34m[DEBUG] Event type: {event}\033[0m")
                    
                    # Handle ThinkingEvent
                    if hasattr(event, 'type') and event.type == 'thinking':
                        thinking_content += event.thinking
                        self.process_thinking(event.thinking)
                    
                    # Handle SignatureEvent to capture the thinking signature
                    elif hasattr(event, 'type') and event.type == 'signature':
                        thinking_signature = event.signature
                    
                    # Handle TextEvent
                    elif hasattr(event, 'type') and event.type == 'text':
                        # If this is the first text event after thinking, add a newline
                        if text_content == "" and thinking_content:
                            print()  # Add a clear separation between thinking and response
                        text_content += event.text
                        print(f"\033[32m{event.text}\033[0m", end="", flush=True)
                    
                    # Handle InputJsonEvent for tool use
                    elif hasattr(event, 'type') and event.type == 'input_json':
                        # Skip empty input_json events
                        if not event.partial_json:
                            continue
                    
                    # Handle Content Block Start for tool use
                    elif hasattr(event, 'type') and event.type == 'content_block_start':
                        if hasattr(event.content_block, 'type') and event.content_block.type == 'tool_use':
                            current_tool_block = {
                                "id": event.content_block.id,
                                "name": event.content_block.name,
                                "input": {}
                            }
                    
                    # Handle Content Block Stop for tool use
                    elif hasattr(event, 'type') and event.type == 'content_block_stop':
                        if (hasattr(event.content_block, 'type') and 
                            event.content_block.type == 'tool_use' and 
                            current_tool_block is not None):
                            # Add the complete input from the stopped block
                            current_tool_block["input"] = event.content_block.input
                            # Check if this tool block is already in our list to avoid duplicates
                            if not any(block["id"] == current_tool_block["id"] for block in tool_use_blocks):
                                tool_use_blocks.append(current_tool_block)
                            current_tool_block = None
                        elif hasattr(event.content_block, 'type') and event.content_block.type == 'thinking':
                            # Store the complete thinking block as is
                            thinking_block = {
                                "type": "thinking",
                                "thinking": event.content_block.thinking,
                                "signature": event.content_block.signature
                            }
                            self.last_thinking_block = thinking_block
                        elif hasattr(event.content_block, 'type') and event.content_block.type == 'redacted_thinking':
                            # Store the redacted_thinking block as is
                            thinking_block = {
                                "type": "redacted_thinking",
                                "data": event.content_block.data
                            }
                            self.last_thinking_block = thinking_block
                    
                    # Handle Message Stop event
                    elif hasattr(event, 'type') and event.type == 'message_stop':
                        # If we get a complete message, store its exact content to reuse in the next API call
                        if hasattr(event, 'message') and hasattr(event.message, 'content'):
                            # Create a properly formatted message to add to our conversation history
                            assistant_message = {
                                "role": "assistant",
                                "content": event.message.content  # Use the exact content structure from the API
                            }
                            self.messages.append(assistant_message)
                            self.last_assistant_message = assistant_message
                            
                            # Extract tool use blocks from the message for execution
                            for block in event.message.content:
                                if hasattr(block, 'type') and block.type == 'tool_use':
                                    if not any(existing_block["id"] == block.id for existing_block in tool_use_blocks):
                                        tool_use_blocks.append({
                                            "id": block.id,
                                            "name": block.name, 
                                            "input": block.input
                                        })
                
                
                # STREAM HAS ENDED

                # Set a default return value in case the stream didn't provide anything
                if not text_content and not tool_use_blocks:
                    print()
                    return None, []
                
                print()
                return text_content, tool_use_blocks
                
        except Exception as e:
            print(f"\033[31mError calling Claude API: {e}\033[0m")
            traceback.print_exc()
            return None, []
    
    def run_tool(self, tool_use_block):
        """Execute the tool specified in the tool use block"""
        tool_name = tool_use_block["name"]
        tool_input = tool_use_block["input"] if "input" in tool_use_block else {}
        tool_id = tool_use_block["id"]
        
        if DEBUG:
            print(f"\033[34m[DEBUG] Running tool: {tool_name}\033[0m")
            print(f"\033[34m[DEBUG] Tool use block: {json.dumps(tool_use_block, indent=2)}\033[0m")
        
        if tool_name == "python_repl":
            # Debug the tool input
            if DEBUG:
                print(f"\n\033[34m[Tool Input Debug]: {json.dumps(tool_input, indent=2)}\033[0m")
            
            # Check if code is in the input
            if not tool_input or "code_string" not in tool_input or not tool_input["code_string"]:
                error_msg = "Error: Missing 'code_string' parameter in python_repl tool input"
                print(f"\033[31m{error_msg}\033[0m")
                
                # If we still don't have a code parameter, return an error
                self.add_tool_result(tool_id, error_msg, is_error=True)
                return
            
            code = tool_input["code_string"]
            # Always print the code being executed
            print(f"\n\033[34m[Executing Python Code...]\033[0m")
            print(f"\033[34m{code}\033[0m")
            
            # Execute the code in our persistent REPL
            result = self.python_repl.execute(code)
            
            # Newline when a tool result is printed
            print()
            
            # Process outputs with our helper methods
            stdout, stdout_truncated, stdout_msg = self._truncate_output(result["stdout"], "stdout")
            stderr, stderr_truncated, stderr_msg = self._truncate_output(result["stderr"], "stderr")
            error, error_truncated, error_msg = self._truncate_output(result["error"], "error")
            
            # Print outputs
            if result["stdout"]:
                self._print_output(stdout, "stdout", stdout_truncated, stdout_msg)
            
            if result["stderr"]:
                self._print_output(stderr, "stderr", stderr_truncated, stderr_msg)
            
            if result["error"]:
                self._print_output(error, "error", error_truncated, error_msg)
                
                # Add the error result to the messages (already truncated)
                self.add_tool_result(tool_id, error, is_error=True)
            else:
                # Construct the tool result content
                tool_content = []
                
                if stdout or stderr:
                    result_text = ""
                    if stdout:
                        result_text += f"[stdout]:\n{stdout}"
                        if stdout_truncated:
                            result_text += stdout_msg
                    
                    if stderr:
                        if result_text:
                            result_text += "\n"
                        result_text += f"[stderr]:\n{stderr}"
                        if stderr_truncated:
                            result_text += stderr_msg
                    
                    tool_content.append({"type": "text", "text": result_text})
                else:
                    # If there's no output, return an empty message
                    tool_content = "No output produced."
                
                # Add the tool result to the messages
                self.add_tool_result(
                    tool_id, 
                    tool_content if isinstance(tool_content, list) else tool_content
                )
                
                if DEBUG:
                    print(f"\033[34m[DEBUG] Added tool result to messages\033[0m")
        else:
            print(f"\033[31mUnknown tool: {tool_name}\033[0m")
            self.add_tool_result(
                tool_id,
                f"Error: Unknown tool '{tool_name}'",
                is_error=True
            )

def main():
    # Clear screen on startup
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print("\033[1;35m")
    print("=" * 80)
    print("    🧠 Claude + Python REPL Interactive Terminal 🧪")
    print("    Using model: " + MODEL)
    print("    Type 'exit', 'quit', or press Ctrl+C to exit")
    print("    For multiline input:")
    print("      - Type '```' on a new line to start multiline mode")
    print("      - Type '```' on a new line when finished")
    print("=" * 80)
    print("\033[0m")
    
    chat = ClaudeChat()
    
    while True:
        try:
            # Get multiline user input
            lines = []
            multiline_mode = False
            
            while True:
                # After the first line, show a continuation prompt in multiline mode
                if lines and multiline_mode:
                    print("\033[1;33m \033[0m", end="")
                else:
                    # Indent the input line for better visual separation from the prompt
                    print("\033[1;33m> \033[0m", end="")
                
                line = input()
                
                # Check for multiline terminator
                if line == "```":
                    if not lines:
                        # If the first line is just ```, start multiline mode
                        multiline_mode = True
                        print("\033[36mMultiline mode activated. Enter '```' on a new line when done.\033[0m")
                        continue
                    else:
                        # End of multiline input
                        break
                
                # Check for exit command
                if not lines and line.lower() in ["exit", "quit"]:
                    print("\nExiting...")
                    return
                
                # Add the line to our collection
                lines.append(line)
                
                # If we're not in multiline mode and the user entered something, we're done
                if not multiline_mode and lines:
                    break
                
                # If the first line is empty, the user didn't enter anything - ask again
                if not lines and not line:
                    break
                
                # We're now in multiline mode
                multiline_mode = True
            
            # Join the lines into a single string
            user_input = "\n".join(lines).strip()
            
            if not user_input:
                continue
            
            # Add the user message to the conversation
            chat.add_user_message(user_input)
            
            # Start conversation loop with Claude
            while True:
                try:
                    # Call Claude API
                    message, tool_use_blocks = chat.call_claude()
                    
                    # If there are no tool use blocks, break out of the loop
                    if not tool_use_blocks:
                        break
                    
                    # Process each tool use block - now deduplicated
                    processed_tool_ids = set()
                    for tool_use_block in tool_use_blocks:
                        # Only process each tool use block once
                        if tool_use_block["id"] not in processed_tool_ids:
                            chat.run_tool(tool_use_block)
                            processed_tool_ids.add(tool_use_block["id"])
                except Exception as e:
                    print(f"\033[31mError in tool processing loop: {e}\033[0m")
                    traceback.print_exc()
                    break
        
        except KeyboardInterrupt:
            print("\nKeyboard interrupt detected. Exiting...")
            break
        except Exception as e:
            print(f"\033[31mAn error occurred: {e}\033[0m")
            traceback.print_exc()

if __name__ == "__main__":
    main()
