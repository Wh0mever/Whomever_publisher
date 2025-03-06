from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    PhoneNumberInvalidError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
    FloodWaitError,
    ApiIdInvalidError,
    PhoneCodeExpiredError
)
from cryptography.fernet import Fernet
import json
import os
from pathlib import Path
from loguru import logger
from config import SESSIONS_DIR, API_ID, API_HASH

class SessionManager:
    def __init__(self):
        logger.info("Инициализация SessionManager")
        self.key = self._get_or_create_key()
        self.fernet = Fernet(self.key)
        self.temp_clients = {}  # Временное хранилище клиентов
        self.session_counter = self._get_last_session_number()
    
    def _get_or_create_key(self):
        key_file = SESSIONS_DIR / "key.key"
        if key_file.exists():
            logger.debug("Загружен существующий ключ шифрования")
            return key_file.read_bytes()
        else:
            logger.info("Создан новый ключ шифрования")
            key = Fernet.generate_key()
            key_file.write_bytes(key)
            return key
    
    def _get_last_session_number(self):
        """Находит последний номер сессии"""
        try:
            sessions = list(SESSIONS_DIR.glob("user.session*"))
            if not sessions:
                return 0
            numbers = [int(s.name.replace("user.session", "") or 1) for s in sessions]
            return max(numbers)
        except Exception:
            return 0
    
    def _get_next_session_file(self) -> str:
        """Генерирует имя следующего файла сессии"""
        self.session_counter += 1
        return f"user.session{self.session_counter if self.session_counter > 1 else ''}"
    
    async def create_session(self, phone: str) -> tuple[bool, str]:
        logger.info(f"Создание новой сессии для номера {phone}")
        try:
            # Создаем нового клиента и сохраняем его
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            self.temp_clients[phone] = client
            
            logger.debug(f"Подключение к Telegram установлено для {phone}")
            
            if not await client.is_user_authorized():
                logger.info(f"Отправка запроса кода для {phone}")
                try:
                    send_code_result = await client.send_code_request(phone)
                    logger.info(f"Код успешно отправлен для {phone}")
                    return False, f"CODE_REQUIRED:{send_code_result.phone_code_hash}"
                except FloodWaitError as e:
                    logger.warning(f"Флуд-ожидание для {phone}: {e.seconds} секунд")
                    await self._cleanup_client(phone)
                    return False, f"Подождите {e.seconds} секунд перед повторной попыткой"
                except PhoneNumberInvalidError:
                    logger.error(f"Неверный формат номера: {phone}")
                    await self._cleanup_client(phone)
                    return False, "Неверный формат номера телефона"
                except ApiIdInvalidError:
                    logger.error("Неверные API_ID или API_HASH")
                    await self._cleanup_client(phone)
                    return False, "Ошибка авторизации приложения"
            
            logger.info(f"Аккаунт {phone} уже авторизован")
            session_str = client.session.save()
            encrypted_session = self.fernet.encrypt(session_str.encode())
            
            session_file = SESSIONS_DIR / f"{phone}.session"
            session_data = {
                "phone": phone,
                "session": encrypted_session.decode()
            }
            
            with open(session_file, 'w') as f:
                json.dump(session_data, f)
            
            logger.info(f"Сессия сохранена для {phone}")
            await self._cleanup_client(phone)
            return True, session_file.name
            
        except Exception as e:
            logger.exception(f"Ошибка при создании сессии для {phone}: {str(e)}")
            await self._cleanup_client(phone)
            return False, str(e)
    
    async def auth_code(self, phone: str, code: str, password: str = None, phone_code_hash: str = None) -> tuple[bool, str]:
        logger.info(f"Попытка авторизации по коду для {phone}")
        try:
            # Используем существующего клиента или создаем нового
            client = self.temp_clients.get(phone)
            if not client or not client.is_connected():
                client = TelegramClient(StringSession(), API_ID, API_HASH)
                await client.connect()
                self.temp_clients[phone] = client
            
            try:
                if password is not None:
                    # Если передан пароль 2FA, используем его для входа
                    logger.debug(f"Попытка входа с 2FA для {phone}")
                    await client.sign_in(password=password)
                    logger.info(f"2FA пароль подтверждён для {phone}")
                else:
                    # Иначе пробуем войти с кодом
                    logger.debug(f"Проверка кода для {phone}")
                    await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
                    logger.info(f"Код подтверждён для {phone}")
                
                # Если дошли до этой точки, значит авторизация успешна
                session_str = client.session.save()
                encrypted_session = self.fernet.encrypt(session_str.encode())
                
                session_file = SESSIONS_DIR / f"{phone}.session"
                session_data = {
                    "phone": phone,
                    "session": encrypted_session.decode()
                }
                
                with open(session_file, 'w') as f:
                    json.dump(session_data, f)
                
                logger.info(f"Сессия успешно сохранена в {session_file}")
                await self._cleanup_client(phone)
                return True, session_file.name
                
            except SessionPasswordNeededError:
                # Если требуется 2FA
                logger.info(f"Требуется 2FA для {phone}")
                if password:
                    logger.error(f"Неверный пароль 2FA для {phone}")
                    await self._cleanup_client(phone)
                    return False, "Неверный пароль 2FA"
                else:
                    # Не закрываем клиента, так как он понадобится для 2FA
                    return False, "2FA_REQUIRED"
                    
            except PhoneCodeExpiredError:
                # Только здесь запрашиваем новый код
                logger.warning(f"Код подтверждения действительно истек для {phone}")
                try:
                    send_code_result = await client.send_code_request(phone)
                    logger.info(f"Отправлен новый код для {phone}")
                    return False, f"CODE_EXPIRED:{send_code_result.phone_code_hash}"
                except Exception as e:
                    logger.error(f"Ошибка при повторном запросе кода для {phone}: {str(e)}")
                    await self._cleanup_client(phone)
                    return False, "Код истек. Начните регистрацию заново"
                    
            except PhoneCodeInvalidError:
                logger.error(f"Неверный код для {phone}")
                return False, "INVALID_CODE"
            
        except Exception as e:
            logger.exception(f"Критическая ошибка при авторизации {phone}: {str(e)}")
            await self._cleanup_client(phone)
            return False, str(e)
    
    async def _cleanup_client(self, phone: str):
        """Очищает и отключает клиента"""
        if phone in self.temp_clients:
            client = self.temp_clients[phone]
            try:
                await client.disconnect()
            except:
                pass
            del self.temp_clients[phone]
    
    async def get_client(self, session_file: str) -> TelegramClient:
        logger.info(f"Получение клиента для сессии {session_file}")
        try:
            with open(SESSIONS_DIR / session_file, 'r') as f:
                session_data = json.load(f)
            
            encrypted_session = session_data['session'].encode()
            session_str = self.fernet.decrypt(encrypted_session).decode()
            
            client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
            await client.connect()
            
            if not await client.is_user_authorized():
                logger.error(f"Сессия {session_file} истекла")
                raise Exception("Session expired")
            
            logger.info(f"Клиент успешно создан для {session_file}")
            return client
        except Exception as e:
            logger.exception(f"Ошибка при создании клиента для {session_file}: {str(e)}")
            raise Exception(f"Failed to create client: {str(e)}")
    
    def delete_session(self, session_file: str) -> bool:
        logger.info(f"Удаление сессии {session_file}")
        try:
            session_path = SESSIONS_DIR / session_file
            if session_path.exists():
                session_path.unlink()
                logger.info(f"Сессия {session_file} успешно удалена")
            return True
        except Exception as e:
            logger.exception(f"Ошибка при удалении сессии {session_file}: {str(e)}")
            return False 