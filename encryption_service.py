"""
AES-256-GCM encryption service for Telegram session strings
"""
import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

class EncryptionService:
    """Handle AES-256-GCM encryption for session strings"""
    
    def __init__(self):
        """Initialize with encryption key from environment"""
        key_material = os.getenv('ACCOUNT_ENCRYPTION_KEY')
        if not key_material:
            raise ValueError("ACCOUNT_ENCRYPTION_KEY not found in environment")
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'moon-userbot-salt-v1',
            iterations=100000,
            backend=default_backend()
        )
        self.key = kdf.derive(key_material.encode())
        self.aesgcm = AESGCM(self.key)
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext using AES-256-GCM
        
        Args:
            plaintext: String to encrypt (e.g., session string)
            
        Returns:
            Base64-encoded ciphertext with IV prepended
        """
        if not plaintext:
            raise ValueError("Cannot encrypt empty string")
        
        nonce = os.urandom(12)
        
        ciphertext = self.aesgcm.encrypt(
            nonce, 
            plaintext.encode('utf-8'), 
            None
        )
        
        encrypted_data = nonce + ciphertext
        
        return base64.b64encode(encrypted_data).decode('utf-8')
    
    def decrypt(self, encrypted: str) -> str:
        """
        Decrypt ciphertext using AES-256-GCM
        
        Args:
            encrypted: Base64-encoded ciphertext with IV prepended
            
        Returns:
            Decrypted plaintext string
        """
        if not encrypted:
            raise ValueError("Cannot decrypt empty string")
        
        encrypted_data = base64.b64decode(encrypted.encode('utf-8'))
        
        nonce = encrypted_data[:12]
        ciphertext = encrypted_data[12:]
        
        plaintext = self.aesgcm.decrypt(nonce, ciphertext, None)
        
        return plaintext.decode('utf-8')

if __name__ == '__main__':
    print("Testing encryption service...")
    
    service = EncryptionService()
    
    test_string = "test_session_string_12345"
    print(f"Original: {test_string}")
    
    encrypted = service.encrypt(test_string)
    print(f"Encrypted: {encrypted[:50]}...")
    
    decrypted = service.decrypt(encrypted)
    print(f"Decrypted: {decrypted}")
    
    assert test_string == decrypted, "Encryption/decryption failed!"
    print("✅ Encryption service working correctly!")
