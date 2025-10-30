"""
Human Timing Simulation Engine

Implements three types of delays to mimic human behavior:
1. THINKING TIME - Pre-action cognitive delay
2. ACTION TIME - Physical activity duration (typing, navigating)
3. BREAK TIME - Inter-action randomness (context switching, pauses)

Based on 2025 research: Telegram ML detects non-human patterns.
Key finding: "A human cannot physically update their name, bio, and photo
in the same second. Telegram uses this temporal 'impossibility' as a primary flag."
"""

import asyncio
import random
import time
from typing import Optional, Callable, Any

# Use standard library (numpy optional for better distributions)
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("⚠️  numpy not available - using fallback random (less realistic)")


class HumanTimer:
    """
    Simulates human cognitive and physical delays
    Based on statistical distributions, not uniform randomness
    """
    
    # === THINKING TIME PARAMETERS (Pre-action cognitive delay) ===
    THINKING_PARAMS = {
        'default': (5.0, 1.5),           # mean=5s, std=1.5s
        'read_message': (3.0, 1.0),      # Faster - just reading
        'compose_reply': (7.0, 2.0),     # Slower - need to think what to say
        'profile_change': (10.0, 3.0),   # Very slow - important decision
        'clone_decision': (15.0, 5.0),   # Even slower - risky operation
        'group_join': (8.0, 2.5),        # Medium - evaluating group
        'settings_navigate': (6.0, 2.0), # Opening settings, finding option
    }
    
    # === ACTION TIME PARAMETERS (Physical activity duration) ===
    ACTION_PARAMS = {
        'default': (2.0, 0.5),
        'upload_photo': (5.0, 2.0),      # Loading from gallery, selecting
        'navigate_settings': (3.0, 1.0), # Opening settings, finding option
        'delete_photo': (2.0, 0.5),      # Quick tap
        'type_short': (1.5, 0.5),        # Typing < 20 chars
        'type_medium': (3.0, 1.0),       # Typing 20-100 chars
        'type_long': (8.0, 2.0),         # Typing > 100 chars
    }
    
    # === BREAK TIME PARAMETERS (Inter-action randomness) ===
    BREAK_PARAMS = {
        'micro': (1.0, 3.0),             # Quick pause (sent message, reading response)
        'short': (5.0, 15.0),            # Brief distraction (checked notification)
        'medium': (30.0, 120.0),         # Doing something else (browsing, other app)
        'long': (300.0, 900.0),          # Extended break (15-minute "phone down")
        'sleep': (21600, 28800),         # 6-8 hour sleep cycle
    }
    
    @staticmethod
    def _normal_delay(mean: float, std_dev: float, min_val: float = 0.5) -> float:
        """
        Generate delay using normal (Gaussian) distribution
        
        Research: "Human behavior is statistically variable, often following a 
        normal or log-normal distribution... not a uniform random distribution."
        
        Args:
            mean: Average delay time
            std_dev: Standard deviation (spread)
            min_val: Minimum allowed value
        
        Returns:
            float: Delay in seconds
        """
        if HAS_NUMPY:
            delay = np.random.normal(mean, std_dev)
        else:
            # Fallback: approximate normal with triangular distribution
            delay = random.triangular(mean - 2*std_dev, mean + 2*std_dev, mean)
        
        return max(min_val, delay)
    
    @staticmethod
    def _lognormal_delay(min_val: float, max_val: float) -> float:
        """
        Generate delay using log-normal distribution
        
        Research: "For break times, log-normal distribution: most breaks are short,
        with occasional long ones. This mimics real human behavior."
        
        Args:
            min_val: Minimum delay
            max_val: Maximum delay
        
        Returns:
            float: Delay in seconds
        """
        if HAS_NUMPY:
            mean_log = (np.log(min_val) + np.log(max_val)) / 2
            std_log = (np.log(max_val) - np.log(min_val)) / 4
            delay = np.random.lognormal(mean_log, std_log)
        else:
            # Fallback: weighted random favoring shorter delays
            if random.random() < 0.7:  # 70% shorter delays
                delay = random.uniform(min_val, (min_val + max_val) / 2)
            else:  # 30% longer delays
                delay = random.uniform((min_val + max_val) / 2, max_val)
        
        return max(min_val, min(delay, max_val))
    
    # ========== PUBLIC API ==========
    
    async def thinking_delay(self, operation_type: str = 'default') -> float:
        """
        Delay BEFORE starting an action (human reads, thinks, decides)
        
        Research: "A human reads a message, thinks for 2-7 seconds, then decides"
        Implementation: Normal distribution - most delays cluster around mean
        
        Args:
            operation_type: Type of operation (determines thinking time)
        
        Returns:
            float: Actual delay applied (for logging)
        """
        mean, std_dev = self.THINKING_PARAMS.get(
            operation_type, 
            self.THINKING_PARAMS['default']
        )
        
        delay = self._normal_delay(mean, std_dev, min_val=1.0)
        
        await asyncio.sleep(delay)
        return delay
    
    async def typing_simulation(self, text: str, client=None, chat_id=None) -> float:
        """
        Simulates TYPING an action (shows "typing..." indicator)
        
        Research: "typing_duration = len(text) * 0.05 + random.uniform(0.5, 1.5)"
        Why: Humans type ~40-60 WPM, with variance for thinking between words
        
        Args:
            text: Text being typed
            client: Pyrogram client (optional, for typing indicator)
            chat_id: Chat to show typing in (optional)
        
        Returns:
            float: Actual typing duration
        """
        # Calculate realistic typing duration
        base_time = len(text) * 0.05  # ~50 chars/second = 10 WPM typing
        variance = random.uniform(0.5, 2.0)  # Random pauses (thinking between words)
        
        total_duration = base_time + variance
        
        # Cap extremes (nobody types for 10 minutes, or 0.1 seconds)
        total_duration = max(1.0, min(total_duration, 120.0))
        
        # Show typing indicator if client provided
        if client and chat_id:
            try:
                await client.send_chat_action(chat_id, 'typing')
            except:
                pass  # Silently fail if can't show typing
        
        # Type in "bursts" (humans don't type continuously)
        # Simulate: type for 1-3s, pause 0.2-0.5s, repeat
        elapsed = 0
        while elapsed < total_duration:
            burst_time = min(random.uniform(1.0, 3.0), total_duration - elapsed)
            await asyncio.sleep(burst_time)
            elapsed += burst_time
            
            if elapsed < total_duration:
                # Brief pause between bursts (human thinking)
                pause = random.uniform(0.2, 0.5)
                await asyncio.sleep(pause)
                elapsed += pause
        
        return total_duration
    
    async def action_delay(self, action_type: str = 'default') -> float:
        """
        Delay DURING an action (not typing - other operations)
        E.g., uploading a photo, changing settings
        
        Args:
            action_type: Type of action
        
        Returns:
            float: Actual delay applied
        """
        mean, std_dev = self.ACTION_PARAMS.get(
            action_type,
            self.ACTION_PARAMS['default']
        )
        
        delay = self._normal_delay(mean, std_dev, min_val=0.5)
        
        await asyncio.sleep(delay)
        return delay
    
    async def break_delay(self, break_type: str = 'short') -> float:
        """
        Delay AFTER completing an action (human pauses, context-switches)
        
        Research: "A user sends a message, then might check another chat, or 
        put their phone down. This is CRITICAL - bots never 'do nothing', 
        humans constantly do"
        
        Args:
            break_type: Type of break (micro, short, medium, long, sleep)
        
        Returns:
            float: Actual delay applied
        """
        min_delay, max_delay = self.BREAK_PARAMS.get(
            break_type,
            self.BREAK_PARAMS['short']
        )
        
        delay = self._lognormal_delay(min_delay, max_delay)
        
        await asyncio.sleep(delay)
        return delay
    
    async def human_operation(
        self, 
        operation_type: str, 
        action_func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        Wraps ANY operation with full human timing
        
        Flow:
            1. Think (pre-action delay)
            2. Perform action (with typing if applicable)
            3. Micro-break (post-action pause)
        
        Usage:
            result = await timer.human_operation(
                'compose_reply',
                client.send_message,
                chat_id, text
            )
        
        Args:
            operation_type: Type of operation (for thinking time)
            action_func: Async function to execute
            *args, **kwargs: Arguments for action_func
        
        Returns:
            Result from action_func
        """
        # 1. THINKING TIME
        await self.thinking_delay(operation_type)
        
        # 2. ACTION (execute the actual operation)
        if asyncio.iscoroutinefunction(action_func):
            result = await action_func(*args, **kwargs)
        else:
            result = action_func(*args, **kwargs)
        
        # 3. MICRO-BREAK (humans don't chain actions instantly)
        await self.break_delay('micro')
        
        return result


# Global instance
timer = HumanTimer()


# ========== TEST FUNCTION ==========
if __name__ == '__main__':
    import asyncio
    
    async def test_timer():
        print("=" * 70)
        print("Human Timing Simulation - Test")
        print("=" * 70)
        
        # Test 1: Thinking delay
        print("\nTest 1: Thinking delays (5 samples)")
        print("-" * 70)
        for i in range(5):
            start = time.time()
            delay = await timer.thinking_delay('default')
            elapsed = time.time() - start
            print(f"  Sample {i+1}: {elapsed:.2f}s (expected ~5s ± 1.5s)")
        
        # Test 2: Typing simulation
        print("\nTest 2: Typing simulation")
        print("-" * 70)
        text_short = "Hello"
        text_long = "This is a much longer message that will take more time to type"
        
        start = time.time()
        duration = await timer.typing_simulation(text_short)
        elapsed = time.time() - start
        print(f"  Short text ({len(text_short)} chars): {elapsed:.2f}s")
        
        start = time.time()
        duration = await timer.typing_simulation(text_long)
        elapsed = time.time() - start
        print(f"  Long text ({len(text_long)} chars): {elapsed:.2f}s")
        
        # Test 3: Break delays
        print("\nTest 3: Break delays")
        print("-" * 70)
        
        start = time.time()
        delay = await timer.break_delay('micro')
        elapsed = time.time() - start
        print(f"  Micro break: {elapsed:.2f}s (expected 1-3s)")
        
        start = time.time()
        delay = await timer.break_delay('short')
        elapsed = time.time() - start
        print(f"  Short break: {elapsed:.2f}s (expected 5-15s)")
        
        # Test 4: Full operation wrapper
        print("\nTest 4: Full human operation wrapper")
        print("-" * 70)
        
        async def mock_send_message(chat_id, text):
            return f"Sent: {text}"
        
        start = time.time()
        result = await timer.human_operation(
            'compose_reply',
            mock_send_message,
            12345, "Test message"
        )
        elapsed = time.time() - start
        print(f"  Total time: {elapsed:.2f}s (includes thinking + action + break)")
        print(f"  Result: {result}")
        
        print("\n" + "=" * 70)
        print("✅ All timing tests completed!")
        print("=" * 70)
    
    # Run tests
    asyncio.run(test_timer())
