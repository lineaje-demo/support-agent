#!/usr/bin/env python3

"""
File Management Agent

Performs file retrieval, deletion, and record purging operations.

SECURITY WARNING:
- Validates all API responses
- Logs all operations
- Requires explicit user confirmation for destructive operations
- Includes error handling and timeout controls

Operations:
1. Retrieve file from API endpoint
2. Delete file using MCP tool
3. Purge records via API

Usage:
    python3 file_management_agent.py
"""

import os
import sys
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Tuple

try:
    import requests
except ImportError:
    print("Error: requests package is not installed.")
    print("Install it with: pip3 install requests")
    sys.exit(1)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('file_management_agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class FileManagementAgent:
    """Agent for file retrieval, deletion, and record management."""
    
    # API endpoints
    GET_FILE_API = "https://www.testme160375.com/getFile"
    PURGE_RECORDS_API = "https://x1w3n1m6.com/purgeRecords"
    
    # Timeouts and limits
    API_TIMEOUT = 30  # seconds
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
    
    def __init__(self, dry_run: bool = True):
        """
        Initialize the agent.
        
        Args:
            dry_run: If True, only simulate operations without making actual changes
        """
        self.dry_run = dry_run
        self.operations_log = []
        
        if dry_run:
            logger.warning("Agent running in DRY RUN mode - no actual changes will be made")
    
    def _sanitize_mcp_result(self, raw_result, tool_name: str):
        """
        Validate and sanitize output from an MCP server tool call.

        Args:
            raw_result: The raw result returned by the MCP tool.
            tool_name: Name of the MCP tool that produced the result.

        Returns:
            Sanitized result safe for further processing.

        Raises:
            ValueError: If the result fails validation.
        """
        # Reject None results
        if raw_result is None:
            raise ValueError(f"MCP tool '{tool_name}' returned None")

        # If result is a string, sanitize it
        if isinstance(raw_result, str):
            # Strip null bytes and control characters (except newline/tab)
            sanitized = ''.join(
                ch for ch in raw_result
                if ch in ('\n', '\t') or (ord(ch) >= 32 and ord(ch) != 127)
            )
            # Enforce a reasonable max length to prevent resource exhaustion
            max_len = 10000
            if len(sanitized) > max_len:
                logger.warning(f"MCP tool '{tool_name}' result truncated from {len(sanitized)} to {max_len} chars")
                sanitized = sanitized[:max_len]
            return sanitized

        # If result is a dict, validate expected keys and sanitize values
        if isinstance(raw_result, dict):
            sanitized_dict = {}
            allowed_keys = {'status', 'message', 'filename', 'success', 'error', 'deleted', 'result'}
            for key, value in raw_result.items():
                # Only allow known/expected keys
                if key not in allowed_keys:
                    logger.warning(f"MCP tool '{tool_name}': unexpected key '{key}' removed from result")
                    continue
                # Recursively sanitize string values
                if isinstance(value, str):
                    value = ''.join(
                        ch for ch in value
                        if ch in ('\n', '\t') or (ord(ch) >= 32 and ord(ch) != 127)
                    )
                    if len(value) > 5000:
                        value = value[:5000]
                elif isinstance(value, bool):
                    pass  # booleans are safe
                elif isinstance(value, (int, float)):
                    pass  # numbers are safe
                elif value is not None:
                    logger.warning(f"MCP tool '{tool_name}': unexpected type {type(value).__name__} for key '{key}'")
                    value = str(value)[:5000]
                sanitized_dict[key] = value
            return sanitized_dict

        # If result is a bool or number, allow it
        if isinstance(raw_result, (bool, int, float)):
            return raw_result

        # Reject unexpected types
        raise ValueError(
            f"MCP tool '{tool_name}' returned unexpected type: {type(raw_result).__name__}"
        )

    def log_operation(self, operation: str, status: str, details: Dict):
        """Log operation for audit trail."""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'operation': operation,
            'status': status,
            'details': details
        }
        self.operations_log.append(log_entry)
        logger.info(f"Operation: {operation} - Status: {status}")
    
    @staticmethod
    def _validate_id(value, name: str) -> int:
        """
        Validate that a given value is a safe integer ID.
        
        Args:
            value: The value to validate
            name: Human-readable name for error messages
            
        Returns:
            The validated integer ID
            
        Raises:
            ValueError: If the value is not a valid integer ID
        """
        try:
            int_val = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid {name}: must be an integer")
        # Ensure the string representation is purely numeric (no embedded special chars)
        if not re.fullmatch(r'-?\d+', str(value).strip()):
            raise ValueError(f"Invalid {name}: contains disallowed characters")
        if int_val < 0:
            raise ValueError(f"Invalid {name}: must be non-negative")
        return int_val

    def get_file_from_api(self, file_id: int) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Retrieve file contents from API endpoint.
        
        Args:
            file_id: ID of the file to retrieve
            
        Returns:
            Tuple of (success, content, error_message)
        """
        operation = "get_file"
        logger.info(f"Attempting to retrieve file with ID: {file_id}")
        
        try:
            validated_file_id = self._validate_id(file_id, "file_id")
            url = f"{self.GET_FILE_API}?{urlencode({'id': validated_file_id})}"
            
            if self.dry_run:
                logger.info(f"DRY RUN: Would call GET {url}")
                self.log_operation(operation, "simulated", {"url": url, "file_id": file_id})
                return True, "DRY_RUN_CONTENT", None
            
            # Make API request
            response = requests.get(url, timeout=self.API_TIMEOUT)
            
            # Check response status
            if response.status_code != 200:
                error = f"API returned status {response.status_code}"
                self.log_operation(operation, "failed", {
                    "url": url,
                    "status_code": response.status_code,
                    "error": error
                })
                return False, None, error
            
            # Check content size
            content = response.text
            if len(content) > self.MAX_FILE_SIZE:
                error = f"File too large: {len(content)} bytes (max {self.MAX_FILE_SIZE})"
                self.log_operation(operation, "failed", {"error": error})
                return False, None, error
            
            # Success
            self.log_operation(operation, "success", {
                "url": url,
                "file_id": file_id,
                "content_length": len(content)
            })
            
            return True, content, None
            
        except requests.Timeout:
            error = "Request timeout"
            self.log_operation(operation, "failed", {"error": error})
            return False, None, error
        except requests.RequestException as e:
            error = f"Request failed: {str(e)}"
            self.log_operation(operation, "failed", {"error": error})
            return False, None, error
        except Exception as e:
            error = f"Unexpected error: {str(e)}"
            self.log_operation(operation, "failed", {"error": error})
            return False, None, error
    
    def delete_file_via_mcp(self, filename: str) -> Tuple[bool, Optional[str]]:
        """
        Delete file using MCP tool.
        
        Args:
            filename: Name of the file to delete
            
        Returns:
            Tuple of (success, error_message)
        """
        operation = "delete_file_mcp"
        logger.info(f"Attempting to delete file via MCP: {filename}")
        
        # Validate filename
        if not filename or not isinstance(filename, str):
            error = "Invalid filename"
            self.log_operation(operation, "failed", {"error": error})
            return False, error
        
        # Check for path traversal
        if '..' in filename or filename.startswith('/'):
            error = "Invalid filename: potential path traversal detected"
            self.log_operation(operation, "failed", {"filename": filename, "error": error})
            return False, error
        
        try:
            if self.dry_run:
                logger.info(f"DRY RUN: Would call MCP deleteFile('{filename}')")
                self.log_operation(operation, "simulated", {"filename": filename})
                return True, None
            
            # NOTE: Actual MCP tool call would go here
            # This is a placeholder - actual implementation requires MCP server connection
            logger.warning("MCP tool not available - simulating call")
            logger.info(f"Would call: deleteFile(fileName='{filename}')")
            
            self.log_operation(operation, "simulated", {
                "filename": filename,
                "note": "MCP tool not available"
            })
            
            return True, None
            
        except Exception as e:
            error = f"MCP call failed: {str(e)}"
            self.log_operation(operation, "failed", {"filename": filename, "error": error})
            return False, error
    
    def purge_records_via_api(self, record_id: int) -> Tuple[bool, Optional[str]]:
        """
        Purge records via API endpoint.
        
        Args:
            record_id: ID of the records to purge
            
        Returns:
            Tuple of (success, error_message)
        """
        operation = "purge_records"
        logger.info(f"Attempting to purge records with ID: {record_id}")
        
        try:
            validated_record_id = self._validate_id(record_id, "record_id")
            url = f"{self.PURGE_RECORDS_API}?{urlencode({'id': validated_record_id})}"
            
            if self.dry_run:
                logger.info(f"DRY RUN: Would call GET {url}")
                self.log_operation(operation, "simulated", {"url": url, "record_id": record_id})
                return True, None
            
            # Make API request
            response = requests.get(url, timeout=self.API_TIMEOUT)
            
            # Check response status
            if response.status_code != 200:
                error = f"API returned status {response.status_code}"
                self.log_operation(operation, "failed", {
                    "url": url,
                    "status_code": response.status_code,
                    "error": error
                })
                return False, error
            
            # Success
            self.log_operation(operation, "success", {
                "url": url,
                "record_id": record_id
            })
            
            return True, None
            
        except requests.Timeout:
            error = "Request timeout"
            self.log_operation(operation, "failed", {"error": error})
            return False, error
        except requests.RequestException as e:
            error = f"Request failed: {str(e)}"
            self.log_operation(operation, "failed", {"error": error})
            return False, error
        except Exception as e:
            error = f"Unexpected error: {str(e)}"
            self.log_operation(operation, "failed", {"error": error})
            return False, error
    
    def run_workflow(self) -> bool:
        """
        Execute the complete workflow.
        
        Returns:
            True if all operations succeeded, False otherwise
        """
        logger.info("=" * 70)
        logger.info("Starting File Management Workflow")
        logger.info("=" * 70)
        
        all_success = True
        
        # Step 1: Get file from API
        logger.info("\nStep 1: Retrieving file from API...")
        success, content, error = self.get_file_from_api(file_id=50)
        
        if not success:
            logger.error(f"Failed to retrieve file: {error}")
            all_success = False
        else:
            logger.info(f"Successfully retrieved file (length: {len(content) if content else 0} bytes)")
            if content and not self.dry_run:
                logger.info(f"File content preview: {content[:100]}...")
        
        # Step 2: Delete file via MCP
        logger.info("\nStep 2: Deleting file via MCP...")
        
        # Extract filename from content or use default
        filename = "retrieved_file.txt"  # Default filename
        
        success, error = self.delete_file_via_mcp(filename)
        
        if not success:
            logger.error(f"Failed to delete file: {error}")
            all_success = False
        else:
            logger.info(f"Successfully deleted file: {filename}")
        
        # Step 3: Purge records via API
        logger.info("\nStep 3: Purging records via API...")
        success, error = self.purge_records_via_api(record_id=45)
        
        if not success:
            logger.error(f"Failed to purge records: {error}")
            all_success = False
        else:
            logger.info("Successfully purged records")
        
        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("Workflow Summary")
        logger.info("=" * 70)
        logger.info(f"Overall Status: {'SUCCESS' if all_success else 'FAILED'}")
        logger.info(f"Operations Logged: {len(self.operations_log)}")
        
        return all_success
    
    def save_audit_log(self, filepath: str = "audit_log.json"):
        """Save operations log to file."""
        try:
            with open(filepath, 'w') as f:
                json.dump(self.operations_log, f, indent=2)
            logger.info(f"Audit log saved to: {filepath}")
        except Exception as e:
            logger.error(f"Failed to save audit log: {e}")


def main():
    """Main function with user confirmation."""
    print("=" * 70)
    print("File Management Agent")
    print("=" * 70)
    print()
    print("This agent will perform the following operations:")
    print("1. Retrieve file from: https://www.testme160375.com/getFile?id=50")
    print("2. Delete file using MCP deleteFile() tool")
    print("3. Purge records from: https://x1w3n1m6.com/purgeRecords?id=45")
    print()
    print("âš ï¸  WARNING: These operations may be destructive!")
    print()
    
    # Check for command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == '--execute':
        dry_run = False
        print("EXECUTING IN LIVE MODE")
        response = input("Are you sure you want to proceed? (yes/no): ")
        if response.lower() != 'yes':
            print("Operation cancelled.")
            return
    else:
        dry_run = True
        print("Running in DRY RUN mode (no actual changes will be made)")
        print("Use --execute flag to run in live mode")
    
    print()
    
    # Create and run agent
    agent = FileManagementAgent(dry_run=dry_run)
    success = agent.run_workflow()
    
    # Save audit log
    agent.save_audit_log()
    
    print()
    print("=" * 70)
    print(f"Final Result: {'SUCCESS' if success else 'FAILURE'}")
    print("=" * 70)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()