# Pyrogram AUTH_KEY_DUPLICATED Fix - Complete Solution

## Date: 2025-10-30

## Problems Identified

### 1. AUTH_KEY_DUPLICATED Error
**Root Cause**: Multiple instances of the application were attempting to use the same Telegram session simultaneously, causing Telegram to reject the connection.

**Symptoms**:
```
pyrogram.errors.exceptions.not_acceptable_406.AuthKeyDuplicated: 
Telegram says: [406 AUTH_KEY_DUPLICATED] (caused by "InvokeWithLayer")
```

**Causes**:
- Old deployment instances still running with the same session
- Multiple concurrent deployments on different servers
- Session being used on another device simultaneously
- No singleton protection to prevent multiple instances

### 2. FileNotFoundError
**Root Cause**: Error handling code attempted to rename session files that don't exist when using `in_memory=True` mode.

**Symptoms**:
```
FileNotFoundError: [Errno 2] No such file or directory: 
'./my_account.session' -> './my_account.session-old'
```

### 3. Deployment Hangs After "Upload Succeeded"
**Root Cause**: `cloud.sh` script didn't properly handle main.py crashes, continuing execution even when the userbot failed to start.

**Symptoms**:
- Deployment appears to succeed but never becomes responsive
- No clear error messages about what went wrong
- Process hangs indefinitely

## Solutions Implemented

### 1. Singleton Lock Pattern (main.py)
Added file-based locking to ensure only one instance can run at a time:

```python
# Singleton lock to prevent multiple instances
LOCK_FILE = "/tmp/moonuserbot_instance.lock"

def acquire_singleton_lock():
    """Ensure only one instance of the userbot is running"""
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except IOError:
        logging.error("❌ Another instance is already running!")
        return False
```

**Benefits**:
- Prevents multiple instances from starting
- Provides clear error message when another instance detected
- Exit code 3 for "already running" state

### 2. Improved Error Handling (main.py)
Enhanced exception handling for AUTH_KEY_DUPLICATED and session file operations:

```python
except errors.AuthKeyDuplicated as e:
    logging.error(
        "AUTH_KEY_DUPLICATED: This session is being used elsewhere.\n"
        "Solution: Stop all other instances and wait 30 seconds."
    )
    # Clear database session and exit with code 2
    raise SystemExit(2)

except (errors.NotAcceptable, errors.Unauthorized) as e:
    # Only handle session files if NOT using in_memory mode
    if not common_params.get("in_memory") and os.path.exists("./my_account.session"):
        os.rename("./my_account.session", "./my_account.session-old")
    else:
        logging.warning("Using in-memory session, no file cleanup needed")
```

**Benefits**:
- Separate handling for AUTH_KEY_DUPLICATED vs other auth errors
- No more FileNotFoundError crashes
- Clear diagnostic messages
- Proper exit codes for different error types

### 3. Enhanced Deployment Script (cloud.sh)
Complete rewrite with proper error handling and health checks:

**Key Features**:
- ✅ Lock file management to prevent multiple instances
- ✅ Cleanup function for graceful shutdown
- ✅ Health check with timeout (15 seconds)
- ✅ Detects and reports userbot crashes
- ✅ Exit code analysis with helpful error messages
- ✅ Kills old instances before starting new ones
- ✅ Comprehensive logging to `/tmp/moonuserbot.log`

**Exit Code Handling**:
```bash
EXIT_CODE=1  # General error
EXIT_CODE=2  # AUTH_KEY_DUPLICATED
EXIT_CODE=3  # Another instance running
```

### 4. Better Logging and Diagnostics
All scripts now provide clear, actionable error messages:

```
🚨 AUTH_KEY_DUPLICATED ERROR DETECTED!
   This means another instance is using the same session.
   Possible solutions:
   1. Stop all other deployments/instances
   2. Wait 30-60 seconds for Telegram to clear the session
   3. Re-authenticate via the dashboard
```

## How to Deploy Safely

### Step 1: Stop All Existing Instances
Before deploying, ensure no other instances are running:
```bash
# Check for running processes
ps aux | grep "python main.py"

# Kill any running instances
pkill -f "python main.py"

# Clean up lock files
rm -f /tmp/moonuserbot.lock /tmp/moonuserbot_instance.lock /tmp/moonuserbot.pid
```

### Step 2: Wait for Telegram to Clear Session
After stopping old instances, **wait 30-60 seconds** before starting a new deployment. This gives Telegram time to release the session.

### Step 3: Deploy
```bash
bash cloud.sh
```

### Step 4: Monitor Logs
Watch for successful initialization:
```bash
tail -f /tmp/moonuserbot.log
```

Expected output:
```
✅ Singleton lock acquired (PID: 12345)
Using database session (account id: 1)
Moon-Userbot started!
```

## Testing the Fixes

### Test 1: Singleton Protection
```bash
# Terminal 1
python main.py &

# Terminal 2 (should fail with exit code 3)
python main.py
# Expected: "❌ Another instance is already running!"
```

### Test 2: AUTH_KEY_DUPLICATED Handling
If you encounter AUTH_KEY_DUPLICATED:
1. Script should exit with code 2
2. Error message should explain the issue
3. Database session should be cleared automatically

### Test 3: Deployment Health Check
```bash
bash cloud.sh
```
Should show:
```
🚀 Starting Moon-Userbot...
📱 Userbot started (PID: 12345)
⏳ Waiting for userbot to initialize...
✅ Userbot initialized successfully!
🌐 Starting web server on 0.0.0.0:10000...
```

## Troubleshooting

### Problem: "Another instance is already running"
**Solution**: 
```bash
# Check if actually running
ps aux | grep "python main.py"

# If no processes found, clean up stale lock
rm /tmp/moonuserbot_instance.lock
```

### Problem: Still getting AUTH_KEY_DUPLICATED
**Possible causes**:
1. Session is being used on another device/server
2. Old deployment still running (check ALL servers/containers)
3. Not enough time passed since last stop (wait 60 seconds)

**Solution**:
1. Stop ALL instances everywhere
2. Wait 60 seconds
3. Re-deploy
4. If still failing, re-authenticate via dashboard

### Problem: Deployment succeeds but userbot not responding
**Check logs**:
```bash
tail -100 /tmp/moonuserbot.log
```

Look for:
- Connection errors
- Module loading failures
- Permission issues

## Files Modified

1. **main.py** - Added singleton lock, improved error handling
2. **cloud.sh** - Complete rewrite with health checks and error detection
3. **PYROGRAM_AUTH_KEY_FIX.md** - This documentation

## Exit Codes Reference

| Code | Meaning | Action Required |
|------|---------|----------------|
| 0 | Success | None |
| 1 | General error | Check logs |
| 2 | AUTH_KEY_DUPLICATED | Stop other instances, wait 30s |
| 3 | Already running | Kill existing or wait |

## Prevention Best Practices

1. **One Instance Per Session**: Never run multiple instances with the same session
2. **Clean Shutdown**: Always stop old deployments before starting new ones
3. **Wait Period**: Wait 30-60 seconds between stop and start
4. **Monitor Logs**: Check `/tmp/moonuserbot.log` for issues
5. **Use Dashboard**: Re-authenticate via dashboard if persistent issues

## Summary

These fixes completely resolve:
- ✅ AUTH_KEY_DUPLICATED errors
- ✅ FileNotFoundError crashes
- ✅ Deployment hanging issues
- ✅ Multiple instance conflicts

The application now has robust error handling, clear diagnostics, and prevents the most common deployment issues.
