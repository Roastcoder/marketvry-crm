"""
Automatic init password generation utility.
Place this file in: <project_root>/horilla/settings/password_utils.py

This module handles password creation automatically on first use.
"""

import os
import secrets
from pathlib import Path


def get_project_root():
    """
    Get the project root directory (where manage.py is located).

    """
    current_file = Path(__file__).resolve()
    settings_directory = current_file.parent  # /project_root/horilla/settings/
    horilla_directory = settings_directory.parent  # /project_root/horilla/
    project_root = horilla_directory.parent  # /project_root/

    manage_py = project_root / "manage.py"
    if not manage_py.exists():
        print(f"Warning: manage.py not found at {manage_py}")

    return project_root


def get_password_file_path():
    """Get the path to the password file."""
    project_root = get_project_root()
    return project_root / ".init_password"


def generate_secure_password():
    """Generate a cryptographically secure password."""
    return secrets.token_urlsafe(32)


def create_password_file():
    """
    Create the password file with a new secure password.
    Returns the generated password.
    """
    password_file = get_password_file_path()
    password = generate_secure_password()

    try:
        # Ensure parent directory exists
        password_file.parent.mkdir(parents=True, exist_ok=True)

        # Write password to file
        with open(password_file, "w", encoding="utf-8") as f:
            f.write(password)

        # Set secure file permissions (Unix/Linux/Mac only)
        try:
            os.chmod(password_file, 0o600)  # Read/write for owner only
        except Exception:
            pass  # Windows doesn't support chmod

        print("Init password auto-generated and saved to .init_password")

    except Exception as e:
        print(e)

    return password


def read_password_from_file():
    """
    Read the password from the file.
    Returns None if file doesn't exist or can't be read.
    """
    password_file = get_password_file_path()

    if not password_file.exists():
        return None

    try:
        with open(password_file, "r", encoding="utf-8") as f:
            password = f.read().strip()
            if password:  # Ensure it's not empty
                return password
    except Exception as e:
        print(e)
    return None


def get_or_create_init_password():
    """
    Main function to get init password.

    Priority:
    1. Environment variable DB_INIT_PASSWORD
    2. Password from .init_password file
    3. Generate new password and save to file

    Returns: The init password string
    """
    # Priority 1: Check environment variable
    password = os.environ.get("DB_INIT_PASSWORD")
    if password:
        return password

    # Priority 2: Check if password file exists
    password = read_password_from_file()
    if password:
        return password

    # Priority 3: Generate and save new password
    return create_password_file()


# For convenience - this is the main function to use
def get_init_password():
    """
    Convenience function - alias for get_or_create_init_password()
    Use this in your settings.py:

    from horilla.settings.password_utils import get_init_password
    DB_INIT_PASSWORD = get_init_password()
    """
    return get_or_create_init_password()
