"""
Migrate existing STRINGSESSION from environment to encrypted database
"""
import os
from encryption_service import EncryptionService
from db_manager import AccountManager

def migrate_existing_session():
    """Import STRINGSESSION from environment into database"""
    
    print("🔄 Starting session migration...")
    
    session_string = os.getenv('STRINGSESSION')
    if not session_string:
        print("⚠️  No STRINGSESSION found in environment - skipping migration")
        return False
    
    api_id = os.getenv('API_ID')
    api_hash = os.getenv('API_HASH')
    
    if not api_id or not api_hash:
        print("⚠️  API_ID or API_HASH missing - skipping migration")
        return False
    
    print(f"✅ Found session string ({len(session_string)} chars)")
    print(f"✅ API_ID: {api_id}")
    
    encryptor = EncryptionService()
    
    print("🔐 Encrypting session string...")
    session_encrypted = encryptor.encrypt(session_string)
    
    print("🔐 Encrypting API hash...")
    api_hash_encrypted = encryptor.encrypt(api_hash)
    
    print("💾 Storing encrypted session in database...")
    account_id = AccountManager.add_account(
        phone="migrated",
        session_encrypted=session_encrypted,
        name="Primary Account",
        api_id=api_id,
        api_hash_encrypted=api_hash_encrypted
    )
    
    from db_manager import get_db_connection
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE telegram_accounts 
            SET is_primary = TRUE,
                first_name = 'Primary',
                account_status = 'active'
            WHERE id = %s
        """, (account_id,))
        cursor.close()
    
    print(f"✅ Migrated account ID: {account_id}")
    print("✅ Marked as primary account")
    
    test_decrypt = encryptor.decrypt(session_encrypted)
    assert test_decrypt == session_string, "Decryption verification failed!"
    print("✅ Encryption verified successfully")
    
    return True

if __name__ == '__main__':
    try:
        success = migrate_existing_session()
        if success:
            print("\n✅ Migration complete!")
        else:
            print("\n⚠️  Migration skipped - no session found")
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
