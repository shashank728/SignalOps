import asyncio
import asyncpg
import sys
import ssl

async def main():
    dsns = [
        "postgresql://postgres.prprjtssujaggbfuxlex:Shubham%400269@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres?sslmode=require",
        "postgresql://postgres.prprjtssujaggbfuxlex:%5BShubham%400269%5D@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres?sslmode=require",
    ]
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for dsn in dsns:
        print(f"Connecting {dsn}...")
        try:
            conn = await asyncpg.connect(dsn, timeout=10, ssl=ctx)
            print("Connected!")
            await conn.close()
            break
        except Exception as e:
            print("Error type:", type(e))
            print("Error:", e)

asyncio.run(main())
