# check_contacts.py
# python check_contacts.py

import httpx
import asyncio
import json
from config import MANAGERS

async def main():
    async with httpx.AsyncClient() as client:
        for key, mgr in MANAGERS.items():
            token = mgr.get("access_token", "")
            if "ВАШ_ACCESS_TOKEN" in token:
                print(f"[{key}] Пропускаю — нет токена")
                continue

            # Получаем контакты фирмы
            r = await client.get(
                "https://api.ati.su/v1.0/firms/contacts",
                headers={"Authorization": f"Bearer {token}"}
            )
            print(f"\n[{key}] contacts: {r.status_code}")
            try:
                data = r.json()
                print(json.dumps(data, ensure_ascii=False, indent=2))
            except:
                print(r.text[:1000])

            # Также смотрим кто я (текущий контакт)
            r2 = await client.get(
                "https://api.ati.su/v1.0/firms/mycontact",
                headers={"Authorization": f"Bearer {token}"}
            )
            print(f"\n[{key}] mycontact: {r2.status_code}")
            print(r2.text[:500])

asyncio.run(main())