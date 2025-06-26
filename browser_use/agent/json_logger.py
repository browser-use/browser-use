"""
JSON Logger for Browser Use Agent

This module provides structured JSON logging for browser automation sessions.
Each agent run generates a single JSON file with all steps and DOM states.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from browser_use.agent.views import AgentOutput
from browser_use.browser.views import BrowserStateSummary


class AgentJSONLogger:
    """JSON logger for agent sessions"""
    
    def __init__(self, log_dir: str = "./logs", session_name: Optional[str] = None):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Generate session filename with timestamp (including microseconds for uniqueness)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        if session_name:
            self.session_name = f"{session_name}_{timestamp}"
        else:
            self.session_name = f"browser_session_{timestamp}"
        
        self.log_file = self.log_dir / f"{self.session_name}.json"
        
        # Initialize session data
        self.session_data = {
            "session_info": {
                "session_id": self.session_name,
                "start_time": datetime.now().isoformat(),
                "end_time": None,
                "total_steps": 0,
                "success": None,
                "task": None
            },
            "steps": []
        }
        
        # Write initial file
        self._save_to_file()
    
    def log_step(self, 
                 step_number: int,
                 browser_state: BrowserStateSummary,
                 agent_output: AgentOutput) -> None:
        """Log a single step with DOM state and action"""
        
        step_data = {
            "step_number": step_number,
            "timestamp": datetime.now().isoformat(),
            "dom_state": self._extract_dom_state(browser_state),
            "agent_response": self._extract_agent_response(agent_output)
        }
        
        self.session_data["steps"].append(step_data)
        self.session_data["session_info"]["total_steps"] = step_number
        
        # 立即保存，确保不会因为中断而丢失
        self._save_to_file()
    
    def log_error_step(self, step_number: int, error_info: str, browser_state: BrowserStateSummary = None) -> None:
        """记录执行失败的步骤"""
        step_data = {
            "step_number": step_number,
            "timestamp": datetime.now().isoformat(),
            "error": error_info,
            "dom_state": self._extract_dom_state(browser_state) if browser_state else None,
            "agent_response": None
        }
        
        self.session_data["steps"].append(step_data)
        self.session_data["session_info"]["total_steps"] = step_number
        self._save_to_file()
    
    def set_task(self, task: str) -> None:
        """Set the task description"""
        self.session_data["session_info"]["task"] = task
        self._save_to_file()
    
    def finalize_session(self, success: bool = False) -> None:
        """Finalize the session with end time and success status"""
        self.session_data["session_info"]["end_time"] = datetime.now().isoformat()
        self.session_data["session_info"]["success"] = success
        self._save_to_file()
    
    def _extract_dom_state(self, browser_state: BrowserStateSummary) -> Dict[str, Any]:
        """Extract structured DOM state information"""
        if not browser_state:
            return {}
        
        # Extract interactive elements as text (safer approach)
        interactive_elements_text = ""
        if browser_state.element_tree:
            interactive_elements_text = browser_state.element_tree.clickable_elements_to_string(include_attributes=[])
        
        return {
            "url": browser_state.url,
            "title": browser_state.title,
            "scroll_position": {
                "pixels_above": browser_state.pixels_above or 0,
                "pixels_below": browser_state.pixels_below or 0
            },
            "tabs": [
                {
                    "page_id": tab.page_id,
                    "url": tab.url,
                    "title": tab.title
                } for tab in browser_state.tabs
            ] if browser_state.tabs else [],
            "interactive_elements_text": interactive_elements_text,
            "has_screenshot": browser_state.screenshot is not None
        }
    
    def _extract_agent_response(self, agent_output: AgentOutput) -> Dict[str, Any]:
        """Extract structured agent response information"""
        if not agent_output:
            return {}
        
        actions = []
        for action in agent_output.action:
            action_dict = action.model_dump(exclude_unset=True)
            # Get action type and parameters
            action_type = list(action_dict.keys())[0] if action_dict else "unknown"
            action_params = action_dict.get(action_type, {}) if action_dict else {}
            
            actions.append({
                "action_type": action_type,
                "parameters": action_params
            })
        
        return {
            "thinking": agent_output.thinking,
            "evaluation_previous_goal": agent_output.evaluation_previous_goal,
            "memory": agent_output.memory,
            "next_goal": agent_output.next_goal,
            "action": actions,
        }
    
    def _save_to_file(self) -> None:
        """Save session data to JSON file"""
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                json.dump(self.session_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving JSON log: {e}")
    
    def get_log_file_path(self) -> str:
        """Get the path to the log file"""
        return str(self.log_file)


def create_json_logger(log_dir: str = "./logs", session_name: Optional[str] = None) -> AgentJSONLogger:
    """Factory function to create a JSON logger"""
    return AgentJSONLogger(log_dir=log_dir, session_name=session_name)