import json
import os
from datetime import datetime
import aiofiles
from pathlib import Path
from config import BASE_DIR
import time
from typing import List, Optional
import logging

# Пути к JSON файлам
DATABASE_DIR = BASE_DIR / "database"
ACCOUNTS_FILE = DATABASE_DIR / "accounts.json"
GROUPS_FILE = DATABASE_DIR / "groups.json"
POSTS_FILE = DATABASE_DIR / "posts.json"
SETTINGS_FILE = DATABASE_DIR / "settings.json"
BULK_GROUPS_FILE = DATABASE_DIR / "bulk_groups.json"

# Создаем директорию для базы данных
DATABASE_DIR.mkdir(parents=True, exist_ok=True)

# Структура по умолчанию для JSON файлов
DEFAULT_ACCOUNTS = {"accounts": []}
DEFAULT_GROUPS = {"groups": []}
DEFAULT_POSTS = {"posts": []}
DEFAULT_SETTINGS = {
    "settings": {
        "default_delay": "30",
        "max_threads": "5",
        "max_retries": "3"
    }
}
DEFAULT_BULK_GROUPS = {"bulk_groups": []}

async def init_db():
    """Инициализация JSON файлов базы данных"""
    files = {
        ACCOUNTS_FILE: DEFAULT_ACCOUNTS,
        GROUPS_FILE: DEFAULT_GROUPS,
        POSTS_FILE: DEFAULT_POSTS,
        SETTINGS_FILE: DEFAULT_SETTINGS,
        BULK_GROUPS_FILE: DEFAULT_BULK_GROUPS
    }
    
    for file_path, default_data in files.items():
        if not file_path.exists():
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(default_data, ensure_ascii=False, indent=4))

