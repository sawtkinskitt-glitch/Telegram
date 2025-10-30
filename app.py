from flask import Flask, render_template, jsonify, request
from db_manager import AccountManager, SafetyMetricsManager, init_database, get_db_connection
from utils.safety_guardian import guardian
import os
from datetime import datetime
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64
import secrets

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())

ENCRYPTION_KEY = os.environ.get('ACCOUNT_ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    print("=" * 80)
    print("🔒 SECURITY ERROR: ACCOUNT_ENCRYPTION_KEY environment variable is required!")
    print("=" * 80)
    print("This key is needed to encrypt/decrypt session data securely.")
    print("Without it, all encrypted account sessions will be lost on restart.")
    print()
    print("To fix this:")
    print("1. Generate a key: python -c 'import base64, os; print(base64.b64encode(os.urandom(32)).decode())'")
    print("2. Add it to Replit Secrets as ACCOUNT_ENCRYPTION_KEY")
    print("3. Restart the application")
    print("=" * 80)
    import sys
    sys.exit(1)

init_database()

def encrypt_data(plaintext):
    """Encrypt data using AES-256-GCM"""
    key = base64.b64decode(ENCRYPTION_KEY)
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()

def decrypt_data(encrypted):
    """Decrypt data using AES-256-GCM"""
    key = base64.b64decode(ENCRYPTION_KEY)
    aesgcm = AESGCM(key)
    data = base64.b64decode(encrypted)
    nonce = data[:12]
    ciphertext = data[12:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode()

@app.route('/')
def index():
    """Dashboard home"""
    return render_template('index.html')

@app.route('/api/commands')
def get_commands():
    """Get all commands from loaded modules - organized by category"""
    try:
        from command_loader import extract_modules_help
        commands_list = extract_modules_help()
        
        categories = {}
        category_priorities = {
            'Core': 1, 'Profile': 2, 'Info': 3, 'Utility': 4,
            'Messaging': 5, 'Media': 6, 'Advanced': 7, 'Help': 8, 'Other': 9
        }
        
        for cmd in commands_list:
            cat = cmd['category']
            if cat not in categories:
                categories[cat] = {
                    'name': cat,
                    'icon': '📦',
                    'description': f'{cat} commands',
                    'priority': category_priorities.get(cat, 10),
                    'commands': {}
                }
            
            # Use full command as key to avoid duplicates (e.g., "clone", "clone reset", "clone save")
            cmd_key = cmd['command']
            categories[cat]['commands'][cmd_key] = {
                'syntax': cmd['command'],
                'description': cmd['description'],
                'safety': cmd['safety'],
                'module': cmd['module']
            }
        
        return jsonify(categories)
    except Exception as e:
        print(f"Error in /api/commands: {e}")
        return jsonify({}), 500

@app.route('/api/stats')
def get_stats():
    """Get userbot statistics"""
    try:
        from command_loader import extract_modules_help
        commands_data = extract_modules_help()
        
        categories = set(cmd['category'] for cmd in commands_data)
        accounts = AccountManager.get_all_accounts()
        
        safety_counts = {'safe': 0, 'moderate': 0, 'risky': 0}
        for cmd in commands_data:
            safety_counts[cmd['safety']] = safety_counts.get(cmd['safety'], 0) + 1
        
        return jsonify({
            'total_commands': len(commands_data),
            'total_categories': len(categories),
            'total_modules': len(set(cmd['module'] for cmd in commands_data)),
            'total_accounts': len(accounts),
            'active_accounts': sum(1 for acc in accounts if acc.get('is_active')),
            'safety_breakdown': safety_counts,
            'prefix': '.',
            'version': '2.5.0'
        })
    except Exception as e:
        print(f"Error in /api/stats: {e}")
        return jsonify({
            'total_commands': 0,
            'total_categories': 0,
            'safety_breakdown': {'safe': 0, 'moderate': 0, 'risky': 0},
            'prefix': '.',
            'version': '2.5.0'
        }), 500

@app.route('/api/accounts')
def get_accounts():
    """Get all accounts with health metrics"""
    try:
        accounts = AccountManager.get_all_accounts()
        return jsonify({
            'success': True,
            'accounts': accounts,
            'count': len(accounts)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/account/<phone>')
def get_account(phone):
    """Get single account details"""
    try:
        account = AccountManager.get_account_by_phone(phone)
        if not account:
            return jsonify({'success': False, 'error': 'Account not found'}), 404
        return jsonify({'success': True, 'account': account})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/safety/report/<phone>')
def safety_report(phone):
    """Get safety report for account"""
    try:
        report = SafetyMetricsManager.get_safety_report(phone)
        if not report:
            return jsonify({'success': False, 'error': 'Account not found'}), 404
        return jsonify({'success': True, 'report': report})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/safety/floodwaits/<phone>')
def get_floodwaits(phone):
    """Get FloodWait events for account"""
    try:
        events = SafetyMetricsManager.get_active_floodwaits(phone)
        return jsonify({'success': True, 'events': events})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/safety/check/<phone>')
def safety_check(phone):
    """Quick safety check - returns current ban risk and status"""
    try:
        account = AccountManager.get_account_by_phone(phone)
        if not account:
            return jsonify({'success': False, 'error': 'Account not found'}), 404
        
        report = SafetyMetricsManager.get_safety_report(phone)
        metrics = report['metrics'] if report else None
        
        ban_risk = metrics['ban_risk_score'] if metrics else 0
        status = 'healthy' if ban_risk < 40 else ('warning' if ban_risk < 70 else 'critical')
        
        return jsonify({
            'success': True,
            'phone': phone,
            'ban_risk_score': ban_risk,
            'status': status,
            'clones_last_hour': metrics['clones_last_hour'] if metrics else 0,
            'clones_last_day': metrics['clones_last_day'] if metrics else 0,
            'last_updated': metrics['calculated_at'].isoformat() if metrics and metrics.get('calculated_at') else None
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/session/request-code', methods=['POST'])
def request_verification_code():
    """Request Telegram verification code"""
    try:
        data = request.get_json()
        phone = data.get('phone')
        
        if not phone:
            return jsonify({
                'success': False,
                'error': 'Phone number required'
            }), 400
        
        from session_generator import async_request_code
        
        api_id = os.getenv('API_ID')
        api_hash = os.getenv('API_HASH')
        
        if not api_id or not api_hash:
            return jsonify({
                'success': False,
                'error': 'API credentials not configured'
            }), 500
        
        result = async_request_code(phone, api_id, api_hash)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/session/verify-code', methods=['POST'])
def verify_code_and_generate_session():
    """Verify code and generate session string"""
    try:
        data = request.get_json()
        phone = data.get('phone')
        code = data.get('code')
        phone_code_hash = data.get('phone_code_hash')
        password = data.get('password')
        
        if not phone or not code or not phone_code_hash:
            return jsonify({
                'success': False,
                'error': 'Phone, code, and phone_code_hash required'
            }), 400
        
        from session_generator import async_verify_code
        from encryption_service import EncryptionService
        
        api_id = os.getenv('API_ID')
        api_hash = os.getenv('API_HASH')
        
        result = async_verify_code(phone, code, phone_code_hash, api_id, api_hash, password)
        
        if result['success']:
            encryptor = EncryptionService()
            session_encrypted = encryptor.encrypt(result['session_string'])
            api_hash_encrypted = encryptor.encrypt(api_hash)
            
            user_info = result['user_info']
            
            account_id = AccountManager.add_account(
                phone=user_info['phone'],
                session_encrypted=session_encrypted,
                name=f"{user_info['first_name']} {user_info['last_name']}".strip(),
                api_id=api_id,
                api_hash_encrypted=api_hash_encrypted,
                username=user_info['username'],
                first_name=user_info['first_name'],
                profile_photo_url=None
            )
            
            return jsonify({
                'success': True,
                'account_id': account_id,
                'user_info': user_info,
                'message': 'Account added successfully!'
            })
        else:
            return jsonify(result), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/account/add', methods=['POST'])
def add_account():
    """Add new Telegram account with encrypted session"""
    try:
        data = request.get_json()
        
        phone = data.get('phone', '').strip()
        name = data.get('name', '').strip()
        api_id = data.get('api_id', '').strip()
        api_hash = data.get('api_hash', '').strip()
        session_string = data.get('session_string', '').strip()
        
        if not phone or not api_id or not api_hash or not session_string:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        session_encrypted = encrypt_data(session_string)
        api_hash_encrypted = encrypt_data(api_hash)
        
        account_id = AccountManager.add_account(
            phone=phone,
            session_encrypted=session_encrypted,
            name=name or None,
            api_id=api_id,
            api_hash_encrypted=api_hash_encrypted
        )
        
        return jsonify({
            'success': True,
            'message': 'Account added successfully',
            'account_id': account_id
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/account/delete/<int:account_id>', methods=['DELETE'])
def delete_account_by_id(account_id):
    """Delete account by ID"""
    try:
        account = AccountManager.get_account_by_id(account_id)
        if not account:
            return jsonify({'success': False, 'error': 'Account not found'}), 404
        
        AccountManager.delete_account(account['phone'])
        return jsonify({'success': True, 'message': 'Account deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/account/<int:account_id>/toggle', methods=['PATCH'])
def toggle_account_active(account_id):
    """Toggle account active/inactive status"""
    try:
        account = AccountManager.get_account_by_id(account_id)
        if not account:
            return jsonify({'success': False, 'error': 'Account not found'}), 404
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE telegram_accounts
                SET is_active = NOT is_active
                WHERE id = %s
                RETURNING is_active
            """, (account_id,))
            result = cursor.fetchone()
            cursor.close()
            
            new_status = result[0] if result else False
            
        return jsonify({
            'success': True,
            'is_active': new_status,
            'message': f"Account {'activated' if new_status else 'deactivated'}"
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/account/<int:account_id>/set-primary', methods=['PATCH'])
def set_primary_account(account_id):
    """Set account as primary (unsets all others)"""
    try:
        account = AccountManager.get_account_by_id(account_id)
        if not account:
            return jsonify({'success': False, 'error': 'Account not found'}), 404
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE telegram_accounts SET is_primary = FALSE")
            cursor.execute("UPDATE telegram_accounts SET is_primary = TRUE WHERE id = %s", (account_id,))
            cursor.close()
        
        return jsonify({
            'success': True,
            'message': 'Primary account updated'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/account/<int:account_id>/sync-profile', methods=['POST'])
def sync_account_profile(account_id):
    """Sync profile data from Telegram"""
    try:
        from profile_sync import ProfileSyncService
        
        result = ProfileSyncService.sync_account_profile_sync(account_id)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'Moon-Userbot Dashboard'
    })

@app.route('/api/safety/limits/<int:account_id>')
def get_safety_limits(account_id):
    """Get rate limit quotas and ban risk for an account"""
    try:
        status = guardian.get_quota_status(account_id)
        return jsonify({'success': True, **status})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/safety/history')
def get_safety_history():
    """Get clone attempt history"""
    try:
        account_id = request.args.get('account_id', type=int)
        limit = request.args.get('limit', 50, type=int)
        history = guardian.get_clone_history(account_id, limit)
        return jsonify({'success': True, 'history': history})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/safety/floodwait/<int:account_id>')
def get_floodwait_status(account_id):
    """Get FloodWait status for an account"""
    try:
        status = guardian.get_floodwait_status(account_id)
        return jsonify({'success': True, 'floodwait': status})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
