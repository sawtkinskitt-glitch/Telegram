from pyrogram import Client
import asyncio

async def generate_session():
    api_id = 22595574
    api_hash = "6f8f406b4cc917a55c639f78be182c8d"
    
    print("🌕 Moon-Userbot - Session Generator")
    print("=" * 50)
    
    phone = input("📱 Enter your phone number (with country code): ")
    
    app = Client("my_account", api_id, api_hash)
    
    try:
        await app.start()
        session_string = app.export_session_string()
        
        print("\n" + "🎉" * 20)
        print("✅ SUCCESS! Your session string:")
        print("🎉" * 20)
        print(session_string)
        print("🎉" * 20)
        print()
        print("📋 Copy this string and add it as STRINGSESSION in Render!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    
    finally:
        await app.stop()

asyncio.run(generate_session())
