from flask import Flask, render_template, jsonify, request
import os
from datetime import datetime
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64
import secrets

# ========== DATABASE IMPORTS (with graceful fallback) ==========
try:
    from db_manager import (
        AccountManager,
        SafetyMetricsManager,
        AnalyticsManager,
        init_database,
        get_db_connection,
    )
    from utils.safety_guardian import guardian
    DB_IMPORTS_AVAILABLE = True
except Exception as e:
    print(f"⚠️  Database modules not available: {e}")
    print("   Dashboard will run in view-only mode")
    DB_IMPORTS_AVAILABLE = False
    # Create dummy init_database function
    def init_database():
        pass

# ========== ANTI-BAN SYSTEM IMPORTS ==========
try:
    from utils.ban_risk_calculator import risk_calculator
    from utils.account_warming import warmer
    from utils.shadowban_detector import detector
    from utils.floodwait_recovery import recovery_manager
    from utils.db import db
    ANTI_BAN_AVAILABLE = True
except ImportError as e:
    print(f"⚠️  Anti-ban modules not fully available: {e}")
    ANTI_BAN_AVAILABLE = False

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())

ENCRYPTION_KEY = os.environ.get('ACCOUNT_ENCRYPTION_KEY')
DATABASE_AVAILABLE = False

# Initialize database (gracefully handle failures)
try:
    if not ENCRYPTION_KEY:
        print("⚠️  WARNING: ACCOUNT_ENCRYPTION_KEY not set - account management features will be limited")
    init_database()
    DATABASE_AVAILABLE = True
    print("✅ Database initialized successfully")
except Exception as db_error:
    print(f"⚠️  Database initialization failed: {db_error}")
    print("   Dashboard will start in limited mode (userbot features only)")
    DATABASE_AVAILABLE = False

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


@app.route('/api/stats/timeseries')
def get_timeseries():
    """Return aggregated dashboard timeseries data"""
    try:
        hours = request.args.get('hours', 24, type=int)
        days = request.args.get('days', 7, type=int)
        data = AnalyticsManager.get_global_timeseries(hours=hours, days=days)
        return jsonify({'success': True, **data})
    except Exception as e:
        print(f"Error in /api/stats/timeseries: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

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


@app.route('/api/accounts/activity')
def get_account_activity():
    """Get per-account activity timeseries for clones and flood waits"""
    try:
        hours = request.args.get('hours', 24, type=int)
        data = AnalyticsManager.get_accounts_activity(hours=hours)
        return jsonify({'success': True, **data})
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
        
        AccountManager.delete_account_by_id(account_id)
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
    """Health check endpoint with process status"""
    import os
    
    # Check if userbot process is running
    userbot_running = False
    userbot_pid = None
    
    if os.path.exists('/tmp/moonuserbot.pid'):
        try:
            with open('/tmp/moonuserbot.pid', 'r') as f:
                userbot_pid = int(f.read().strip())
            # Check if process is alive
            os.kill(userbot_pid, 0)
            userbot_running = True
        except (OSError, ValueError, ProcessLookupError):
            userbot_running = False
    
    return jsonify({
        'status': 'healthy' if userbot_running else 'degraded',
        'timestamp': datetime.now().isoformat(),
        'service': 'Moon-Userbot Dashboard',
        'userbot': {
            'running': userbot_running,
            'pid': userbot_pid
        },
        'details': 'Web server is running' + (' and userbot is active' if userbot_running else ', but userbot is not running')
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

# ========== ANTI-BAN API ENDPOINTS (2025 Research-Based) ==========

@app.route('/api/anti-ban/dashboard-summary/<int:account_id>')
def get_dashboard_summary(account_id):
    """Get comprehensive anti-ban summary for dashboard widget"""
    if not ANTI_BAN_AVAILABLE:
        return jsonify({'success': False, 'error': 'Anti-ban system not available'}), 503
    
    try:
        account_created = db.get(f"account.{account_id}", "created_date", datetime.now().isoformat())
        account_age_days = warmer.get_account_age_days(account_created)
        is_premium = db.get(f"account.{account_id}", "is_premium", False)
        
        risk_score, risk_level, risk_details = risk_calculator.calculate_ban_risk_score(
            db, account_id, account_age_days, is_premium
        )
        
        limits = warmer.get_daily_limits(account_age_days, is_premium)
        today_key = datetime.now().strftime('%Y-%m-%d')
        clones_today = db.get("usage_tracking", f"account.{account_id}.daily_usage.{today_key}.clone", 0)
        is_quarantined = db.get(f"account.{account_id}", "quarantine_mode", False)
        is_recovering, recovery_data = recovery_manager.is_in_recovery_mode(db, account_id)
        fw_stats = recovery_manager.get_floodwait_stats(db, account_id, days=7)
        
        return jsonify({
            'success': True,
            'summary': {
                'account_age_days': account_age_days,
                'is_premium': is_premium,
                'ban_risk': {
                    'score': risk_score,
                    'level': risk_level,
                    'emoji': '✅' if risk_score <= 20 else ('⚠️' if risk_score <= 40 else ('🔴' if risk_score <= 70 else '🚨'))
                },
                'warming': {
                    'phase': limits.get('phase', 'unknown'),
                    'warmed': account_age_days >= 30,
                    'days_remaining': max(0, 30 - account_age_days)
                },
                'usage': {
                    'clones_today': clones_today,
                    'clones_limit': limits.get('clone_operations', 0),
                    'clones_remaining': max(0, limits.get('clone_operations', 0) - clones_today)
                },
                'status': {
                    'quarantined': is_quarantined,
                    'recovering': is_recovering,
                    'operational': not is_quarantined and not is_recovering and risk_score < 70
                },
                'alerts': {
                    'floodwaits_7d': fw_stats.get('total_events', 0),
                    'has_alerts': is_quarantined or is_recovering or risk_score >= 70 or fw_stats.get('total_events', 0) > 0
                }
            }
        })
    except Exception as e:
        print(f"❌ Dashboard summary error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/anti-ban/quarantine/<int:account_id>', methods=['GET', 'POST'])
def manage_quarantine(account_id):
    """Get or set quarantine status"""
    if not ANTI_BAN_AVAILABLE:
        return jsonify({'success': False, 'error': 'Anti-ban system not available'}), 503
    
    try:
        if request.method == 'GET':
            return jsonify({
                'success': True,
                'quarantine': {
                    'active': db.get(f"account.{account_id}", "quarantine_mode", False),
                    'started': db.get(f"account.{account_id}", "quarantine_started"),
                    'reason': db.get(f"account.{account_id}", "quarantine_reason", "Unknown")
                }
            })
        else:
            data = request.get_json()
            action = data.get('action')
            
            if action == 'enable':
                db.set(f"account.{account_id}", "quarantine_mode", True)
                db.set(f"account.{account_id}", "quarantine_started", datetime.now().isoformat())
                db.set(f"account.{account_id}", "quarantine_reason", data.get('reason', 'Manual'))
                return jsonify({'success': True, 'message': 'Quarantine enabled'})
            elif action == 'disable':
                db.set(f"account.{account_id}", "quarantine_mode", False)
                db.remove(f"account.{account_id}", "quarantine_started")
                return jsonify({'success': True, 'message': 'Quarantine disabled'})
            else:
                return jsonify({'success': False, 'error': 'Invalid action'}), 400
    except Exception as e:
        print(f"❌ Quarantine error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
