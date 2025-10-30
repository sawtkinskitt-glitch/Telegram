"""
Load commands from Moon-Userbot modules for web dashboard
"""
import os
import re
from pathlib import Path

def extract_modules_help():
    """Extract commands from all module files"""
    modules_dir = Path('modules')
    commands_data = []
    
    if not modules_dir.exists():
        return []
    
    for module_file in modules_dir.glob('*.py'):
        if module_file.name.startswith('_'):
            continue
            
        try:
            content = module_file.read_text()
            
            match = re.search(r'modules_help\["([^"]+)"\]\s*=\s*\{([^}]+)\}', content, re.DOTALL)
            if match:
                module_name = match.group(1)
                commands_dict_str = match.group(2)
                
                command_matches = re.findall(r'"([^"]+)":\s*"([^"]+)"', commands_dict_str)
                
                for command, description in command_matches:
                    safety = 'safe'
                    if any(keyword in command.lower() or keyword in description.lower() 
                           for keyword in ['spam', 'flood', 'raid', 'delete', 'purge']):
                        safety = 'moderate'
                    if any(keyword in command.lower() or keyword in description.lower()
                           for keyword in ['ban', 'kick', 'restrict']):
                        safety = 'risky'
                    
                    commands_data.append({
                        'module': module_name,
                        'command': command,
                        'description': description,
                        'safety': safety,
                        'category': categorize_module(module_name)
                    })
        except Exception as e:
            print(f"Error loading {module_file.name}: {e}")
            continue
    
    return commands_data

def categorize_module(module_name):
    """Categorize modules"""
    categories = {
        'clone': 'Profile',
        'user_info': 'Info',
        'id': 'Info',
        'ping': 'Utility',
        'help': 'Core',
        'prefix': 'Core',
        'loader': 'Core',
        'updater': 'Core',
        'spam': 'Messaging',
        'purge': 'Messaging',
        'stickers': 'Media',
        'python': 'Advanced',
        'shell': 'Advanced',
        'notes': 'Utility',
        'support': 'Help'
    }
    return categories.get(module_name, 'Other')

if __name__ == '__main__':
    commands = extract_modules_help()
    print(f"Loaded {len(commands)} commands from {len(set(c['module'] for c in commands))} modules")
    for cmd in commands[:5]:
        print(f"  {cmd['command']}: {cmd['description']}")
