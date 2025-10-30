"""
Telegram session generator using Pyrogram
"""
import os
import asyncio
from pyrogram import Client
from pyrogram.errors import (
    SessionPasswordNeeded, PhoneCodeInvalid, 
    PhoneCodeExpired, FloodWait
)

_temp_clients_cache = {}

class SessionGenerator:
    """Generate Telegram session strings"""
    
    def __init__(self, api_id, api_hash):
        """Initialize with API credentials"""
        self.api_id = api_id
        self.api_hash = api_hash
        self.temp_clients = _temp_clients_cache
    
    async def request_code(self, phone: str) -> dict:
        """
        Request verification code from Telegram
        
        Returns:
            dict with phone_code_hash and phone for next step
        """
        try:
            client = Client(
                f"temp_{phone}",
                api_id=self.api_id,
                api_hash=self.api_hash,
                phone_number=phone,
                in_memory=True
            )
            
            await client.connect()
            
            sent = await client.send_code(phone)
            phone_code_hash = sent.phone_code_hash
            
            self.temp_clients[phone] = client
            
            return {
                'success': True,
                'phone': phone,
                'phone_code_hash': phone_code_hash,
                'message': f'Verification code sent to {phone}'
            }
            
        except FloodWait as e:
            return {
                'success': False,
                'error': 'rate_limited',
                'message': f'Too many requests. Wait {e.value} seconds.',
                'wait_time': e.value
            }
        except Exception as e:
            return {
                'success': False,
                'error': 'send_code_failed',
                'message': str(e)
            }
    
    async def verify_code(self, phone: str, phone_code: str, phone_code_hash: str, password: str | None = None) -> dict:
        """
        Verify code and generate session string
        
        Returns:
            dict with session_string or error
        """
        try:
            client = self.temp_clients.get(phone)
            if not client:
                return {
                    'success': False,
                    'error': 'session_expired',
                    'message': 'Session expired. Request code again.'
                }
            
            try:
                signed_in = await client.sign_in(phone, phone_code_hash, phone_code)
            except SessionPasswordNeeded:
                if not password:
                    return {
                        'success': False,
                        'error': 'password_required',
                        'message': '2FA password required. Please provide it.'
                    }
                signed_in = await client.check_password(password)
            except PhoneCodeInvalid:
                return {
                    'success': False,
                    'error': 'invalid_code',
                    'message': 'Invalid verification code. Try again.'
                }
            except PhoneCodeExpired:
                return {
                    'success': False,
                    'error': 'code_expired',
                    'message': 'Code expired. Request a new one.'
                }
            
            session_string = await client.export_session_string()
            
            me = await client.get_me()
            
            await client.disconnect()
            
            del self.temp_clients[phone]
            
            return {
                'success': True,
                'session_string': session_string,
                'user_info': {
                    'id': me.id,
                    'first_name': me.first_name or '',
                    'last_name': me.last_name or '',
                    'username': me.username or '',
                    'phone': me.phone_number or phone,
                    'is_premium': me.is_premium or False
                }
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': 'verification_failed',
                'message': str(e)
            }
    
    async def cleanup_temp_client(self, phone: str):
        """Clean up temporary client"""
        client = self.temp_clients.get(phone)
        if client:
            try:
                await client.disconnect()
            except:
                pass
            del self.temp_clients[phone]

def async_request_code(phone: str, api_id: str, api_hash: str) -> dict:
    """Sync wrapper for request_code"""
    generator = SessionGenerator(api_id, api_hash)
    return asyncio.run(generator.request_code(phone))

def async_verify_code(phone: str, phone_code: str, phone_code_hash: str, api_id: str, api_hash: str, password: str | None = None) -> dict:
    """Sync wrapper for verify_code"""
    generator = SessionGenerator(api_id, api_hash)
    return asyncio.run(generator.verify_code(phone, phone_code, phone_code_hash, password))

if __name__ == '__main__':
    print("Session generator module loaded successfully")
