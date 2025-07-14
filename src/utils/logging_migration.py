#!/usr/bin/env python3
"""
Script to migrate existing logging calls to structured JSON logging.
This script will help update all logging calls throughout the codebase.
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Common logging patterns to detect and replace
PATTERNS = [
    # Basic logging calls
    (r'logging\.info\((.*?)\)', r'log_event(logger, "info", \1, event_type="info")'),
    (r'logging\.warning\((.*?)\)', r'log_event(logger, "warning", \1, event_type="warning")'),
    (r'logging\.error\((.*?)\)', r'log_event(logger, "error", \1, event_type="error")'),
    (r'logging\.debug\((.*?)\)', r'log_event(logger, "debug", \1, event_type="debug")'),
    
    # Logger instance calls
    (r'logger\.info\((.*?)\)', r'log_event(logger, "info", \1, event_type="info")'),
    (r'logger\.warning\((.*?)\)', r'log_event(logger, "warning", \1, event_type="warning")'),
    (r'logger\.error\((.*?)\)', r'log_event(logger, "error", \1, event_type="error")'),
    (r'logger\.debug\((.*?)\)', r'log_event(logger, "debug", \1, event_type="debug")'),
    
    # Import statements
    (r'import logging', r'from utils.logging_config import get_logger, log_event'),
    (r'from logging import.*', r'from utils.logging_config import get_logger, log_event'),
    (r'logger = logging\.getLogger\(__name__\)', r'logger = get_logger(__name__)'),
    (r'logger = logging\.getLogger\((.*?)\)', r'logger = get_logger(\1)'),
]

def update_file_logging(file_path: Path) -> Tuple[bool, List[str]]:
    """Update logging calls in a single file."""
    changes = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Apply pattern replacements
        for pattern, replacement in PATTERNS:
            matches = re.findall(pattern, content)
            if matches:
                content = re.sub(pattern, replacement, content)
                changes.append(f"Updated {len(matches)} occurrences of {pattern}")
        
        # Check if we need to add imports
        if 'log_event(' in content and 'from utils.logging_config import' not in content:
            # Add import at the top after other imports
            lines = content.split('\n')
            import_line = "from utils.logging_config import get_logger, log_event"
            
            # Find the last import line
            last_import_idx = -1
            for i, line in enumerate(lines):
                if line.strip().startswith('import ') or line.strip().startswith('from '):
                    last_import_idx = i
            
            if last_import_idx >= 0:
                lines.insert(last_import_idx + 1, import_line)
                content = '\n'.join(lines)
                changes.append("Added logging_config import")
        
        # Write back if changes were made
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True, changes
        
        return False, changes
        
    except Exception as e:
        return False, [f"Error processing file: {str(e)}"]

def main():
    """Main migration function."""
    src_dir = Path(__file__).parent.parent
    python_files = list(src_dir.glob('**/*.py'))
    
    # Exclude certain files
    exclude_patterns = [
        'utils/logging_config.py',
        'utils/logging_migration.py',
        '__pycache__',
        '.git',
        'venv',
        'env'
    ]
    
    files_to_process = []
    for file_path in python_files:
        if not any(pattern in str(file_path) for pattern in exclude_patterns):
            files_to_process.append(file_path)
    
    print(f"Found {len(files_to_process)} Python files to process")
    
    updated_files = []
    total_changes = 0
    
    for file_path in files_to_process:
        print(f"Processing: {file_path}")
        was_updated, changes = update_file_logging(file_path)
        
        if was_updated:
            updated_files.append(file_path)
            total_changes += len(changes)
            print(f"  ✓ Updated with {len(changes)} changes")
            for change in changes:
                print(f"    - {change}")
        else:
            print(f"  - No changes needed")
    
    print(f"\nMigration complete!")
    print(f"Updated {len(updated_files)} files with {total_changes} total changes")
    
    if updated_files:
        print("\nUpdated files:")
        for file_path in updated_files:
            print(f"  - {file_path}")

if __name__ == "__main__":
    main()