class Database:
    @staticmethod
    async def _read_json(file_path: Path) -> dict:
        """Чтение JSON файла"""
        try:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                return json.loads(content)
        except FileNotFoundError:
            return {}

    @staticmethod
    async def _write_json(file_path: Path, data: dict):
        """Запись в JSON файл"""
        async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=4))

    @staticmethod
    async def add_account(phone: str, session_file: str):
        """Добавление нового аккаунта"""
        data = await Database._read_json(ACCOUNTS_FILE)
        accounts = data.get("accounts", [])
        
        # Генерируем новый ID
        new_id = max([acc.get("id", 0) for acc in accounts], default=0) + 1
        
        account = {
            "id": new_id,
            "phone": phone,
            "session_file": f"{phone}.session",
            "status": "active",  # active, frozen, banned
            "last_used": None,
            "created_at": int(time.time())
        }
        
        accounts.append(account)
        data["accounts"] = accounts
        await Database._write_json(ACCOUNTS_FILE, data)

    @staticmethod
    async def get_active_accounts():
        """Получение активных аккаунтов"""
        data = await Database._read_json(ACCOUNTS_FILE)
        return [acc for acc in data.get("accounts", []) if acc["status"] == "active"]

    @staticmethod
    async def update_account_status(account_id: int, status: str):
        """Обновление статуса аккаунта"""
        data = await Database._read_json(ACCOUNTS_FILE)
        accounts = data.get("accounts", [])
        
        for account in accounts:
            if account["id"] == account_id:
                account["status"] = status
                account["last_used"] = int(time.time())
                break
                
        data["accounts"] = accounts
        await Database._write_json(ACCOUNTS_FILE, data)

    @staticmethod
    async def get_account_by_id(account_id: int):
        """Получение аккаунта по ID"""
        data = await Database._read_json(ACCOUNTS_FILE)
        for account in data.get("accounts", []):
            if account["id"] == account_id:
                return account
        return None

    @staticmethod
    async def delete_account(account_id: int):
        """Удаление аккаунта"""
        data = await Database._read_json(ACCOUNTS_FILE)
        accounts = data.get("accounts", [])
        data["accounts"] = [acc for acc in accounts if acc["id"] != account_id]
        await Database._write_json(ACCOUNTS_FILE, data)

    @staticmethod
    async def add_group(group_id: str, title: str, username: str = None, invite_link: str = None):
        """Добавление новой группы"""
        data = await Database._read_json(GROUPS_FILE)
        groups = data.get("groups", [])
        
        # Генерируем новый ID
        new_id = max([group.get("id", 0) for group in groups], default=0) + 1
        
        group = {
            "id": new_id,
            "group_id": group_id,
            "title": title,
            "username": username,
            "invite_link": invite_link,
            "status": "active",
            "last_post": None,
            "created_at": int(time.time())
        }
        
        # Обновляем существующую группу или добавляем новую
        updated = False
        for i, existing_group in enumerate(groups):
            if existing_group["group_id"] == group_id:
                groups[i] = group
                updated = True
                break
                
        if not updated:
            groups.append(group)
            
        data["groups"] = groups
        await Database._write_json(GROUPS_FILE, data)

    @staticmethod
    async def get_active_groups():
        """Получение активных групп"""
        data = await Database._read_json(GROUPS_FILE)
        return sorted(
            [g for g in data.get("groups", []) if g["status"] == "active"],
            key=lambda x: x["title"]
        )

    @staticmethod
    async def delete_group(group_id: int):
        """Удаление группы"""
        data = await Database._read_json(GROUPS_FILE)
        groups = data.get("groups", [])
        data["groups"] = [g for g in groups if g["id"] != group_id]
        await Database._write_json(GROUPS_FILE, data)

    @staticmethod
    async def get_group_by_group_id(group_id: str):
        """Получение группы по group_id"""
        data = await Database._read_json(GROUPS_FILE)
        for group in data.get("groups", []):
            if str(group["group_id"]) == str(group_id):
                return group
        return None

    @staticmethod
    async def update_group_status(group_id: str, status: str):
        """Обновление статуса группы"""
        data = await Database._read_json(GROUPS_FILE)
        groups = data.get("groups", [])
        
        for group in groups:
            if group["group_id"] == group_id:
                group["status"] = status
                break
                
        data["groups"] = groups
        await Database._write_json(GROUPS_FILE, data)

    @staticmethod
    async def add_post(content: str) -> int:
        """Добавление нового поста"""
        data = await Database._read_json(POSTS_FILE)
        posts = data.get("posts", [])
        
        # Генерируем новый ID
        new_id = max([post.get("id", 0) for post in posts], default=0) + 1
        
        post = {
            "id": new_id,
            "content": content,
            "created_at": int(time.time())
        }
        
        posts.append(post)
        data["posts"] = posts
        await Database._write_json(POSTS_FILE, data)
        
        return new_id

    @staticmethod
    async def get_setting(key: str) -> str:
        """Получение значения настройки"""
        data = await Database._read_json(SETTINGS_FILE)
        return data.get("settings", {}).get(key)

    @staticmethod
    async def update_setting(key: str, value: str):
        """Обновление настройки"""
        data = await Database._read_json(SETTINGS_FILE)
        settings = data.get("settings", {})
        settings[key] = str(value)
        data["settings"] = settings
        await Database._write_json(SETTINGS_FILE, data)

    @staticmethod
    async def get_all_settings() -> dict:
        """Получение всех настроек"""
        data = await Database._read_json(SETTINGS_FILE)
        return data.get("settings", {})

    @staticmethod
    async def add_scheduled_post(
        message_data: dict,
        groups: List[int],
        accounts: List[int],
        schedule_time: int
    ) -> int:
        """Добавление отложенного поста"""
        data = await Database._read_json(POSTS_FILE)
        posts = data.get("posts", [])
        
        # Генерируем новый ID
        new_id = max([post.get("id", 0) for post in posts], default=0) + 1
        
        post = {
            "id": new_id,
            "message": message_data,
            "groups": groups,
            "accounts": accounts,
            "schedule_time": schedule_time,  # Время отправки в unix timestamp
            "status": "pending",  # pending, sent, cancelled
            "created_at": int(time.time())
        }
        
        posts.append(post)
        data["posts"] = posts
        await Database._write_json(POSTS_FILE, data)
        return new_id

    @staticmethod
    async def get_pending_posts() -> List[dict]:
        """Получение всех отложенных постов со статусом pending"""
        data = await Database._read_json(POSTS_FILE)
        return [
            post for post in data.get("posts", [])
            if post.get("status") == "pending"
        ]

    @staticmethod
    async def get_post_by_id(post_id: int) -> Optional[dict]:
        """Получение поста по ID"""
        data = await Database._read_json(POSTS_FILE)
        for post in data.get("posts", []):
            if post["id"] == post_id:
                return post
        return None

    @staticmethod
    async def update_post_status(post_id: int, status: str):
        """Обновление статуса поста"""
        data = await Database._read_json(POSTS_FILE)
        posts = data.get("posts", [])
        
        for post in posts:
            if post["id"] == post_id:
                post["status"] = status
                break
                
        data["posts"] = posts
        await Database._write_json(POSTS_FILE, data)

    @staticmethod
    async def delete_post(post_id: int):
        """Удаление поста"""
        data = await Database._read_json(POSTS_FILE)
        posts = data.get("posts", [])
        data["posts"] = [p for p in posts if p["id"] != post_id]
        await Database._write_json(POSTS_FILE, data)

    @staticmethod
    async def get_groups() -> List[dict]:
        """Получение всех групп"""
        data = await Database._read_json(GROUPS_FILE)
        return data.get("groups", [])

    @staticmethod
    async def get_accounts() -> List[dict]:
        """Получение всех аккаунтов"""
        data = await Database._read_json(ACCOUNTS_FILE)
        return data.get("accounts", [])

    @staticmethod
    async def get_group_by_id(group_id: str):
        """Получение группы по внутреннему id"""
        data = await Database._read_json(GROUPS_FILE)
        for group in data.get("groups", []):
            if str(group["id"]) == str(group_id):
                return group
        return None

    @staticmethod
    async def add_automated_post(
        message_data: dict,
        groups: List[int],
        accounts: List[int],
        times: List[str]
    ) -> int:
        """Добавление нового автоматизированного поста"""
        data = await Database._read_json(POSTS_FILE)
        posts = data.get("automated_posts", [])
        
        # Генерируем новый ID
        new_id = max([post.get("id", 0) for post in posts], default=0) + 1
        
        post = {
            "id": new_id,
            "message": message_data,
            "groups": groups,
            "accounts": accounts,
            "times": times,  # Список времен для ежедневной отправки
            "status": "active",  # active, paused, deleted
            "created_at": int(time.time())
        }
        
        if "automated_posts" not in data:
            data["automated_posts"] = []
            
        data["automated_posts"].append(post)
        await Database._write_json(POSTS_FILE, data)
        return new_id

    @staticmethod
    async def get_automated_posts() -> List[dict]:
        """Получение всех автоматизированных постов"""
        data = await Database._read_json(POSTS_FILE)
        return data.get("automated_posts", [])

    @staticmethod
    async def get_automated_post_by_id(post_id: int) -> Optional[dict]:
        """Получение автоматизированного поста по ID"""
        data = await Database._read_json(POSTS_FILE)
        for post in data.get("automated_posts", []):
            if post["id"] == post_id:
                return post
        return None

    @staticmethod
    async def update_automated_post(
        post_id: int,
        groups: List[int] = None,
        accounts: List[int] = None,
        times: List[str] = None,
        status: str = None,
        message_data: dict = None
    ):
        """Обновление автоматизированного поста"""
        data = await Database._read_json(POSTS_FILE)
        posts = data.get("automated_posts", [])
        updated = False
        
        for post in posts:
            if post["id"] == post_id:
                if groups is not None:
                    post["groups"] = sorted(list(set(groups)))  # Убираем дубликаты и сортируем
                if accounts is not None:
                    post["accounts"] = sorted(list(set(accounts)))  # Убираем дубликаты и сортируем
                if times is not None:
                    post["times"] = sorted(list(set(times)))  # Убираем дубликаты и сортируем
                if status is not None:
                    post["status"] = status
                if message_data is not None:
                    post["message"] = message_data
                updated = True
                break
                
        if not updated:
            logging.error(f"Пост с ID {post_id} не найден при обновлении")
            return False
            
        data["automated_posts"] = posts
        await Database._write_json(POSTS_FILE, data)
        return True

    @staticmethod
    async def delete_automated_post(post_id: int):
        """Удаление автоматизированного поста"""
        data = await Database._read_json(POSTS_FILE)
        posts = data.get("automated_posts", [])
        data["automated_posts"] = [p for p in posts if p["id"] != post_id]
        await Database._write_json(POSTS_FILE, data)

    @staticmethod
    async def add_bulk_group(name: str, group_ids: List[int]) -> int:
        """Добавление новой оптомгруппы"""
        data = await Database._read_json(BULK_GROUPS_FILE)
        bulk_groups = data.get("bulk_groups", [])
        
        # Генерируем новый ID
        new_id = max([group.get("id", 0) for group in bulk_groups], default=0) + 1
        
        # Получаем полную информацию о группах
        groups_data = await Database._read_json(GROUPS_FILE)
        groups = groups_data.get("groups", [])
        selected_groups = []
        
        for group in groups:
            if group["id"] in group_ids:
                selected_groups.append({
                    "id": group["id"],
                    "group_id": group["group_id"],
                    "title": group["title"],
                    "username": group["username"],
                    "invite_link": group["invite_link"],
                    "status": group["status"]
                })
        
        bulk_group = {
            "id": new_id,
            "name": name,
            "groups": selected_groups,
            "created_at": int(time.time())
        }
        
        bulk_groups.append(bulk_group)
        data["bulk_groups"] = bulk_groups
        await Database._write_json(BULK_GROUPS_FILE, data)
        return new_id

    @staticmethod
    async def get_bulk_groups() -> List[dict]:
        """Получение всех оптомгрупп"""
        data = await Database._read_json(BULK_GROUPS_FILE)
        return data.get("bulk_groups", [])

    @staticmethod
    async def get_bulk_group_by_id(bulk_group_id: int) -> Optional[dict]:
        """Получение оптомгруппы по ID"""
        data = await Database._read_json(BULK_GROUPS_FILE)
        for bulk_group in data.get("bulk_groups", []):
            if bulk_group["id"] == bulk_group_id:
                return bulk_group
        return None

    @staticmethod
    async def update_bulk_group(bulk_group_id: int, name: str = None, group_ids: List[int] = None) -> bool:
        """Обновление оптомгруппы"""
        try:
            data = await Database._read_json(BULK_GROUPS_FILE)
            bulk_groups = data.get("bulk_groups", [])
            updated = False
            
            # Находим индекс оптомгруппы
            index = None
            for i, group in enumerate(bulk_groups):
                if group["id"] == bulk_group_id:
                    index = i
                    break
            
            if index is not None:
                # Обновляем существующую запись
                if name is not None:
                    bulk_groups[index]["name"] = name
                if group_ids is not None:
                    # Получаем полную информацию о группах
                    groups_data = await Database._read_json(GROUPS_FILE)
                    groups = groups_data.get("groups", [])
                    selected_groups = []
                    
                    for group in groups:
                        if group["id"] in group_ids:
                            selected_groups.append({
                                "id": group["id"],
                                "group_id": group["group_id"],
                                "title": group["title"],
                                "username": group["username"],
                                "invite_link": group["invite_link"],
                                "status": group["status"]
                            })
                    
                    bulk_groups[index]["groups"] = selected_groups
                updated = True
                
                # Сохраняем обновленные данные
                data["bulk_groups"] = bulk_groups
                await Database._write_json(BULK_GROUPS_FILE, data)
                return True
            
            return False
            
        except Exception as e:
            return False

    @staticmethod
    async def delete_bulk_group(bulk_group_id: int) -> bool:
        """Удаление оптомгруппы"""
        try:
            data = await Database._read_json(BULK_GROUPS_FILE)
            bulk_groups = data.get("bulk_groups", [])
            initial_length = len(bulk_groups)
            
            data["bulk_groups"] = [bg for bg in bulk_groups if bg["id"] != bulk_group_id]
            await Database._write_json(BULK_GROUPS_FILE, data)
            
            return len(data["bulk_groups"]) < initial_length
        except Exception as e:
            return False 