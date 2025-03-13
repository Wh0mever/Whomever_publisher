from telethon import TelegramClient
from telethon.errors import (
    ChatWriteForbiddenError,
    ChannelPrivateError,
    UserBannedInChannelError,
    MediaInvalidError,
    PhotoInvalidDimensionsError,
    VideoFileInvalidError,
    UserNotParticipantError
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import InputPeerChannel, InputFile, Message, PeerChannel
import asyncio
import os
from datetime import datetime
from typing import List, Dict, Any, Union, Optional
from config import DEFAULT_DELAY, MAX_RETRIES
from database.models import Database
import aiofiles
import aiohttp
from loguru import logger
from aiogram import Bot
import hashlib

class PostingManager:
    def __init__(self, client: TelegramClient, db: Database, bot: Bot):
        self.client = client
        self.db = db
        self.bot = bot
        
    async def join_group(self, group_id: str) -> bool:
        try:
            # Получаем информацию о группе из базы данных
            group_data = await self.db.get_group_by_group_id(str(group_id))
            if not group_data:
                logger.error(f"Группа с ID {group_id} не найдена в базе данных")
                return False
            
            # Форматируем ID группы
            channel_id = group_data['group_id']
            if not str(channel_id).startswith('-100'):
                channel_id = f"-100{channel_id}"
            
            # Пробуем получить username группы
            username = group_data.get('username')
            if username:
                try:
                    # Пробуем подписаться по username
                    entity = await self.client.get_entity(f"@{username}")
                    await self.client(JoinChannelRequest(entity))
                    logger.info(f"✅ Успешно подписались на группу @{username}")
                    return True
                except Exception as e:
                    logger.error(f"Не удалось подписаться по username @{username}: {str(e)}")
                    # Продолжаем, попробуем другие методы
            
            # Пробуем через invite link, если есть
            invite_link = group_data.get('invite_link')
            if invite_link:
                try:
                    # Пробуем подписаться по invite link
                    await self.client(JoinChannelRequest(invite_link))
                    logger.info(f"✅ Успешно подписались на группу по invite link")
                    return True
                except Exception as e:
                    logger.error(f"Не удалось подписаться по invite link: {str(e)}")
                    # Продолжаем, попробуем через ID
            
            # Если не удалось по username и invite link, пробуем через ID
            try:
                entity = await self.client.get_entity(PeerChannel(int(channel_id.replace('-100', ''))))
                await self.client(JoinChannelRequest(entity))
                logger.info(f"✅ Успешно подписались на группу по ID {channel_id}")
                return True
            except Exception as e:
                logger.error(f"Не удалось подписаться по ID {channel_id}: {str(e)}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при присоединении к группе {group_id}: {str(e)}")
            return False
    
    async def check_group_access(self, group_id: str) -> tuple[bool, str]:
        try:
            logger.info(f"Проверяем доступ к группе {group_id}")
            
            # Получаем информацию о группе из базы данных
            group_data = await self.db.get_group_by_group_id(str(group_id))
            if not group_data:
                logger.error(f"Группа с ID {group_id} не найдена в базе данных")
                return False, "Группа не найдена в базе данных"
            
            # Форматируем ID группы
            channel_id = group_data['group_id']
            if not str(channel_id).startswith('-100'):
                channel_id = f"-100{channel_id}"
            
            try:
                # Пробуем получить сущность по ID
                entity = await self.client.get_entity(PeerChannel(int(channel_id.replace('-100', ''))))
                logger.info(f"Успешно получили группу: {entity.title}")
            except Exception as e:
                # Если не получилось по ID, пробуем через username
                username = group_data.get('username')
                if username:
                    try:
                        entity = await self.client.get_entity(f"@{username}")
                        logger.info(f"Успешно получили группу по username: {entity.title}")
                    except Exception as e:
                        logger.error(f"Не удалось получить группу по username @{username}: {str(e)}")
                        return False, "Не удалось получить доступ к группе"
                else:
                    logger.error(f"Не удалось получить группу по ID {channel_id}: {str(e)}")
                    return False, "Не удалось получить доступ к группе"
            
            try:
                # Пробуем получить права
                permissions = await self.client.get_permissions(entity)
                
                if not permissions:
                    logger.error(f"Не удалось получить права для группы {group_id}")
                    return False, "Нет доступа к группе"
                    
                logger.info(f"Успешно получили права для группы {entity.title}")
                return True, "OK"
                
            except UserNotParticipantError:
                # Если не участник - пробуем подписаться
                logger.info(f"Аккаунт не подписан на группу {entity.title}, пробуем подписаться")
                try:
                    await self.join_group(group_id)
                    logger.info(f"Успешно подписались на группу {entity.title}")
                    
                    # Проверяем права после подписки
                    permissions = await self.client.get_permissions(entity)
                    if permissions:
                        return True, "Подписались и получили доступ"
                    else:
                        return False, "Подписались, но нет прав на отправку"
                        
                except Exception as e:
                    logger.error(f"Не удалось подписаться на группу {entity.title}: {str(e)}")
                    return False, f"Не удалось подписаться: {str(e)}"
                
            except ChatWriteForbiddenError:
                logger.error(f"Нет прав на отправку сообщений в группу {group_id}")
                return False, "Нет прав на отправку сообщений"
            except ChannelPrivateError:
                logger.warning(f"Группа {group_id} является приватной")
                return False, "Группа является приватной"
            except Exception as e:
                logger.error(f"Ошибка при проверке доступа к группе {group_id}: {str(e)}")
                return False, "Нет доступа к группе"
                
        except Exception as e:
            logger.exception(f"Критическая ошибка при проверке доступа к группе {group_id}: {str(e)}")
            return False, str(e)

    async def download_media_file(self, file_id: str, file_type: str) -> Optional[str]:
        """Скачивает медиафайл из Telegram и сохраняет его локально"""
        try:
            # Создаем директорию для временных файлов, если её нет
            os.makedirs("temp_media", exist_ok=True)
            
            # Генерируем имя файла
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = f"temp_media/{timestamp}_{file_id}.{file_type}"
            
            # Скачиваем файл
            await self.client.download_media(file_id, file_path)
            return file_path
        except Exception as e:
            logger.error(f"Ошибка при скачивании медиафайла {file_id}: {str(e)}")
            return None

    async def process_media(self, media_data: Dict[str, Any]) -> Optional[str]:
        """Обрабатывает медиафайл перед отправкой"""
        try:
            if not media_data:
                return None
                
            file_id = media_data.get('file_id')
            if not file_id:
                return None
            
            # Определяем тип файла
            file_type = "jpg"  # По умолчанию
            if 'video' in media_data:
                file_type = "mp4"
            elif 'document' in media_data:
                # Получаем расширение из оригинального имени файла
                original_name = media_data.get('file_name', '')
                file_type = original_name.split('.')[-1] if '.' in original_name else 'doc'
            
            # Скачиваем файл
            file_path = await self.download_media_file(file_id, file_type)
            if not file_path:
                return None
            
            return file_path
            
        except Exception as e:
            logger.error(f"Ошибка при обработке медиафайла: {str(e)}")
            return None
    
    async def check_account_status(self) -> tuple[bool, str]:
        """Проверяет, не заморожен ли аккаунт"""
        try:
            # Получаем телефон из сессии
            me = await self.client.get_me()
            phone = me.phone
            
            # Ищем аккаунт по номеру телефона
            data = await self.db._read_json('database/accounts.json')
            accounts = data.get('accounts', [])
            
            for account in accounts:
                if account['phone'] == f"+{phone}":
                    if account['status'] == 'frozen':
                        logger.warning(f"Аккаунт {account['phone']} заморожен")
                        return False, account['phone']
                    return True, account['phone']
                    
            logger.warning(f"Аккаунт с номером +{phone} не найден в базе")
            return True, f"+{phone}"  # Разрешаем отправку если аккаунт не найден
            
        except Exception as e:
            logger.error(f"Ошибка при проверке статуса аккаунта: {str(e)}")
            return True, "unknown"  # В случае ошибки позволяем продолжить

    async def get_media_hash(self, file_id: str) -> str:
        """Генерирует хеш для медиафайла"""
        return hashlib.md5(file_id.encode()).hexdigest()

    async def get_cached_media_path(self, file_id: str, file_type: str) -> Optional[str]:
        """Проверяет наличие кешированного медиафайла"""
        media_hash = await self.get_media_hash(file_id)
        cached_path = f"automated_media/{media_hash}.{file_type}"
        return cached_path if os.path.exists(cached_path) else None

    async def cache_media_file(self, file_id: str, file_type: str, temp_path: str) -> Optional[str]:
        """Кеширует медиафайл для повторного использования"""
        try:
            os.makedirs("automated_media", exist_ok=True)
            media_hash = await self.get_media_hash(file_id)
            cached_path = f"automated_media/{media_hash}.{file_type}"
            
            if not os.path.exists(cached_path):
                # Копируем файл в кеш
                with open(temp_path, 'rb') as src, open(cached_path, 'wb') as dst:
                    dst.write(src.read())
                logger.info(f"Медиафайл {file_id} успешно кеширован")
            
            return cached_path
        except Exception as e:
            logger.error(f"Ошибка при кешировании медиафайла {file_id}: {str(e)}")
            return None

    async def send_post(
        self,
        group_id: str,
        message_data: dict,
        retry_count: int = 0
    ) -> tuple[bool, str]:
        # Проверяем статус аккаунта перед отправкой
        can_send, phone = await self.check_account_status()
        if not can_send:
            logger.warning(f"Аккаунт {phone} заморожен, пропускаем отправку")
            return False, "ACCOUNT_FROZEN"
            
        try:
            logger.info(f"[Этап 1/5] Начинаем отправку поста через аккаунт {phone} в группу {group_id}")
            start_time = datetime.now()
            
            # Получаем информацию о группе из базы данных
            group_data = await self.db.get_group_by_group_id(str(group_id))
            if not group_data:
                logger.error(f"[Этап 1/5] ❌ Группа с ID {group_id} не найдена в базе данных")
                return False, "Группа не найдена в базе данных"
            
            # Форматируем ID группы
            channel_id = group_data['group_id']
            if not str(channel_id).startswith('-100'):
                channel_id = f"-100{channel_id}"

            # Сначала пробуем подписаться на группу
            logger.info(f"[Этап 2/5] Попытка подписаться на группу {channel_id}")
            if not await self.join_group(group_id):
                logger.warning(f"[Этап 2/5] ⚠️ Не удалось подписаться на группу {channel_id}, но продолжаем...")
            else:
                logger.info(f"[Этап 2/5] ✅ Успешно подписались на группу")
                await asyncio.sleep(2)  # Небольшая задержка после подписки
            
            try:
                # Теперь пытаемся получить сущность группы
                entity = await self.client.get_entity(PeerChannel(int(channel_id.replace('-100', ''))))
                logger.info(f"[Этап 2/5] ✅ Успешно получили группу: {entity.title}")
            except Exception as e:
                logger.error(f"[Этап 2/5] ❌ Не удалось получить группу: {str(e)}")
                return False, f"Ошибка при получении группы: {str(e)}"
            
            # Проверяем права доступа
            can_post, reason = await self.check_group_access(group_id)
            if not can_post:
                logger.error(f"[Этап 2/5] ❌ Нет доступа к группе {entity.title}: {reason}")
                return False, reason
            
            logger.info(f"[Этап 2/5] ✅ Права доступа подтверждены для {entity.title}")
            
            try:
                # Подготавливаем сообщение
                logger.info("[Этап 3/5] Подготовка сообщения к отправке")
                
                text = message_data.get('text') or message_data.get('caption') or ""
                
                # Создаем временную директорию
                os.makedirs("temp_media", exist_ok=True)
                
                # Проверяем наличие медиафайлов
                if 'photo' in message_data:
                    logger.info("[Этап 3/5] Подготовка фото")
                    try:
                        # Проверяем наличие кешированного файла
                        cached_path = await self.get_cached_media_path(message_data['photo'], 'jpg')
                        
                        if not cached_path:
                            # Если нет в кеше, скачиваем во временный файл
                            temp_path = f"temp_media/photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                            file = await self.bot.get_file(message_data['photo'])
                            await self.bot.download_file(file.file_path, temp_path)
                            
                            # Кешируем файл
                            cached_path = await self.cache_media_file(message_data['photo'], 'jpg', temp_path)
                            # Удаляем временный файл
                            os.remove(temp_path)
                        
                        # Отправляем сообщение с фото
                        result = await self.client.send_file(
                            entity,
                            cached_path,
                            caption=text
                        )
                        
                    except Exception as e:
                        logger.error(f"[Этап 4/5] ❌ Ошибка при отправке фото: {str(e)}")
                        raise
                        
                elif 'video' in message_data:
                    logger.info("[Этап 3/5] Подготовка видео")
                    try:
                        # Проверяем наличие кешированного файла
                        cached_path = await self.get_cached_media_path(message_data['video'], 'mp4')
                        
                        if not cached_path:
                            # Если нет в кеше, скачиваем во временный файл
                            temp_path = f"temp_media/video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                            file = await self.bot.get_file(message_data['video'])
                            await self.bot.download_file(file.file_path, temp_path)
                            
                            # Кешируем файл
                            cached_path = await self.cache_media_file(message_data['video'], 'mp4', temp_path)
                            # Удаляем временный файл
                            os.remove(temp_path)
                        
                        # Отправляем сообщение с видео
                        result = await self.client.send_file(
                            entity,
                            cached_path,
                            caption=text
                        )
                        
                    except Exception as e:
                        logger.error(f"[Этап 4/5] ❌ Ошибка при отправке видео: {str(e)}")
                        raise
                        
                elif 'document' in message_data:
                    logger.info("[Этап 3/5] Подготовка документа")
                    try:
                        # Получаем расширение из оригинального имени файла
                        file_ext = message_data['document'].get('file_name', '').split('.')[-1] if '.' in message_data['document'].get('file_name', '') else 'doc'
                        
                        # Проверяем наличие кешированного файла
                        cached_path = await self.get_cached_media_path(message_data['document']['file_id'], file_ext)
                        
                        if not cached_path:
                            # Если нет в кеше, скачиваем во временный файл
                            temp_path = f"temp_media/doc_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{file_ext}"
                            file = await self.bot.get_file(message_data['document']['file_id'])
                            await self.bot.download_file(file.file_path, temp_path)
                            
                            # Кешируем файл
                            cached_path = await self.cache_media_file(message_data['document']['file_id'], file_ext, temp_path)
                            # Удаляем временный файл
                            os.remove(temp_path)
                        
                        # Отправляем сообщение с документом
                        result = await self.client.send_file(
                            entity,
                            cached_path,
                            caption=text
                        )
                        
                    except Exception as e:
                        logger.error(f"[Этап 4/5] ❌ Ошибка при отправке документа: {str(e)}")
                        raise
                        
                else:
                    # Отправляем только текст
                    result = await self.client.send_message(
                        entity,
                        text
                    )
                
                if result:
                    end_time = datetime.now()
                    duration = (end_time - start_time).total_seconds()
                    logger.info(f"[Этап 5/5] ✅ Сообщение успешно отправлено в группу {entity.title}")
                    logger.info(f"[Статистика] Время выполнения: {duration:.2f} секунд")
                    return True, "OK"
                else:
                    logger.error("[Этап 4/5] ❌ Сообщение не было отправлено (пустой результат)")
                    return False, "Сообщение не было отправлено"
                    
            except Exception as e:
                logger.error(f"[Этап 4/5] ❌ Ошибка при отправке сообщения: {str(e)}")
                if retry_count < MAX_RETRIES:
                    retry_delay = DEFAULT_DELAY * (retry_count + 1)
                    logger.info(f"[Повтор] Пробуем отправить снова через {retry_delay} сек (попытка {retry_count + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(retry_delay)
                    return await self.send_post(group_id, message_data, retry_count + 1)
                return False, str(e)
                
        except Exception as e:
            logger.error(f"[Критическая ошибка] ❌ Ошибка при отправке поста: {str(e)}")
            if retry_count < MAX_RETRIES:
                retry_delay = DEFAULT_DELAY * (retry_count + 1)
                logger.info(f"[Повтор] Пробуем отправить снова через {retry_delay} сек (попытка {retry_count + 1}/{MAX_RETRIES})")
                await asyncio.sleep(retry_delay)
                return await self.send_post(group_id, message_data, retry_count + 1)
            return False, str(e)

class PostingPool:
    def __init__(self, max_threads: int = 5):
        self.max_threads = max_threads
        self.active_tasks: List[asyncio.Task] = []
    
    async def add_posting_task(
        self,
        posting_manager: PostingManager,
        group_id: str,
        message_data: dict
    ):
        # Очищаем завершенные задачи
        self.active_tasks = [task for task in self.active_tasks if not task.done()]
        
        # Проверяем статус аккаунта
        can_send, phone = await posting_manager.check_account_status()
        if not can_send:
            logger.warning(f"Аккаунт {phone} заморожен, пропускаем отправку")
            return None
            
        # Если достигнут лимит потоков, ждем освобождения
        while len(self.active_tasks) >= self.max_threads:
            await asyncio.sleep(1)
            self.active_tasks = [task for task in self.active_tasks if not task.done()]
        
        # Создаем новую задачу
        task = asyncio.create_task(
            posting_manager.send_post(group_id, message_data)
        )
        self.active_tasks.append(task)
        
        return task
    
    async def wait_all(self):
        """Ожидание завершения всех активных задач"""
        if self.active_tasks:
            await asyncio.gather(*self.active_tasks)
            self.active_tasks.clear() 