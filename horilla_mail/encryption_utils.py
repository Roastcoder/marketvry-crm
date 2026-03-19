"""
Encryption utilities for securely storing and retrieving sensitive data.

This module provides functions for encrypting and decrypting passwords
and other sensitive information using the Fernet symmetric encryption algorithm.
"""

import logging
import os

from cryptography.fernet import Fernet
from django.conf import settings

# First-party (Horilla)
from horilla.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


def get_or_create_encryption_key():
    """
    Get encryption key from environment or generate new one.
    This is safe for open source projects.
    """
    key = os.environ.get("FIELD_ENCRYPTION_KEY")

    if not key:
        key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key:
        # For development: try to read from local file
        key_file = os.path.join(settings.BASE_DIR, ".encryption_key")

        if os.path.exists(key_file):
            with open(key_file, "r", encoding="utf-8") as f:
                key = f.read().strip()
        else:
            key = Fernet.generate_key().decode()
            with open(key_file, "w", encoding="utf-8") as f:
                f.write(key)
            logger.info("New encryption key generated and saved to %s", key_file)

    return key


def get_cipher():
    """Get Fernet cipher instance"""
    key = get_or_create_encryption_key()
    if not key:
        raise ImproperlyConfigured("Could not get or create encryption key")
    return Fernet(key.encode())


def encrypt_password(plain_password):
    """Encrypt password"""
    if not plain_password:
        return None
    cipher = get_cipher()
    return cipher.encrypt(plain_password.encode()).decode()


def decrypt_password(encrypted_password):
    """Decrypt password"""
    if not encrypted_password:
        return None
    cipher = get_cipher()
    try:
        return cipher.decrypt(encrypted_password.encode()).decode()
    except Exception as e:
        raise ValueError(
            f"Failed to decrypt password. You may be using a different encryption key. Error: {e}"
        ) from e
