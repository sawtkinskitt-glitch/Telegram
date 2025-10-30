"""
Sync Telegram profile data (name, username, profile photo)
"""
import asyncio
from pyrogram import Client
from encryption_service import EncryptionService
from db_manager import AccountManager, get_db_connection

class ProfileSyncService:
    """Sync profile data from Telegram"""
    
    @staticmethod
    async def sync_account_profile(account_id: int, phone: str, api_id: str, api_hash: str, session_string: str):
        """
        Fetch and update profile data from Telegram
        
        Returns:
            dict with updated profile data or error
        """
        try:
            client = Client(
                f"sync_{phone}",
                api_id=int(api_id),
                api_hash=api_hash,
                session_string=session_string,
                in_memory=True
            )
            
            await client.start()
            
            me = await client.get_me()
            
            profile_photo_url = None
            if me.photo:
                try:
                    import base64
                    photo_bytes = await client.download_media(me.photo.big_file_id, in_memory=True)
                    if photo_bytes:
                        photo_b64 = base64.b64encode(photo_bytes).decode('utf-8')
                        profile_photo_url = f"data:image/jpeg;base64,{photo_b64}"
                except Exception as e:
                    print(f"Warning: Failed to download profile photo: {e}")
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE telegram_accounts
                    SET first_name = %s,
                        username = %s,
                        profile_photo_url = %s,
                        name = %s,
                        account_status = 'online',
                        last_active = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (
                    me.first_name or '',
                    me.username or '',
                    profile_photo_url,
                    f"{me.first_name or ''} {me.last_name or ''}".strip(),
                    account_id
                ))
                cursor.close()
            
            await client.stop()
            
            return {
                'success': True,
                'profile': {
                    'first_name': me.first_name or '',
                    'last_name': me.last_name or '',
                    'username': me.username or '',
                    'phone': me.phone_number or phone,
                    'is_premium': me.is_premium or False,
                    'profile_photo_url': profile_photo_url
                }
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    @staticmethod
    def sync_account_profile_sync(account_id: int):
        """Sync wrapper - decrypts session and syncs profile"""
        try:
            account = AccountManager.get_account_by_id(account_id)
            if not account:
                return {'success': False, 'error': 'Account not found'}
            
            encryptor = EncryptionService()
            session_string = encryptor.decrypt(account['session_encrypted'])
            api_hash = encryptor.decrypt(account['api_hash_encrypted'])
            
            return asyncio.run(ProfileSyncService.sync_account_profile(
                account_id=account_id,
                phone=account['phone'],
                api_id=account['api_id'],
                api_hash=api_hash,
                session_string=session_string
            ))
        except Exception as e:
            return {'success': False, 'error': str(e)}

if __name__ == '__main__':
    print("Profile sync service loaded")
