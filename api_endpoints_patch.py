# ANTI-BAN API ENDPOINTS TO ADD TO app.py
# Add this before the final "if __name__ == '__main__':" line

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
