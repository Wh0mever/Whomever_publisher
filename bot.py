import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from database.models import Database, init_db, ACCOUNTS_FILE, GROUPS_FILE, POSTS_FILE, SETTINGS_FILE
from utils.session_manager import SessionManager
from utils.posting_manager import PostingManager, PostingPool
from config import BOT_TOKEN, MAX_THREADS, DEFAULT_DELAY, MAX_RETRIES, SESSIONS_DIR
import logging
from loguru import logger
import sys
from datetime import datetime, timedelta
from telethon.tl.functions.channels import GetFullChannelRequest, JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import UserNotParticipantError, InviteHashInvalidError, InviteHashExpiredError, ChannelPrivateError, UserAlreadyParticipantError
from telethon.tl.types import PeerChannel
import time
from typing import Optional
import os
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import re

# Настраиваем логирование
logger.remove()  # Удаляем стандартный обработчик
logger.add(sys.stderr, format="{time} | {level} | {message}")
logger.add(
    "logs/bot_{time}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    rotation="1 MB",
    compression="zip",
    backtrace=True,
    diagnose=True
)
logger.add(
    "logs/errors_{time}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    level="ERROR",
    rotation="1 MB",
    compression="zip",
    backtrace=True,
    diagnose=True
)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния FSM
class AccountStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()

class PostStates(StatesGroup):
    waiting_for_content = State()
    waiting_for_media = State()
    waiting_for_schedule = State()
    waiting_for_groups = State()
    waiting_for_accounts = State()
    waiting_for_delay = State()
    # Новые состояния для автоматизации
    waiting_for_auto_groups = State()
    waiting_for_auto_accounts = State()
    waiting_for_auto_content = State()
    waiting_for_auto_times_count = State()
    waiting_for_auto_time = State()

class SettingsStates(StatesGroup):
    waiting_for_delay = State()
    waiting_for_threads = State()
    waiting_for_retries = State()

class GroupStates(StatesGroup):
    waiting_for_group = State()
    waiting_for_bulk_group_name = State()
    waiting_for_bulk_group_selection = State()

# Инициализация менеджеров
session_manager = SessionManager()
posting_pool = PostingPool(max_threads=MAX_THREADS)

def get_main_keyboard() -> types.ReplyKeyboardMarkup:
    """Создание основной клавиатуры"""
    keyboard = [
        [
            types.KeyboardButton(text="👤 Управление аккаунтами"),
            types.KeyboardButton(text="👥 Управление группами")
        ],
        [
            types.KeyboardButton(text="✍️ Новый пост"),
            types.KeyboardButton(text="⏰ Отложенный пост")
        ],
        [
            types.KeyboardButton(text="🤖 Автоматизация постов"),
            types.KeyboardButton(text="📋 Список постов")
        ],
        [
            types.KeyboardButton(text="⚙️ Настройка автопостов"),
            types.KeyboardButton(text="⚙️ Настройки")
        ]
    ]
    return types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# Обработчики команд
@dp.message(Command("start"))
async def start_command(message: types.Message):
    await message.answer(
        "👋 Добро пожаловать в бот для управления постингом!\n\n"
        "🔹 Создавайте и отправляйте посты\n"
        "🔹 Планируйте отложенные публикации\n"
        "🔹 Управляйте группами и аккаунтами\n"
        "🔹 Проверяйте доступ к группам\n\n"
        "Выберите действие в меню:",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("cancel"))
async def cancel_command(message: types.Message, state: FSMContext):
    """Отмена текущего действия"""
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
        await message.answer(
            "❌ Действие отменено. Вернулись в главное меню",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            "🤔 Нечего отменять. Вы в главном меню",
            reply_markup=get_main_keyboard()
        )

# Обработчик кнопки добавления аккаунта
@dp.message(lambda m: m.text == "👤 Добавить аккаунт")
async def start_add_account(message: types.Message, state: FSMContext):
    await state.set_state(AccountStates.waiting_for_phone)
    await message.answer(
        "📱 Отправьте номер телефона аккаунта в формате: +998901234567\n\n"
        "Для отмены используйте команду /cancel"
    )

# Обработчик ввода номера телефона
@dp.message(AccountStates.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    logger.info(f"Попытка добавления аккаунта с номером: {phone}")
    
    if not phone.startswith('+') or not phone[1:].isdigit():
        logger.warning(f"Неверный формат номера: {phone}")
        await message.answer(
            "❌ Неверный формат номера!\n"
            "Отправьте номер в формате: +79001234567"
        )
        return
    
    await state.update_data(phone=phone)
    
    try:
        logger.info(f"Отправка запроса кода для номера {phone}")
        success, result = await session_manager.create_session(phone)
        
        if result.startswith("CODE_REQUIRED:"):
            phone_code_hash = result.split(":")[1]
            await state.update_data(phone_code_hash=phone_code_hash)
            await state.set_state(AccountStates.waiting_for_code)
            logger.info(f"Код подтверждения запрошен для номера {phone}")
            await message.answer(
                "✅ Код подтверждения отправлен!\n"
                "Введите код, который пришел в Telegram на указанный аккаунт:"
            )
        else:
            logger.error(f"Ошибка при создании сессии для {phone}: {result}")
            await state.clear()
            await message.answer(f"❌ Ошибка: {result}")
    except Exception as e:
        logger.exception(f"Критическая ошибка при обработке номера {phone}: {str(e)}")
        await state.clear()
        await message.answer(f"❌ Произошла ошибка: {str(e)}")

# Обработчик ввода кода подтверждения
@dp.message(AccountStates.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    data = await state.get_data()
    phone = data.get("phone")
    
    logger.info(f"Получен код подтверждения для номера {phone}")
    
    if not code.isdigit():
        logger.warning(f"Неверный формат кода для номера {phone}: {code}")
        await message.answer("❌ Код должен состоять только из цифр!")
        return
    
    phone_code_hash = data.get("phone_code_hash")
    logger.debug(f"phone_code_hash для {phone}: {phone_code_hash}")
    
    try:
        logger.info(f"Попытка авторизации с кодом для номера {phone}")
        success, result = await session_manager.auth_code(phone, code, phone_code_hash=phone_code_hash)
        
        if success:
            logger.info(f"Успешная авторизация аккаунта {phone}")
            await Database.add_account(phone, result)
            await state.clear()
            await message.answer(
                "✅ Аккаунт успешно добавлен!\n"
                "Теперь вы можете использовать его для постинга."
            )
        else:
            if result == "2FA_REQUIRED":
                logger.info(f"Требуется 2FA для аккаунта {phone}")
                await state.set_state(AccountStates.waiting_for_2fa)
                await message.answer(
                    "🔐 Требуется двухфакторная аутентификация!\n"
                    "Введите пароль 2FA:"
                )
            elif result.startswith("CODE_EXPIRED:"):
                # Получаем новый phone_code_hash
                new_phone_code_hash = result.split(":")[1]
                await state.update_data(phone_code_hash=new_phone_code_hash)
                logger.info(f"Код истек для {phone}, отправлен новый")
                await message.answer(
                    "⚠️ Код подтверждения истек!\n"
                    "Мы отправили новый код.\n"
                    "Пожалуйста, введите код, который только что пришел:"
                )
            else:
                logger.error(f"Ошибка при проверке кода для {phone}: {result}")
                await message.answer(f"❌ Ошибка: {result}\nПопробуйте ввести код ещё раз.")
    except Exception as e:
        logger.exception(f"Критическая ошибка при проверке кода для {phone}: {str(e)}")
        await message.answer(f"❌ Ошибка при проверке кода: {str(e)}")

# Обработчик ввода пароля 2FA
@dp.message(AccountStates.waiting_for_2fa)
async def process_2fa(message: types.Message, state: FSMContext):
    password = message.text.strip()
    data = await state.get_data()
    phone = data.get("phone")
    phone_code_hash = data.get("phone_code_hash")
    
    try:
        success, result = await session_manager.auth_code(phone, None, password=password, phone_code_hash=phone_code_hash)
        
        if success:
            await Database.add_account(phone, result)
            await state.clear()
            await message.answer(
                "✅ Аккаунт успешно добавлен!\n"
                "Теперь вы можете использовать его для постинга."
            )
        else:
            await state.clear()
            await message.answer(f"❌ Ошибка: {result}")
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ Ошибка при проверке пароля 2FA: {str(e)}")

# Обработчик просмотра статуса аккаунтов
@dp.message(lambda m: m.text == "📊 Статус аккаунтов")
async def show_accounts_status(message: types.Message):
    try:
        data = await Database._read_json(ACCOUNTS_FILE)
        accounts = data.get("accounts", [])
        
        if not accounts:
            await message.answer(
                "❌ У вас пока нет добавленных аккаунтов.\n"
                "Нажмите '👤 Добавить аккаунт' чтобы добавить новый."
            )
            return
        
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=f"{'🟢' if acc['status'] == 'active' else '🔴' if acc['status'] == 'frozen' else '⛔'} {acc['phone']}", 
                        callback_data=f"account_menu_{acc['id']}"
                    )
                ] for acc in accounts
            ]
        )
        
        status_text = "📱 Управление аккаунтами:\n\n"
        status_text += "🟢 - Активен\n"
        status_text += "🔴 - Заморожен\n"
        status_text += "⛔ - Заблокирован\n\n"
        status_text += "Нажмите на аккаунт для управления"
        
        await message.answer(status_text, reply_markup=keyboard)
    except Exception as e:
        logger.exception(f"Ошибка при получении списка аккаунтов: {str(e)}")
        await message.answer(f"❌ Ошибка при получении списка аккаунтов: {str(e)}")

@dp.callback_query(lambda c: c.data.startswith('account_menu_'))
async def account_menu(callback: types.CallbackQuery):
    try:
        account_id = int(callback.data.split('_')[2])
        account = await Database.get_account_by_id(account_id)
        
        if not account:
            await callback.message.edit_text("❌ Аккаунт не найден")
            return
            
        status_emoji = {
            'active': '🟢',
            'frozen': '🔴',
            'banned': '⛔'
        }
        
        status_text = (
            f"📱 Аккаунт: {account['phone']}\n"
            f"Статус: {status_emoji.get(account['status'], '❓')} {account['status']}\n"
            f"Добавлен: {datetime.fromtimestamp(account['created_at']).strftime('%d.%m.%Y %H:%M')}\n"
        )
        
        if account['last_used']:
            status_text += f"Последнее использование: {datetime.fromtimestamp(account['last_used']).strftime('%d.%m.%Y %H:%M')}\n"
        
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
        
        # Кнопки управления в зависимости от текущего статуса
        if account['status'] == 'active':
            keyboard.inline_keyboard.append([
                types.InlineKeyboardButton(
                    text="🔴 Заморозить",
                    callback_data=f"account_freeze_{account['phone']}"
                )
            ])
        elif account['status'] == 'frozen':
            keyboard.inline_keyboard.append([
                types.InlineKeyboardButton(
                    text="🟢 Разморозить",
                    callback_data=f"account_unfreeze_{account['phone']}"
                )
            ])
        
        # Кнопка удаления доступна всегда
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="❌ Удалить аккаунт",
                callback_data=f"account_delete_{account['id']}"
            )
        ])
        
        # Кнопка возврата к списку
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="◀️ Назад к списку",
                callback_data="accounts_list"
            )
        ])
        
        await callback.message.edit_text(status_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.exception(f"Ошибка при открытии меню аккаунта: {str(e)}")
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")

@dp.callback_query(lambda c: c.data.startswith('account_freeze_'))
async def freeze_account(callback: types.CallbackQuery):
    try:
        phone = callback.data.replace('account_freeze_', '')
        
        # Получаем данные аккаунта
        data = await Database._read_json(ACCOUNTS_FILE)
        accounts = data.get("accounts", [])
        account = None
        
        # Ищем аккаунт
        for acc in accounts:
            if acc["phone"] == phone:
                account = acc
                break
        
        if not account:
            await callback.message.edit_text("❌ Аккаунт не найден")
            return
            
        # Обновляем статус
        await Database.update_account_status(account["id"], "frozen")
        
        # Возвращаемся в меню аккаунта
        await account_menu(callback)
        
    except Exception as e:
        logger.error(f"Ошибка при заморозке аккаунта: {str(e)}")
        await callback.message.edit_text(f"❌ Ошибка при заморозке аккаунта: {str(e)}")

@dp.callback_query(lambda c: c.data.startswith('account_unfreeze_'))
async def unfreeze_account(callback: types.CallbackQuery):
    try:
        phone = callback.data.replace('account_unfreeze_', '')
        
        # Получаем данные аккаунта
        data = await Database._read_json(ACCOUNTS_FILE)
        accounts = data.get("accounts", [])
        account = None
        
        # Ищем аккаунт
        for acc in accounts:
            if acc["phone"] == phone:
                account = acc
                break
        
        if not account:
            await callback.message.edit_text("❌ Аккаунт не найден")
            return
            
        # Обновляем статус
        await Database.update_account_status(account["id"], "active")
        
        # Возвращаемся в меню аккаунта
        await account_menu(callback)
        
    except Exception as e:
        logger.error(f"Ошибка при разморозке аккаунта: {str(e)}")
        await callback.message.edit_text(f"❌ Ошибка при разморозке аккаунта: {str(e)}")

@dp.callback_query(lambda c: c.data.startswith('account_delete_'))
async def delete_account(callback: types.CallbackQuery):
    try:
        # Получаем ID аккаунта из callback_data
        parts = callback.data.split('_')
        if len(parts) < 3:
            await callback.answer("❌ Некорректный формат данных", show_alert=True)
            return
            
        # Проверяем, не является ли это подтверждением
        if 'confirm' in callback.data:
            # Получаем ID аккаунта
            account_id = int(parts[-1])
            account = await Database.get_account_by_id(account_id)
            
            if not account:
                await callback.answer("❌ Аккаунт не найден", show_alert=True)
                return
                
            # Удаляем файл сессии
            session_file = os.path.join(SESSIONS_DIR, f"{account['phone']}.session")
            if os.path.exists(session_file):
                os.remove(session_file)
                logger.info(f"Удален файл сессии: {session_file}")
                
            # Удаляем аккаунт из базы
            await Database.delete_account(account_id)
            logger.info(f"Удален аккаунт {account['phone']} из базы данных")
            
            # Отвечаем на callback и удаляем сообщение с подтверждением
            await callback.answer("✅ Аккаунт успешно удален", show_alert=True)
            await callback.message.delete()
            
            # Показываем обновленный список аккаунтов
            accounts = await Database.get_accounts()
            if not accounts:
                await callback.message.answer("❌ Нет добавленных аккаунтов")
                return
                
            keyboard = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(
                            text=f"{'🟢' if acc['status'] == 'active' else '🔴' if acc['status'] == 'frozen' else '⛔'} {acc['phone']}", 
                            callback_data=f"account_menu_{acc['id']}"
                        )
                    ] for acc in accounts
                ]
            )
            
            await callback.message.answer(
                "📱 Управление аккаунтами:\n\n"
                "🟢 - Активен\n"
                "🔴 - Заморожен\n"
                "⛔ - Заблокирован\n\n"
                "Нажмите на аккаунт для управления",
                reply_markup=keyboard
            )
            return
            
        # Если это не подтверждение, показываем сообщение с подтверждением
        account_id = int(parts[-1])
        account = await Database.get_account_by_id(account_id)
        
        if not account:
            await callback.answer("❌ Аккаунт не найден", show_alert=True)
            return
            
        # Создаем клавиатуру для подтверждения
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="❌ Удалить",
                        callback_data=f"account_delete_confirm_{account_id}"
                    ),
                    types.InlineKeyboardButton(
                        text="◀️ Отмена",
                        callback_data=f"account_menu_{account_id}"
                    )
                ]
            ]
        )
        
        # Отвечаем на callback и отправляем новое сообщение
        await callback.answer()
        await callback.message.delete()
        await callback.message.answer(
            f"⚠️ Вы действительно хотите удалить аккаунт {account['phone']}?",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Ошибка при удалении аккаунта: {str(e)}")
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)

@dp.callback_query(lambda c: c.data == "accounts_list")
async def show_accounts_list(callback: types.CallbackQuery):
    try:
        accounts = await Database.get_accounts()
        
        if not accounts:
            await callback.message.edit_text("❌ Нет добавленных аккаунтов")
            return
            
        keyboard = []
        for account in accounts:
            status = "🟢" if account["status"] == "active" else "🔴" if account["status"] == "frozen" else "⛔"
            keyboard.append([
                types.InlineKeyboardButton(
                    text=f"{status} {account['phone']}",
                    callback_data=f"account_menu_{account['id']}"
                )
            ])
            
        markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        await callback.message.edit_text(
            "📱 Управление аккаунтами:\n\n"
            "🟢 - Активен\n"
            "🔴 - Заморожен\n"
            "⛔ - Заблокирован\n\n"
            "Нажмите на аккаунт для управления",
            reply_markup=markup
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отображении списка аккаунтов: {str(e)}")
        await callback.message.edit_text(f"❌ Ошибка при отображении списка аккаунтов: {str(e)}")

# Управление постингом
@dp.message(lambda m: m.text == "📢 Управление постингом")
async def posting_menu(message: types.Message):
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [
                types.KeyboardButton(text="✍️ Новый пост"),
                types.KeyboardButton(text="⏰ Отложенный пост")
            ],
            [
                types.KeyboardButton(text="📋 Список постов"),
                types.KeyboardButton(text="◀️ Назад")
            ]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        "📢 Управление постингом\n"
        "Выберите действие:",
        reply_markup=keyboard
    )

@dp.message(lambda m: m.text in ["✍️ Новый пост", "📝 Создать пост"])
async def new_post(message: types.Message, state: FSMContext):
    await state.set_state(PostStates.waiting_for_content)
    await state.update_data(is_scheduled=False)
    await message.answer(
        "📝 Отправьте текст поста.\n"
        "Можно добавить фото, видео или документ.\n"
        "Для отмены нажмите /cancel"
    )

@dp.message(PostStates.waiting_for_content)
async def process_post_content(message: types.Message, state: FSMContext):
    try:
        # Сохраняем только нужные данные сообщения
        message_data = {
            'text': message.text,
            'caption': message.caption,
            'message_id': message.message_id,
            'user_id': message.from_user.id
        }
        
        # Если есть фото
        if message.photo:
            message_data['photo'] = message.photo[-1].file_id
            
        # Если есть видео
        if message.video:
            message_data['video'] = message.video.file_id
            
        # Если есть документ
        if message.document:
            message_data['document'] = {
                'file_id': message.document.file_id,
                'file_name': message.document.file_name
            }
        
        # Сохраняем данные в состояние
        await state.update_data(message_data=message_data)
        
        # Получаем список групп и оптомгрупп
        groups = await Database.get_active_groups()
        bulk_groups = await Database.get_bulk_groups()
        
        if not groups:
            await message.answer("❌ Нет доступных групп для отправки")
            await state.clear()
            return
            
        # Создаем клавиатуру с группами и оптомгруппами
        keyboard = []
        
        # Добавляем оптомгруппы, если они есть
        if bulk_groups:
            keyboard.extend([
                [
                    types.InlineKeyboardButton(
                        text=f"📦 {bg['name']} ({len(bg['groups'])} групп)",
                        callback_data=f"select_bulk_group_post_{bg['id']}"
                    )
                ] for bg in bulk_groups
            ])
            # Добавляем разделитель
            keyboard.append([
                types.InlineKeyboardButton(
                    text="➖ или выберите отдельные группы ➖",
                    callback_data="separator"
                )
            ])
        
        # Добавляем отдельные группы
        keyboard.extend([
            [
                types.InlineKeyboardButton(
                    text=group['title'],
                    callback_data=f"select_group_{group['id']}"
                )
            ] for group in groups
        ])
        
        # Добавляем кнопку подтверждения
        keyboard.append([
            types.InlineKeyboardButton(
                text="✅ Подтвердить выбор",
                callback_data="confirm_groups"
            )
        ])
        
        markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        await state.update_data(selected_groups=[])
        await state.set_state(PostStates.waiting_for_groups)
        await message.answer(
            "📢 Выберите группы для отправки поста\n"
            "Можно выбрать отдельные группы или оптомгруппу",
            reply_markup=markup
        )
        
    except Exception as e:
        logger.exception(f"Ошибка при обработке контента поста: {str(e)}")
        await message.answer("❌ Произошла ошибка при обработке поста")
        await state.clear()

@dp.callback_query(lambda c: c.data.startswith('select_bulk_group_post_'))
async def select_bulk_group_for_post(callback: types.CallbackQuery, state: FSMContext):
    try:
        bulk_group_id = int(callback.data.split('_')[4])
        bulk_group = await Database.get_bulk_group_by_id(bulk_group_id)
        
        if not bulk_group:
            await callback.answer("❌ Оптомгруппа не найдена", show_alert=True)
            return
            
        # Получаем текущие выбранные группы
        data = await state.get_data()
        selected_groups = data.get('selected_groups', [])
        
        # Получаем ID групп из оптомгруппы
        bulk_group_ids = [g['id'] for g in bulk_group['groups']]
        
        # Проверяем, выбрана ли эта оптомгруппа
        is_selected = all(g_id in selected_groups for g_id in bulk_group_ids)
        
        # Удаляем все группы из других оптомгрупп
        bulk_groups = await Database.get_bulk_groups()
        other_bulk_group_ids = []
        for bg in bulk_groups:
            if bg['id'] != bulk_group_id:
                other_bulk_group_ids.extend(g['id'] for g in bg['groups'])
                
        # Очищаем выбранные группы от групп из других оптомгрупп
        selected_groups = [g for g in selected_groups if g not in other_bulk_group_ids]
        
        if is_selected:
            # Если оптомгруппа уже выбрана - удаляем её группы
            selected_groups = [g for g in selected_groups if g not in bulk_group_ids]
        else:
            # Если не выбрана - добавляем её группы
            for g_id in bulk_group_ids:
                if g_id not in selected_groups:
                    selected_groups.append(g_id)
            
        await state.update_data(selected_groups=selected_groups)
        
        # Обновляем клавиатуру
        groups = await Database.get_active_groups()
        
        keyboard = []
        
        # Добавляем оптомгруппы
        if bulk_groups:
            keyboard.extend([
                [
                    types.InlineKeyboardButton(
                        text=f"{'✅' if all(g['id'] in selected_groups for g in bg['groups']) else '📦'} "
                             f"{bg['name']} ({len(bg['groups'])} групп)",
                        callback_data=f"select_bulk_group_post_{bg['id']}"
                    )
                ] for bg in bulk_groups
            ])
            keyboard.append([
                types.InlineKeyboardButton(
                    text="➖ или выберите отдельные группы ➖",
                    callback_data="separator"
                )
            ])
        
        # Добавляем отдельные группы
        keyboard.extend([
            [
                types.InlineKeyboardButton(
                    text=f"{'✅' if group['id'] in selected_groups else '⭕️'} {group['title']}",
                    callback_data=f"select_group_{group['id']}"
                )
            ] for group in groups
        ])
        
        # Добавляем кнопку подтверждения
        keyboard.append([
            types.InlineKeyboardButton(
                text="✅ Подтвердить выбор",
                callback_data="confirm_auto_groups"
            )
        ])
        
        markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        await callback.message.edit_text(
            f"📢 Выберите группы для отправки поста\n"
            f"Выбрано: {len(selected_groups)} групп",
            reply_markup=markup
        )
        
    except Exception as e:
        logger.error(f"Ошибка при выборе оптомгруппы: {str(e)}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data == "separator")
async def separator_callback(callback: types.CallbackQuery):
    # Игнорируем нажатие на разделитель
    await callback.answer()

@dp.callback_query(PostStates.waiting_for_groups, lambda c: c.data.startswith('select_group_'))
async def select_group(callback: types.CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split('_')[2])
        data = await state.get_data()
        selected_groups = data.get('selected_groups', [])
        
        if group_id in selected_groups:
            selected_groups.remove(group_id)
        else:
            selected_groups.append(group_id)
            
        await state.update_data(selected_groups=selected_groups)
        
        # Обновляем клавиатуру
        groups = await Database.get_active_groups()
        bulk_groups = await Database.get_bulk_groups()
        
        keyboard = []
        
        # Добавляем оптомгруппы
        if bulk_groups:
            keyboard.extend([
                [
                    types.InlineKeyboardButton(
                        text=f"{'✅' if set([g['id'] for g in bg['groups']]).issubset(set(selected_groups)) else '📦'} "
                             f"{bg['name']} ({len(bg['groups'])} групп)",
                        callback_data=f"select_bulk_group_post_{bg['id']}"
                    )
                ] for bg in bulk_groups
            ])
            keyboard.append([
                types.InlineKeyboardButton(
                    text="➖ или выберите отдельные группы ➖",
                    callback_data="separator"
                )
            ])
        
        # Добавляем отдельные группы
        keyboard.extend([
            [
                types.InlineKeyboardButton(
                    text=f"{'✅' if group['id'] in selected_groups else ''}{group['title']}",
                    callback_data=f"select_group_{group['id']}"
                )
            ] for group in groups
        ])
        
        # Добавляем кнопку подтверждения
        keyboard.append([
            types.InlineKeyboardButton(
                text="✅ Подтвердить выбор",
                callback_data="confirm_groups"
            )
        ])
        
        markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
        
        await callback.message.edit_text(
            f"📢 Выберите группы для отправки поста\n"
            f"Выбрано: {len(selected_groups)} групп",
            reply_markup=markup
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при выборе группы: {str(e)}")
        await callback.message.edit_text("❌ Ошибка при выборе группы")
        await state.clear()

@dp.callback_query(PostStates.waiting_for_groups, lambda c: c.data == "confirm_groups")
async def confirm_groups(callback: types.CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        selected_groups = data.get('selected_groups', [])
        
        if not selected_groups:
            await callback.message.edit_text("❌ Выберите хотя бы одну группу")
            return
            
        # Переходим к выбору аккаунтов
        accounts = await Database.get_accounts()
        active_accounts = [acc for acc in accounts if acc['status'] == 'active']
        
        if not active_accounts:
            await callback.message.edit_text("❌ Нет доступных аккаунтов для отправки")
            await state.clear()
            return
            
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=account['phone'],
                        callback_data=f"select_account_{account['id']}"
                    )
                ] for account in active_accounts
            ] + [
                [
                    types.InlineKeyboardButton(
                        text="✅ Подтвердить выбор",
                        callback_data="confirm_accounts"
                    )
                ]
            ]
        )
        
        # Сохраняем выбранные группы и очищаем список выбранных аккаунтов
        await state.update_data(selected_groups=selected_groups, selected_accounts=[])
        await state.set_state(PostStates.waiting_for_accounts)
        
        await callback.message.edit_text(
            "👤 Выберите аккаунты для отправки поста\n"
            "Можно выбрать несколько аккаунтов",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.exception(f"Ошибка при подтверждении групп: {str(e)}")
        await callback.message.edit_text("❌ Ошибка при подтверждении выбора")
        await state.clear()

@dp.callback_query(PostStates.waiting_for_accounts, lambda c: c.data.startswith('select_account_'))
async def select_account(callback: types.CallbackQuery, state: FSMContext):
    try:
        account_id = int(callback.data.split('_')[2])
        data = await state.get_data()
        selected_accounts = data.get('selected_accounts', [])
        selected_groups = data.get('selected_groups', [])  # Сохраняем выбранные группы
        
        if account_id in selected_accounts:
            selected_accounts.remove(account_id)
        else:
            selected_accounts.append(account_id)
            
        await state.update_data(selected_accounts=selected_accounts, selected_groups=selected_groups)
        
        # Обновляем клавиатуру
        accounts = await Database.get_accounts()
        active_accounts = [acc for acc in accounts if acc['status'] == 'active']
        
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=f"{'✅ ' if acc['id'] in selected_accounts else ''}{acc['phone']}",
                        callback_data=f"select_account_{acc['id']}"
                    )
                ] for acc in active_accounts
            ] + [
                [
                    types.InlineKeyboardButton(
                        text="✅ Подтвердить выбор",
                        callback_data="confirm_accounts"
                    )
                ]
            ]
        )
        
        await callback.message.edit_reply_markup(reply_markup=keyboard)
        
    except Exception as e:
        logger.exception(f"Ошибка при выборе аккаунта: {str(e)}")
        await callback.message.edit_text("❌ Ошибка при выборе аккаунта")
        await state.clear()

@dp.callback_query(PostStates.waiting_for_accounts, lambda c: c.data == "confirm_accounts")
async def confirm_accounts(callback: types.CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        selected_groups = data.get('selected_groups', [])
        selected_accounts = data.get('selected_accounts', [])
        message_data = data.get('message_data', {})
        is_scheduled = data.get('is_scheduled', False)

        if not selected_groups or not selected_accounts:
            await callback.message.edit_text("❌ Не выбраны группы или аккаунты")
            await state.clear()
            return

        if is_scheduled:
            # Для отложенного поста запрашиваем время
            await state.set_state(PostStates.waiting_for_schedule)
            await callback.message.edit_text(
                "🕒 Укажите время отправки поста в формате:\n"
                "ДД.ММ ЧЧ:ММ\n"
                "Например: 25.03 15:30\n\n"
                "Или укажите через сколько минут отправить:\n"
                "+30 (через 30 минут)\n"
                "+60 (через час)\n"
                "+120 (через 2 часа)"
            )
            return

        # Отключаем кнопки и показываем статус
        await callback.message.edit_text(
            "🔄 Начинаем отправку...\n"
            "Пожалуйста, подождите."
        )

        success_count = 0
        error_count = 0
        account_index = 0
        total_accounts = len(selected_accounts)
        total_groups = len(selected_groups)
        processed = 0
        start_time = time.time()

        # Получаем информацию о группах
        groups_info = []
        for group_id in selected_groups:
            group = await Database.get_group_by_id(group_id)
            if group:
                groups_info.append({
                    'id': group['group_id'],
                    'title': group['title']
                })

        # Распределяем группы между аккаунтами
        for group_info in groups_info:
            # Получаем следующий аккаунт
            account = await Database.get_account_by_id(selected_accounts[account_index])
            if not account:
                continue

            account_phone = account['phone']
            group_id = group_info['id']
            group_title = group_info['title']

            try:
                # Обновляем статус
                processed += 1
                progress = int((processed / total_groups) * 100)
                current_time = time.time() - start_time
                await callback.message.edit_text(
                    f"🔄 Отправка... {progress}%\n"
                    f"📱 Аккаунт: {account_phone}\n"
                    f"📢 Группа: {group_title}\n\n"
                    f"✅ Успешно: {success_count}\n"
                    f"❌ Ошибок: {error_count}\n"
                    f"⏱ Прошло времени: {current_time:.1f} сек"
                )

                # Создаем клиент для аккаунта
                client = await session_manager.get_client(account['session_file'])
                posting_manager = PostingManager(client, Database, bot)
                
                logger.info(f"Создана задача отправки в группу {group_title} через аккаунт {account_phone}")
                
                # Отправляем сообщение
                success, message = await posting_manager.send_post(group_id, message_data)
                
                # Закрываем клиент
                await client.disconnect()

                if success:
                    logger.info(f"✅ Успешно отправлено в группу {group_title} через аккаунт {account_phone}")
                    success_count += 1
                else:
                    logger.error(f"❌ Ошибка при отправке в группу {group_title} через аккаунт {account_phone}: {message}")
                    error_count += 1
            except Exception as e:
                logger.error(f"❌ Ошибка при отправке в группу {group_title} через аккаунт {account_phone}: {str(e)}")
                error_count += 1
            
            # Переходим к следующему аккаунту
            account_index = (account_index + 1) % total_accounts

        # Отправляем финальные результаты
        total_time = time.time() - start_time
        await callback.message.edit_text(
            f"📊 Результаты отправки:\n\n"
            f"✅ Успешно отправлено: {success_count}\n"
            f"❌ Ошибок: {error_count}\n"
            f"⏱ Время выполнения: {total_time:.1f} сек\n\n"
            f"📱 Использовано аккаунтов: {len(selected_accounts)}\n"
            f"📢 Всего групп: {len(selected_groups)}"
        )
        
        await state.clear()
        
    except Exception as e:
        logger.exception(f"Ошибка при подтверждении аккаунтов: {str(e)}")
        await callback.message.edit_text(
            "❌ Ошибка при отправке:\n"
            f"{str(e)}\n\n"
            "Попробуйте еще раз"
        )
        await state.clear()

@dp.message(PostStates.waiting_for_schedule)
async def process_schedule(message: types.Message, state: FSMContext):
    try:
        schedule_time = None
        now = datetime.now()
        
        # Проверяем формат "+минуты"
        if message.text.startswith('+'):
            try:
                minutes = int(message.text[1:])
                schedule_time = now + timedelta(minutes=minutes)
            except ValueError:
                await message.answer(
                    "❌ Неверный формат времени\n"
                    "Укажите время в формате:\n"
                    "ДД.ММ ЧЧ:ММ\n"
                    "Например: 25.03 15:30\n\n"
                    "Или через сколько минут отправить:\n"
                    "+30 (через 30 минут)\n"
                    "+60 (через час)\n"
                    "+120 (через 2 часа)"
                )
                return
        else:
            # Парсим дату и время
            try:
                date_str = message.text.strip()
                if len(date_str.split()) == 2:
                    date_str = f"{now.year} {date_str}"
                schedule_time = datetime.strptime(date_str, "%Y %d.%m %H:%M")
                
                # Если дата в прошлом, добавляем год
                if schedule_time < now:
                    schedule_time = schedule_time.replace(year=now.year + 1)
            except ValueError:
                await message.answer(
                    "❌ Неверный формат даты и времени\n"
                    "Укажите время в формате:\n"
                    "ДД.ММ ЧЧ:ММ\n"
                    "Например: 25.03 15:30"
                )
                return
        
        if schedule_time <= now:
            await message.answer("❌ Время отправки должно быть в будущем")
            return
            
        # Получаем данные из состояния
        data = await state.get_data()
        message_data = data.get('message_data')
        selected_groups = data.get('selected_groups', [])
        selected_accounts = data.get('selected_accounts', [])
        
        # Сохраняем отложенный пост
        post_id = await Database.add_scheduled_post(
            message_data=message_data,
            groups=selected_groups,
            accounts=selected_accounts,
            schedule_time=int(schedule_time.timestamp())
        )
        
        # Очищаем состояние
        await state.clear()
        
        await message.answer(
            f"✅ Пост #{post_id} запланирован на {schedule_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"Используйте команду '📋 Список постов' для управления"
        )
        
    except Exception as e:
        logger.exception(f"Ошибка при установке времени отправки: {str(e)}")
        await message.answer("❌ Ошибка при планировании поста")
        await state.clear()

@dp.message(PostStates.waiting_for_delay)
async def process_delay(message: types.Message, state: FSMContext):
    try:
        # Проверяем что введено число
        if not message.text.isdigit():
            await message.answer("❌ Пожалуйста, введите число (количество минут)")
            return
            
        delay_minutes = int(message.text)
        if delay_minutes < 1:
            await message.answer("❌ Минимальная задержка - 1 минута")
            return
            
        # Получаем все данные
        data = await state.get_data()
        schedule_time = int(time.time()) + (delay_minutes * 60)
        
        # Сохраняем пост
        post_id = await Database.add_scheduled_post(
            message_data=data['message'],
            groups=data['selected_groups'],
            accounts=data['selected_accounts'],
            schedule_time=schedule_time
        )
        
        # Очищаем состояние
        await state.clear()
        
        await message.answer(
            f"✅ Пост #{post_id} запланирован на {datetime.fromtimestamp(schedule_time).strftime('%d.%m.%Y %H:%M')}\n"
            f"Будет отправлен через {delay_minutes} минут"
        )
        
    except Exception as e:
        logger.exception(f"Ошибка при обработке задержки: {str(e)}")
        await message.answer("❌ Произошла ошибка при планировании поста")
        await state.clear()

# Обработчик кнопки настроек
@dp.message(lambda m: m.text == "⚙️ Настройки")
async def settings_menu(message: types.Message):
    logger.info("Открыто меню настроек")
    try:
        settings = await Database.get_all_settings()
        delay = int(settings.get('default_delay', DEFAULT_DELAY))
        threads = int(settings.get('max_threads', MAX_THREADS))
        retries = int(settings.get('max_retries', MAX_RETRIES))
        
        logger.debug(f"Текущие настройки: delay={delay}, threads={threads}, retries={retries}")
        
        keyboard = types.ReplyKeyboardMarkup(
            keyboard=[
                [
                    types.KeyboardButton(text="⏱ Интервал между постами"),
                    types.KeyboardButton(text="🔄 Количество потоков")
                ],
                [
                    types.KeyboardButton(text="🔁 Количество попыток"),
                    types.KeyboardButton(text="◀️ Назад")
                ]
            ],
            resize_keyboard=True
        )
        
        current_settings = (
            f"⚙️ Текущие настройки:\n\n"
            f"⏱ Интервал между постами: {format_time(delay)}\n"
            f"🔄 Количество потоков: {threads}\n"
            f"🔁 Количество попыток: {retries}"
        )
        
        await message.answer(current_settings, reply_markup=keyboard)
    except Exception as e:
        logger.exception("Ошибка при загрузке настроек")
        await message.answer("❌ Ошибка при загрузке настроек")

# Обработчик кнопки "Назад"
@dp.message(lambda m: m.text == "◀️ Назад")
async def back_to_main(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state in [SettingsStates.waiting_for_delay, 
                        SettingsStates.waiting_for_threads,
                        SettingsStates.waiting_for_retries]:
        await state.clear()
        await settings_menu(message)
    elif current_state and current_state.startswith('GroupStates:'):
        # Если мы в состоянии работы с группами
        await state.clear()
        await manage_groups_menu(message)
    else:
        await state.clear()
        await start_command(message)

# Обработчик настройки интервала
@dp.message(lambda m: m.text == "⏱ Интервал между постами")
async def set_delay(message: types.Message, state: FSMContext):
    settings = await Database.get_all_settings()
    current_delay = int(settings.get('default_delay', DEFAULT_DELAY))
    
    await state.set_state(SettingsStates.waiting_for_delay)
    await message.answer(
        "⏱ Введите интервал между постами в минутах\n\n"
        "Примеры:\n"
        "1 = 1 минута\n"
        "60 = 1 час (60 минут)\n"
        "1440 = 24 часа (1440 минут)\n\n"
        f"Текущее значение: {format_time(current_delay)}\n\n"
        "Нажмите ◀️ Назад для отмены"
    )

# Обработчик настройки потоков
@dp.message(lambda m: m.text == "🔄 Количество потоков")
async def set_threads(message: types.Message, state: FSMContext):
    settings = await Database.get_all_settings()
    current_threads = int(settings.get('max_threads', MAX_THREADS))
    
    await state.set_state(SettingsStates.waiting_for_threads)
    await message.answer(
        "🔄 Введите количество одновременных потоков\n"
        "Рекомендуется не более 5 потоков\n"
        f"Текущее значение: {current_threads}\n\n"
        "Нажмите ◀️ Назад для отмены"
    )

# Обработчик настройки попыток
@dp.message(lambda m: m.text == "🔁 Количество попыток")
async def set_retries(message: types.Message, state: FSMContext):
    settings = await Database.get_all_settings()
    current_retries = int(settings.get('max_retries', MAX_RETRIES))
    
    await state.set_state(SettingsStates.waiting_for_retries)
    await message.answer(
        "🔁 Введите количество попыток отправки при ошибке\n"
        "Рекомендуется 3-5 попыток\n"
        f"Текущее значение: {current_retries}\n\n"
        "Нажмите ◀️ Назад для отмены"
    )

# Обработчик ввода интервала
@dp.message(SettingsStates.waiting_for_delay)
async def process_delay(message: types.Message, state: FSMContext):
    delay_seconds = parse_time(message.text)
    
    if delay_seconds is None:
        await message.answer(
            "❌ Неверный формат!\n"
            "Введите количество минут числом, например: 30"
        )
        return
    
    if delay_seconds < 60:  # Минимум 1 минута
        await message.answer("❌ Интервал не может быть меньше 1 минуты!")
        return
    
    await Database.update_setting('default_delay', delay_seconds)
    await state.clear()
    await message.answer(f"✅ Интервал между постами установлен: {format_time(delay_seconds)}")

# Обработчик ввода потоков
@dp.message(SettingsStates.waiting_for_threads)
async def process_threads(message: types.Message, state: FSMContext):
    try:
        threads = int(message.text.strip())
        if threads < 1:
            await message.answer("❌ Количество потоков не может быть меньше 1!")
            return
        if threads > 10:
            await message.answer("⚠️ Большое количество потоков может привести к блокировке!")
        
        await Database.update_setting('max_threads', threads)
        posting_pool.max_threads = threads  # Обновляем текущий пул
        await state.clear()
        await message.answer(f"✅ Количество потоков установлено: {threads}")
        
    except ValueError:
        await message.answer("❌ Введите корректное число!")

# Обработчик ввода попыток
@dp.message(SettingsStates.waiting_for_retries)
async def process_retries(message: types.Message, state: FSMContext):
    try:
        retries = int(message.text.strip())
        if retries < 1:
            await message.answer("❌ Количество попыток не может быть меньше 1!")
            return
        if retries > 10:
            await message.answer("⚠️ Большое количество попыток может увеличить время отправки!")
        
        await Database.update_setting('max_retries', retries)
        await state.clear()
        await message.answer(f"✅ Количество попыток установлено: {retries}")
        
    except ValueError:
        await message.answer("❌ Введите корректное число!")

# Обработчик кнопки управления аккаунтами
@dp.message(lambda m: m.text == "👤 Управление аккаунтами")
async def accounts_menu(message: types.Message):
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [
                types.KeyboardButton(text="👤 Добавить аккаунт"),
                types.KeyboardButton(text="📊 Статус аккаунтов")
            ],
            [
                types.KeyboardButton(text="◀️ Назад")
            ]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        "👤 Управление аккаунтами\n"
        "Выберите действие:",
        reply_markup=keyboard
    )

# Обработчик кнопки управления группами
@dp.message(lambda m: m.text == "👥 Управление группами")
async def manage_groups_menu(message: types.Message):
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [
                types.KeyboardButton(text="➕ Добавить группу"),
                types.KeyboardButton(text="📋 Список групп")
            ],
            [
                types.KeyboardButton(text="❌ Удалить группу"),
                types.KeyboardButton(text="🔍 Проверка групп")
            ],
            [
                types.KeyboardButton(text="📦 Оптомгруппы"),
                types.KeyboardButton(text="◀️ Назад")
            ]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        "👥 Управление группами\n"
        "Выберите действие:",
        reply_markup=keyboard
    )

@dp.message(lambda m: m.text == "📦 Оптомгруппы")
async def bulk_groups_menu(message: types.Message, state: FSMContext):
    # Очищаем текущее состояние при входе в меню
    await state.clear()
    
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [
                types.KeyboardButton(text="➕ Добавить оптомгруппу"),
                types.KeyboardButton(text="📋 Список оптомгрупп")
            ],
            [
                types.KeyboardButton(text="✏️ Редактировать оптомгруппу"),
                types.KeyboardButton(text="❌ Удалить оптомгруппу")
            ],
            [
                types.KeyboardButton(text="◀️ Назад")
            ]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        "📦 Управление оптомгруппами\n"
        "Выберите действие:",
        reply_markup=keyboard
    )

@dp.message(lambda m: m.text == "➕ Добавить оптомгруппу")
async def add_bulk_group_start(message: types.Message, state: FSMContext):
    await state.set_state(GroupStates.waiting_for_bulk_group_name)
    await message.answer(
        "📝 Введите название новой оптомгруппы\n"
        "Например: Реклама Москва\n\n"
        "Для отмены нажмите ◀️ Назад"
    )

@dp.message(GroupStates.waiting_for_bulk_group_name)
async def process_bulk_group_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    
    if len(name) < 3 or len(name) > 50:
        await message.answer(
            "❌ Название должно быть от 3 до 50 символов\n"
            "Попробуйте еще раз"
        )
        return
        
    # Сохраняем название
    await state.update_data(bulk_group_name=name)
    
    # Получаем список групп
    groups = await Database.get_active_groups()
    if not groups:
        await message.answer("❌ Нет доступных групп для добавления")
        await state.clear()
        return
        
    # Создаем клавиатуру для выбора групп
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=f"⭕️ {group['title']}",
                    callback_data=f"select_bulk_group_{group['id']}"
                )
            ] for group in groups
        ] + [
            [
                types.InlineKeyboardButton(
                    text="✅ Подтвердить выбор",
                    callback_data="confirm_bulk_group_selection"
                )
            ]
        ]
    )
    
    await state.update_data(selected_groups=[])
    await state.set_state(GroupStates.waiting_for_bulk_group_selection)
    await message.answer(
        f"Выберите группы для оптомгруппы '{name}'\n"
        "Нажмите на группу, чтобы выбрать её",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data.startswith('select_bulk_group_'))
async def select_bulk_group(callback: types.CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split('_')[3])
        logger.info(f"Выбор группы {group_id} для оптомгруппы")
        
        data = await state.get_data()
        selected_groups = data.get('selected_groups', [])
        bulk_group_name = data.get('bulk_group_name', '')
        edit_bulk_group_id = data.get('edit_bulk_group_id')  # Получаем ID редактируемой группы
        
        # Добавляем или удаляем группу из списка
        if group_id in selected_groups:
            selected_groups.remove(group_id)
            logger.info(f"Группа {group_id} удалена из выбранных")
        else:
            selected_groups.append(group_id)
            logger.info(f"Группа {group_id} добавлена к выбранным")
            
        # Сохраняем обновленный список
        await state.update_data(selected_groups=selected_groups)
        
        # Получаем список всех групп
        groups = await Database.get_active_groups()
        if not groups:
            logger.error("Нет доступных групп для выбора")
            await callback.answer("❌ Нет доступных групп", show_alert=True)
            return
            
        # Определяем callback_data для кнопки подтверждения
        confirm_callback = "confirm_bulk_group_edit" if edit_bulk_group_id else "confirm_bulk_group_selection"
        
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=f"{'✅' if group['id'] in selected_groups else '⭕️'} {group['title']}",
                        callback_data=f"select_bulk_group_{group['id']}"
                    )
                ] for group in groups
            ] + [
                [
                    types.InlineKeyboardButton(
                        text="✅ Подтвердить изменения" if edit_bulk_group_id else "✅ Подтвердить выбор",
                        callback_data=confirm_callback
                    )
                ]
            ]
        )
        
        message_text = (
            f"{'Редактирование' if edit_bulk_group_id else 'Создание'} оптомгруппы "
            f"'{bulk_group_name}'\n"
            f"Выбрано: {len(selected_groups)} групп"
        )
        
        await callback.message.edit_text(message_text, reply_markup=keyboard)
        logger.info(f"Обновлен список выбранных групп: {selected_groups}")
        
    except ValueError as e:
        logger.error(f"Ошибка при парсинге ID группы: {str(e)}")
        await callback.answer("❌ Некорректный формат ID группы", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при выборе группы: {str(e)}")
        await callback.answer("❌ Произошла ошибка при выборе группы", show_alert=True)

@dp.callback_query(lambda c: c.data == "confirm_bulk_group_selection")
async def confirm_bulk_group_selection(callback: types.CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        selected_groups = data.get('selected_groups', [])
        name = data.get('bulk_group_name')
        
        logger.info(f"Подтверждение создания оптомгруппы '{name}' с группами: {selected_groups}")
        
        if not selected_groups:
            logger.warning("Попытка создания оптомгруппы без выбранных групп")
            await callback.answer("❌ Выберите хотя бы одну группу!", show_alert=True)
            return
            
        # Создаем новую оптомгруппу
        bulk_group_id = await Database.add_bulk_group(name, selected_groups)
        logger.info(f"Создана новая оптомгруппа с ID {bulk_group_id}")
        
        # Получаем названия выбранных групп
        groups = await Database.get_active_groups()
        selected_titles = [
            group['title'] for group in groups 
            if group['id'] in selected_groups
        ]
        
        success_message = (
            f"✅ Оптомгруппа '{name}' успешно создана!\n\n"
            f"📋 Группы ({len(selected_groups)}):\n"
            f"{chr(10).join('• ' + title for title in selected_titles)}"
        )
        
        await callback.message.edit_text(success_message)
        logger.info(f"Оптомгруппа '{name}' успешно создана с {len(selected_groups)} группами")
        
        # Показываем обновленный список оптомгрупп
        await list_bulk_groups(callback.message)
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при создании оптомгруппы: {str(e)}")
        await callback.answer("❌ Произошла ошибка при создании оптомгруппы", show_alert=True)
        await state.clear()

@dp.message(lambda m: m.text == "📋 Список оптомгрупп")
async def list_bulk_groups(message: types.Message):
    try:
        logger.info("Запрос списка оптомгрупп")
        bulk_groups = await Database.get_bulk_groups()
        
        if not bulk_groups:
            logger.info("Список оптомгрупп пуст")
            await message.answer(
                "📝 У вас нет оптомгрупп\n"
                "Нажмите '➕ Добавить оптомгруппу' чтобы создать"
            )
            return
        
        # Формируем текст
        text = "📋 Список оптомгрупп:\n\n"
        for bg in bulk_groups:
            text += f"📦 {bg['name']} (ID: {bg['id']})\n"
            text += f"Групп: {len(bg['groups'])}\n"
            text += f"Создана: {datetime.fromtimestamp(bg['created_at']).strftime('%d.%m.%Y %H:%M')}\n"
            text += f"Группы в составе:\n"
            for group in bg['groups']:
                text += f"• {group['title']}"
                if group['username']:
                    text += f" (@{group['username']})"
                text += "\n"
            text += "\n"
        
        logger.info(f"Отображение {len(bulk_groups)} оптомгрупп с полной информацией")
        await message.answer(text)
        
    except Exception as e:
        logger.error(f"Ошибка при получении списка оптомгрупп: {str(e)}")
        await message.answer("❌ Ошибка при получении списка оптомгрупп")

@dp.message(lambda m: m.text == "✏️ Редактировать оптомгруппу")
async def edit_bulk_group_start(message: types.Message):
    bulk_groups = await Database.get_bulk_groups()
    
    if not bulk_groups:
        await message.answer("❌ Нет оптомгрупп для редактирования")
        return
        
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=bg['name'],
                    callback_data=f"edit_bulk_group_{bg['id']}"
                )
            ] for bg in bulk_groups
        ]
    )
    
    await message.answer(
        "Выберите оптомгруппу для редактирования:",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data.startswith('edit_bulk_group_'))
async def edit_bulk_group(callback: types.CallbackQuery, state: FSMContext):
    try:
        # Очищаем предыдущее состояние
        await state.clear()
        
        bulk_group_id = int(callback.data.split('_')[3])
        logger.info(f"Начато редактирование оптомгруппы {bulk_group_id}")
        
        bulk_group = await Database.get_bulk_group_by_id(bulk_group_id)
        
        if not bulk_group:
            error_msg = f"Оптомгруппа {bulk_group_id} не найдена"
            logger.error(error_msg)
            await callback.answer("❌ Оптомгруппа не найдена", show_alert=True)
            return
        
        # Устанавливаем состояние перед сохранением данных
        await state.set_state(GroupStates.waiting_for_bulk_group_selection)
        
        # Получаем ID групп из массива groups
        selected_groups = [group['id'] for group in bulk_group['groups']]
        
        # Сохраняем данные в состояние
        await state.update_data(
            edit_bulk_group_id=bulk_group_id,
            bulk_group_name=bulk_group['name'],
            selected_groups=selected_groups
        )
        
        logger.info(f"Загружены текущие данные оптомгруппы: {bulk_group}")
        
        # Получаем список групп
        groups = await Database.get_active_groups()
        if not groups:
            error_msg = "Нет доступных групп для редактирования"
            logger.error(error_msg)
            await callback.answer(f"❌ {error_msg}", show_alert=True)
            await state.clear()
            return
        
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=f"{'✅' if group['id'] in selected_groups else '⭕️'} {group['title']}",
                        callback_data=f"select_bulk_group_{group['id']}"
                    )
                ] for group in groups
            ] + [
                [
                    types.InlineKeyboardButton(
                        text="✅ Подтвердить изменения",
                        callback_data="confirm_bulk_group_edit"
                    )
                ]
            ]
        )
        
        await callback.message.edit_text(
            f"Редактирование оптомгруппы '{bulk_group['name']}'\n"
            f"Выбрано: {len(selected_groups)} групп",
            reply_markup=keyboard
        )
        
        logger.info(f"Открыт интерфейс редактирования оптомгруппы {bulk_group_id}")
        
    except ValueError as e:
        error_msg = f"Ошибка при парсинге ID оптомгруппы: {str(e)}"
        logger.error(error_msg)
        await callback.answer("❌ Некорректный формат ID", show_alert=True)
        await state.clear()
    except Exception as e:
        error_msg = f"Ошибка при начале редактирования оптомгруппы: {str(e)}"
        logger.error(error_msg)
        await callback.answer("❌ Произошла ошибка", show_alert=True)
        await state.clear()

async def update_bulk_group_with_groups(bulk_group_id: int, selected_groups: list) -> tuple[bool, str]:
    """Обновление оптомгруппы с выбранными группами"""
    try:
        if not bulk_group_id:
            return False, "ID оптомгруппы не найден"
            
        if not selected_groups:
            return False, "Не выбраны группы"
            
        # Обновляем существующую оптомгруппу
        success = await Database.update_bulk_group(bulk_group_id, group_ids=selected_groups)
        
        if success:
            # Получаем названия выбранных групп
            groups = await Database.get_active_groups()
            selected_titles = [
                group['title'] for group in groups 
                if group['id'] in selected_groups
            ]
            
            success_message = (
                f"✅ Оптомгруппа обновлена!\n\n"
                f"📋 Группы ({len(selected_groups)}):\n"
                f"{chr(10).join('• ' + title for title in selected_titles)}"
            )
            
            return True, success_message
        else:
            return False, "Ошибка при обновлении оптомгруппы"
            
    except Exception as e:
        return False, f"Ошибка: {str(e)}"

@dp.callback_query(lambda c: c.data == "confirm_bulk_group_edit")
async def confirm_bulk_group_edit(callback: types.CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        bulk_group_id = data.get('edit_bulk_group_id')
        selected_groups = data.get('selected_groups', [])
        bulk_group_name = data.get('bulk_group_name', '')
        
        if not bulk_group_id:
            await callback.answer("❌ Группа не найдена", show_alert=True)
            await state.clear()
            return
            
        if not selected_groups:
            await callback.answer("❌ Выберите хотя бы одну группу!", show_alert=True)
            return
            
        success = await Database.update_bulk_group(bulk_group_id, group_ids=selected_groups)
        
        if success:
            # Получаем обновленную оптомгруппу
            bulk_group = await Database.get_bulk_group_by_id(bulk_group_id)
            
            success_message = (
                f"✅ Оптомгруппа '{bulk_group_name}' обновлена!\n\n"
                f"📋 Группы ({len(bulk_group['groups'])}):\n"
                f"{chr(10).join('• ' + group['title'] for group in bulk_group['groups'])}"
            )
            
            await callback.message.edit_text(success_message)
            await list_bulk_groups(callback.message)
            await state.clear()
        else:
            await callback.answer("❌ Ошибка при обновлении групп", show_alert=True)
            
    except Exception as e:
        logger.error(f"Ошибка при подтверждении изменений: {str(e)}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)
        await state.clear()

@dp.message(lambda m: m.text == "❌ Удалить оптомгруппу")
async def delete_bulk_group_start(message: types.Message):
    bulk_groups = await Database.get_bulk_groups()
    
    if not bulk_groups:
        await message.answer("❌ Нет оптомгрупп для удаления")
        return
        
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=f"❌ {bg['name']}",
                    callback_data=f"delete_bulk_group_{bg['id']}"
                )
            ] for bg in bulk_groups
        ]
    )
    
    await message.answer(
        "Выберите оптомгруппу для удаления:",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data.startswith('delete_bulk_group_'))
async def delete_bulk_group(callback: types.CallbackQuery):
    try:
        # Проверяем, не является ли это подтверждением
        if 'confirm' in callback.data:
            bulk_group_id = int(callback.data.split('_')[4])
            logger.info(f"Подтверждение удаления оптомгруппы {bulk_group_id}")
            
            success = await Database.delete_bulk_group(bulk_group_id)
            
            if success:
                logger.info(f"Оптомгруппа {bulk_group_id} успешно удалена")
                await callback.message.edit_text("✅ Оптомгруппа успешно удалена")
            else:
                logger.error(f"Ошибка при удалении оптомгруппы {bulk_group_id}")
                await callback.message.edit_text("❌ Ошибка при удалении оптомгруппы")
            return
            
        bulk_group_id = int(callback.data.split('_')[3])
        logger.info(f"Запрос на удаление оптомгруппы {bulk_group_id}")
        
        bulk_group = await Database.get_bulk_group_by_id(bulk_group_id)
        
        if not bulk_group:
            logger.error(f"Оптомгруппа {bulk_group_id} не найдена")
            await callback.answer("❌ Оптомгруппа не найдена", show_alert=True)
            return
            
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="✅ Да, удалить",
                        callback_data=f"delete_bulk_group_confirm_{bulk_group_id}"
                    ),
                    types.InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data="cancel_bulk_group_delete"
                    )
                ]
            ]
        )
        
        await callback.message.edit_text(
            f"⚠️ Вы действительно хотите удалить оптомгруппу '{bulk_group['name']}'?",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Ошибка при обработке удаления оптомгруппы: {str(e)}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data == "cancel_bulk_group_delete")
async def cancel_bulk_group_delete(callback: types.CallbackQuery):
    try:
        groups = await Database.get_active_groups()
        
        if not groups:
            await callback.message.edit_text("Список групп пуст")
            return
            
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(
                    text=f"❌ {group['title']}", 
                    callback_data=f"delete_group_{group['id']}"
                )] for group in groups
            ]
        )
        
        await callback.message.edit_text(
            "Выберите группу для удаления:",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.exception(f"Ошибка при отмене удаления: {str(e)}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.message(lambda m: m.text == "⏰ Отложенный пост")
async def scheduled_post_start(message: types.Message, state: FSMContext):
    await state.set_state(PostStates.waiting_for_content)
    await state.update_data(is_scheduled=True)
    await message.answer(
        "📝 Отправьте контент для отложенного поста.\n"
        "Можно добавить фото, видео или документ.\n"
        "Для отмены нажмите /cancel"
    )

@dp.message(lambda m: m.text == "📋 Список постов")
async def list_scheduled_posts(message: types.Message):
    try:
        posts = await Database.get_pending_posts()
        
        if not posts:
            await message.answer(
                "📭 Нет отложенных постов.\n"
                "Нажмите '⏰ Отложенный пост' чтобы создать новый."
            )
            return
            
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=f"🕒 Пост #{post['id']} ({datetime.fromtimestamp(post['schedule_time']).strftime('%d.%m %H:%M')})",
                        callback_data=f"post_menu_{post['id']}"
                    )
                ] for post in posts
            ]
        )
        
        await message.answer(
            "📋 Список отложенных постов:\n"
            "Нажмите на пост для управления",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.exception(f"Ошибка при получении списка постов: {str(e)}")
        await message.answer("❌ Ошибка при получении списка постов")

@dp.callback_query(lambda c: c.data.startswith('post_menu_'))
async def post_menu(callback: types.CallbackQuery):
    try:
        post_id = int(callback.data.split('_')[2])
        post = await Database.get_post_by_id(post_id)
        
        if not post:
            await callback.message.edit_text("❌ Пост не найден")
            return
            
        schedule_time = datetime.fromtimestamp(post['schedule_time'])
        groups = [await Database.get_group_by_id(str(g)) for g in post['groups']]
        accounts = [await Database.get_account_by_id(a) for a in post['accounts']]
        
        status_text = (
            f"📝 Пост #{post['id']}\n"
            f"⏰ Запланирован на: {schedule_time.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"📢 Группы для отправки:\n"
            + "\n".join([f"• {g['title']}" for g in groups if g]) + "\n\n"
            f"👤 Аккаунты для отправки:\n"
            + "\n".join([f"• {a['phone']}" for a in accounts if a])
        )
        
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🚀 Отправить сейчас",
                    callback_data=f"send_now_{post_id}"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="❌ Отменить пост",
                    callback_data=f"cancel_post_{post_id}"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="◀️ Назад к списку",
                    callback_data="scheduled_posts_list"
                )
            ]
        ])
        
        await callback.message.edit_text(status_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.exception(f"Ошибка при открытии меню поста: {str(e)}")
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")

@dp.callback_query(lambda c: c.data.startswith('send_now_'))
async def send_post_now(callback: types.CallbackQuery):
    try:
        post_id = int(callback.data.split('_')[2])
        post = await Database.get_post_by_id(post_id)
        
        if not post:
            await callback.message.edit_text("❌ Пост не найден")
            return

        # Показываем начальный статус
        await callback.message.edit_text(
            f"🔄 Подготовка к отправке поста #{post_id}...\n"
            "Пожалуйста, подождите..."
        )

        # Получаем информацию о группах и аккаунтах для отображения
        groups = [await Database.get_group_by_id(str(g)) for g in post['groups']]
        accounts = [await Database.get_account_by_id(a) for a in post['accounts']]
        
        groups_text = "\n".join([f"• {g['title']}" for g in groups if g])
        accounts_text = "\n".join([f"• {a['phone']}" for a in accounts if a])

        # Обновляем сообщение с деталями
        await callback.message.edit_text(
            f"🚀 Начинаем отправку поста #{post_id}\n\n"
            f"📢 Группы для отправки:\n{groups_text}\n\n"
            f"👤 Используемые аккаунты:\n{accounts_text}\n\n"
            "⏳ Идёт отправка..."
        )
            
        # Отправляем пост немедленно
        await process_scheduled_post(post)
        
        # Обновляем статус поста в базе
        await Database.update_post_status(post_id, "sent")
        
        # Показываем финальное сообщение
        await callback.message.edit_text(
            f"✅ Пост #{post_id} успешно отправлен!\n\n"
            f"📢 Отправлено в {len(groups)} групп\n"
            f"👤 Использовано {len(accounts)} аккаунтов\n\n"
            "Детальный отчёт будет отправлен отдельным сообщением."
        )
        
    except Exception as e:
        logger.exception(f"Ошибка при немедленной отправке поста: {str(e)}")
        await callback.message.edit_text(
            f"❌ Ошибка при отправке поста #{post_id}:\n"
            f"{str(e)}\n\n"
            "Проверьте доступность групп и статус аккаунтов."
        )

@dp.callback_query(lambda c: c.data.startswith('cancel_post_'))
async def cancel_scheduled_post(callback: types.CallbackQuery):
    try:
        post_id = int(callback.data.split('_')[2])
        post = await Database.get_post_by_id(post_id)
        
        if not post:
            await callback.message.edit_text("❌ Пост не найден")
            return
            
        if post['status'] != 'pending':
            await callback.message.edit_text(
                f"❌ Невозможно отменить пост #{post_id}\n"
                f"Текущий статус: {post['status']}"
            )
            return

        # Показываем подтверждение
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✅ Да, отменить",
                    callback_data=f"confirm_cancel_post_{post_id}"
                ),
                types.InlineKeyboardButton(
                    text="❌ Нет",
                    callback_data=f"post_menu_{post_id}"
                )
            ]
        ])

        schedule_time = datetime.fromtimestamp(post['schedule_time'])
        await callback.message.edit_text(
            f"⚠️ Вы действительно хотите отменить пост #{post_id}?\n\n"
            f"Запланирован на: {schedule_time.strftime('%d.%m.%Y %H:%M')}\n"
            "Это действие нельзя отменить.",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.exception(f"Ошибка при отмене поста: {str(e)}")
        await callback.message.edit_text(
            f"❌ Ошибка при отмене поста:\n{str(e)}"
        )

@dp.callback_query(lambda c: c.data.startswith('confirm_cancel_post_'))
async def confirm_cancel_post(callback: types.CallbackQuery):
    try:
        post_id = int(callback.data.split('_')[3])
        post = await Database.get_post_by_id(post_id)
        
        if not post:
            await callback.message.edit_text("❌ Пост не найден")
            return
            
        # Отменяем пост
        await Database.update_post_status(post_id, "cancelled")
        
        # Показываем подтверждение
        await callback.message.edit_text(
            f"✅ Пост #{post_id} успешно отменён\n\n"
            "Нажмите '📋 Список постов' чтобы увидеть остальные посты."
        )
        
    except Exception as e:
        logger.exception(f"Ошибка при подтверждении отмены поста: {str(e)}")
        await callback.message.edit_text(
            f"❌ Ошибка при отмене поста:\n{str(e)}"
        )

@dp.callback_query(lambda c: c.data == "scheduled_posts_list")
async def back_to_posts_list(callback: types.CallbackQuery):
    await list_scheduled_posts(callback.message)

async def process_scheduled_post(post: dict):
    """Обработка отложенного поста"""
    try:
        # Получаем аккаунты
        accounts = []
        for account_id in post['accounts']:
            account = await Database.get_account_by_id(account_id)
            if account and account['status'] == 'active':
                accounts.append(account)
        
        if not accounts:
            logger.error(f"Нет доступных аккаунтов для отправки поста #{post['id']}")
            return
            
        # Получаем группы
        groups = []
        for group_id in post['groups']:
            group = await Database.get_group_by_id(str(group_id))
            if group:
                groups.append(group)
        
        if not groups:
            logger.error(f"Нет доступных групп для отправки поста #{post['id']}")
            return
            
        # Создаем список задач для отправки
        tasks = []
        message_data = post['message']
        
        # Распределяем группы между аккаунтами равномерно
        account_index = 0
        for group in groups:
            # Перебираем аккаунты по кругу
            account = accounts[account_index]
            account_index = (account_index + 1) % len(accounts)  # Следующий аккаунт
            
            try:
                client = await session_manager.get_client(account['session_file'])
                posting_manager = PostingManager(client, Database, bot)
                
                # Проверяем статус аккаунта
                can_send, phone = await posting_manager.check_account_status()
                if can_send:
                    # Создаем задачу для отправки
                    task = asyncio.create_task(
                        posting_manager.send_post(
                            str(group['group_id']),
                            message_data
                        )
                    )
                    tasks.append((task, group['title'], account['phone']))
                    logger.info(f"Создана задача отправки в группу {group['title']} через аккаунт {account['phone']}")
                else:
                    logger.warning(f"Аккаунт {account['phone']} заморожен, пропускаем")
                    
            except Exception as e:
                logger.error(f"Ошибка при подготовке отправки в группу {group['title']}: {str(e)}")
        
        # Ждем завершения всех задач
        if tasks:
            success_count = 0
            error_count = 0
            
            for task, group_title, account_phone in tasks:
                try:
                    success, message = await task
                    if success:
                        logger.info(f"✅ Успешно отправлено в группу {group_title} через аккаунт {account_phone}")
                        success_count += 1
                    else:
                        logger.error(f"❌ Ошибка при отправке в группу {group_title} через аккаунт {account_phone}: {message}")
                        error_count += 1
                except Exception as e:
                    logger.error(f"❌ Ошибка при отправке в группу {group_title} через аккаунт {account_phone}: {str(e)}")
                    error_count += 1
            
            # Отправляем результаты через бота
            try:
                user_id = post.get('user_id')  # ID пользователя, создавшего пост
                if user_id:
                    await bot.send_message(
                        user_id,
                        f"📊 Результаты отправки поста #{post['id']}:\n"
                        f"✅ Успешно: {success_count}\n"
                        f"❌ Ошибок: {error_count}"
                    )
                else:
                    logger.error("Не удалось отправить результаты пользователю")
            except Exception as e:
                logger.error(f"Не удалось отправить результаты пользователю: {str(e)}")
        
        # Обновляем статус поста
        await Database.update_post_status(post['id'], "sent")
        logger.info(f"✅ Пост #{post['id']} успешно отправлен")
            
    except Exception as e:
        logger.exception(f"Ошибка при обработке отложенного поста: {str(e)}")

async def check_scheduled_posts():
    """Проверка и отправка отложенных постов"""
    while True:
        try:
            current_time = int(time.time())
            posts = await Database.get_pending_posts()
            
            for post in posts:
                if post['schedule_time'] <= current_time:
                    logger.info(f"Отправка отложенного поста #{post['id']}")
                    await process_scheduled_post(post)
            
            await asyncio.sleep(60)  # Проверяем каждую минуту
            
        except Exception as e:
            logger.exception(f"Ошибка при проверке отложенных постов: {str(e)}")
            await asyncio.sleep(60)

def format_time(seconds: int) -> str:
    """Форматирует время в минуты и часы"""
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} мин"
    hours = minutes // 60
    remaining_minutes = minutes % 60
    if remaining_minutes == 0:
        return f"{hours} ч"
    return f"{hours} ч {remaining_minutes} мин"

def parse_time(time_str: str) -> Optional[int]:
    """Преобразует строку с минутами в секунды"""
    try:
        minutes = int(time_str.strip())
        if minutes < 1:
            return None
        return minutes * 60
    except ValueError:
        return None

# Обработчик добавления группы
@dp.message(lambda m: m.text == "➕ Добавить группу")
async def add_group_start(message: types.Message, state: FSMContext):
    await state.set_state(GroupStates.waiting_for_group)
    await message.answer(
        "Отправьте @username группы или её ID.\n\n"
        "Примеры:\n"
        "@group_name\n"
        "-1001234567890\n\n"
        "Для отмены нажмите ◀️ Назад"
    )

@dp.message(GroupStates.waiting_for_group)
async def process_group_input(message: types.Message, state: FSMContext):
    """Обработка ввода группы"""
    try:
        input_text = message.text.strip()
        
        # Проверяем, является ли это пригласительной ссылкой
        if "t.me/" in input_text or "telegram.me/" in input_text:
            # Создаем клиент для проверки группы
            accounts = await Database.get_active_accounts()
            if not accounts:
                await message.answer("❌ Нет доступных аккаунтов для проверки группы!")
                return
                
            session_file = accounts[0]["session_file"]
            client = await session_manager.get_client(session_file)
            
            try:
                # Сначала пробуем присоединиться к группе
                await message.answer("🔄 Пытаюсь присоединиться к группе...")
                
                # Извлекаем hash из ссылки
                invite_hash = None
                if '+' in input_text:
                    invite_hash = input_text.split('+')[-1]
                elif 'joinchat/' in input_text:
                    invite_hash = input_text.split('joinchat/')[-1]
                
                try:
                    if invite_hash:
                        # Для приватных групп используем ImportChatInviteRequest
                        try:
                            await client(ImportChatInviteRequest(invite_hash))
                            await message.answer("✅ Успешно присоединились к группе")
                        except UserAlreadyParticipantError:
                            # Если уже участник - это нормально, продолжаем
                            logger.info("Пользователь уже является участником группы")
                            pass
                        except (InviteHashInvalidError, InviteHashExpiredError):
                            await message.answer("❌ Ссылка-приглашение недействительна или истекла")
                            return
                        except ChannelPrivateError:
                            await message.answer("❌ Группа является приватной и недоступна")
                            return
                    else:
                        # Для публичных групп используем JoinChannelRequest
                        try:
                            await client(JoinChannelRequest(input_text))
                            await message.answer("✅ Успешно присоединились к группе")
                        except UserAlreadyParticipantError:
                            # Если уже участник - это нормально, продолжаем
                            logger.info("Пользователь уже является участником группы")
                            pass
                        except Exception as e:
                            logger.error(f"Ошибка при присоединении к публичной группе: {str(e)}")
                            await message.answer("❌ Не удалось присоединиться к группе. Проверьте ссылку и права доступа.")
                            return
                except Exception as e:
                    # Если возникла ошибка при присоединении, но это не критично - продолжаем
                    logger.warning(f"Некритичная ошибка при присоединении к группе: {str(e)}")
                    pass

                # После присоединения получаем информацию о группе
                await asyncio.sleep(2)  # Небольшая задержка после присоединения
                
                try:
                    # Пробуем получить сущность по ссылке
                    group_entity = await client.get_entity(input_text)
                except ValueError:
                    # Если не получилось по ссылке, пробуем по hash
                    try:
                        messages = await client.get_messages(invite_hash, limit=1)
                        if messages and messages[0].peer_id:
                            group_entity = await client.get_entity(messages[0].peer_id)
                        else:
                            raise ValueError("Не удалось получить информацию о группе")
                    except Exception as e:
                        logger.error(f"Ошибка при получении информации о группе: {str(e)}")
                        await message.answer("❌ Не удалось получить информацию о группе.")
                        return
                
                if hasattr(group_entity, 'id'):
                    group_id = str(group_entity.id)
                    if not group_id.startswith('-100'):
                        group_id = f"-100{group_id}"
                        
                    # Получаем дополнительную информацию о группе
                    title = getattr(group_entity, 'title', 'Без названия')
                    username = getattr(group_entity, 'username', None)
                    
                    # Добавляем группу в базу
                    await Database.add_group(
                        group_id=group_id.replace('-100', ''),
                        title=title,
                        username=username,
                        invite_link=input_text
                    )
                    
                    await message.answer(
                        f"✅ Группа успешно добавлена!\n\n"
                        f"📝 Название: {title}\n"
                        f"🆔 ID: {group_id}\n"
                        f"👥 Username: {f'@{username}' if username else 'отсутствует'}\n"
                        f"🔗 Ссылка сохранена"
                    )
                    await state.clear()
                    return
                    
            except Exception as e:
                logger.error(f"Ошибка при получении информации о группе: {str(e)}")
                await message.answer("❌ Не удалось получить информацию о группе по ссылке.")
                return

        # Если это не ссылка, проверяем стандартные форматы
        if input_text.startswith('@'):
            username = input_text[1:]
            # Создаем клиент для проверки группы
            accounts = await Database.get_active_accounts()
            if not accounts:
                await message.answer("❌ Нет доступных аккаунтов для проверки группы!")
                return
                
            session_file = accounts[0]["session_file"]
            client = await session_manager.get_client(session_file)
            
            try:
                # Получаем информацию о группе по username
                group = await client.get_entity(input_text)
                group_id = str(group.id)
                if not group_id.startswith('-100'):
                    group_id = f"-100{group_id}"
                    
                await Database.add_group(
                    group_id=group_id.replace('-100', ''),
                    title=group.title,
                    username=username
                )
                
                await message.answer(
                    f"✅ Группа успешно добавлена!\n\n"
                    f"📝 Название: {group.title}\n"
                    f"🆔 ID: {group_id}\n"
                    f"👥 Username: @{username}"
                )
                await state.clear()
                return
                
            except Exception as e:
                logger.error(f"Ошибка при получении информации о группе: {str(e)}")
                await message.answer("❌ Не удалось получить информацию о группе.")
                return
                
        elif input_text.startswith('-100'):
            group_id = input_text.replace('-100', '')
            if not group_id.isdigit():
                await message.answer("❌ Неверный формат ID группы!")
                return
                
            # Создаем клиент для проверки группы
            accounts = await Database.get_active_accounts()
            if not accounts:
                await message.answer("❌ Нет доступных аккаунтов для проверки группы!")
                return
                
            session_file = accounts[0]["session_file"]
            client = await session_manager.get_client(session_file)
            
            try:
                # Получаем информацию о группе по ID
                group = await client.get_entity(PeerChannel(int(group_id)))
                
                await Database.add_group(
                    group_id=group_id,
                    title=group.title,
                    username=group.username if hasattr(group, 'username') else None
                )
                
                await message.answer(
                    f"✅ Группа успешно добавлена!\n\n"
                    f"📝 Название: {group.title}\n"
                    f"🆔 ID: -100{group_id}\n"
                    f"👥 Username: {f'@{group.username}' if hasattr(group, 'username') and group.username else 'отсутствует'}"
                )
                await state.clear()
                return
                
            except Exception as e:
                logger.error(f"Ошибка при получении информации о группе: {str(e)}")
                await message.answer("❌ Не удалось получить информацию о группе.")
                return
        
        await message.answer(
            "❌ Неверный формат!\n"
            "Отправьте:\n"
            "- Пригласительную ссылку (https://t.me/...)\n"
            "- Username группы (@group_name)\n"
            "- ID группы (-100...)\n\n"
            "Для отмены нажмите ◀️ Назад"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при добавлении группы: {str(e)}")
        await message.answer("❌ Произошла ошибка при добавлении группы.")
        await state.clear()

# Обработчик просмотра списка групп
@dp.message(lambda m: m.text == "📋 Список групп")
async def list_groups(message: types.Message):
    try:
        groups = await Database.get_active_groups()
        
        if not groups:
            await message.answer(
                "❌ У вас пока нет добавленных групп.\n"
                "Нажмите '➕ Добавить группу' чтобы добавить новую."
            )
            return
        
        groups_text = "📋 Список добавленных групп:\n\n"
        for group in groups:
            username = f"@{group['username']}" if group['username'] else "Приватная группа"
            groups_text += f"• {group['title']}\n  {username}\n  ID: {group['group_id']}\n\n"
        
        await message.answer(groups_text)
        
    except Exception as e:
        logger.exception(f"Ошибка при получении списка групп: {str(e)}")
        await message.answer("❌ Ошибка при получении списка групп")

# Обработчик удаления группы
@dp.message(lambda m: m.text == "❌ Удалить группу")
async def delete_group_menu(message: types.Message):
    try:
        groups = await Database.get_active_groups()
        
        if not groups:
            await message.answer("❌ У вас нет добавленных групп")
            return
        
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(
                    text=f"❌ {group['title']}", 
                    callback_data=f"delete_group_{group['id']}"
                )] for group in groups
            ]
        )
        
        await message.answer(
            "Выберите группу для удаления:",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.exception(f"Ошибка при создании меню удаления групп: {str(e)}")
        await message.answer("❌ Ошибка при загрузке списка групп")

@dp.callback_query(lambda c: c.data.startswith('delete_group_'))
async def delete_group(callback: types.CallbackQuery):
    try:
        # Проверяем, не является ли это подтверждением
        if 'confirm' in callback.data:
            group_id = int(callback.data.split('_')[3])
            group = await Database.get_group_by_id(group_id)
            
            if not group:
                await callback.answer("❌ Группа не найдена", show_alert=True)
                return
                
            # Удаляем группу
            await Database.delete_group(group_id)
            
            # Получаем обновленный список групп
            groups = await Database.get_active_groups()
            
            if not groups:
                await callback.message.edit_text("✅ Группа удалена.\n\nСписок групп пуст.")
                return
                
            # Создаем новую клавиатуру
            keyboard = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(
                        text=f"❌ {group['title']}", 
                        callback_data=f"delete_group_{group['id']}"
                    )] for group in groups
                ]
            )
            
            await callback.message.edit_text(
                "Выберите группу для удаления:",
                reply_markup=keyboard
            )
            await callback.answer("✅ Группа успешно удалена", show_alert=True)
            return
            
        # Если это не подтверждение, показываем сообщение с подтверждением
        group_id = int(callback.data.split('_')[2])
        group = await Database.get_group_by_id(group_id)
        
        if not group:
            await callback.answer("❌ Группа не найдена", show_alert=True)
            return
            
        # Создаем клавиатуру для подтверждения
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="✅ Да, удалить",
                        callback_data=f"delete_group_confirm_{group_id}"
                    ),
                    types.InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data="cancel_delete_group"
                    )
                ]
            ]
        )
        
        await callback.message.edit_text(
            f"⚠️ Вы действительно хотите удалить группу {group['title']}?",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.exception(f"Ошибка при удалении группы: {str(e)}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data == "cancel_delete_group")
async def cancel_delete_group(callback: types.CallbackQuery):
    try:
        groups = await Database.get_active_groups()
        
        if not groups:
            await callback.message.edit_text("Список групп пуст")
            return
            
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(
                    text=f"❌ {group['title']}", 
                    callback_data=f"delete_group_{group['id']}"
                )] for group in groups
            ]
        )
        
        await callback.message.edit_text(
            "Выберите группу для удаления:",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.exception(f"Ошибка при отмене удаления: {str(e)}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)

# Обработчик проверки групп
@dp.message(lambda m: m.text == "🔍 Проверка групп")
async def check_groups_access(message: types.Message):
    try:
        # Получаем все группы
        groups = await Database.get_groups()
        if not groups:
            await message.answer("❌ Нет добавленных групп для проверки")
            return
            
        # Получаем активные аккаунты
        accounts = await Database.get_accounts()
        active_accounts = [acc for acc in accounts if acc['status'] == 'active']
        
        if not active_accounts:
            await message.answer("❌ Нет активных аккаунтов для проверки")
            return
            
        status_message = await message.answer("⌛ Проверяем доступ к группам...")
        results = []
        
        # Проверяем каждую группу с каждым аккаунтом
        for group in groups:
            group_results = {
                'group_id': group['id'],
                'title': group['title'],
                'accounts': []
            }
            
            for account in active_accounts:
                try:
                    client = await session_manager.get_client(account['session_file'])
                    posting_manager = PostingManager(client, Database, bot)
                    
                    # Проверяем доступ
                    can_post, reason = await posting_manager.check_group_access(group['group_id'])
                    
                    group_results['accounts'].append({
                        'phone': account['phone'],
                        'can_post': can_post,
                        'reason': reason
                    })
                    
                except Exception as e:
                    group_results['accounts'].append({
                        'phone': account['phone'],
                        'can_post': False,
                        'reason': str(e)
                    })
                    
            results.append(group_results)
            
        # Формируем отчет
        report = "📊 Результаты проверки групп:\n\n"
        
        for group in results:
            report += f"📢 Группа: {group['title']}\n"
            for acc in group['accounts']:
                status = "✅" if acc['can_post'] else "❌"
                reason = f" ({acc['reason']})" if not acc['can_post'] else ""
                report += f"{status} {acc['phone']}{reason}\n"
            report += "\n"
            
        # Разбиваем отчет на части, если он слишком длинный
        max_length = 4096
        if len(report) > max_length:
            parts = [report[i:i + max_length] for i in range(0, len(report), max_length)]
            for i, part in enumerate(parts):
                if i == 0:
                    await status_message.edit_text(part)
                else:
                    await message.answer(part)
        else:
            await status_message.edit_text(report)
            
    except Exception as e:
        logger.exception(f"Ошибка при проверке групп: {str(e)}")
        await message.answer(f"❌ Ошибка при проверке групп: {str(e)}")

@dp.message(lambda m: m.text == "🤖 Автоматизация постов")
async def automated_post_start(message: types.Message, state: FSMContext):
    """Начало создания автоматизированного поста"""
    # Очищаем предыдущие данные
    await state.clear()
    await state.set_state(PostStates.waiting_for_auto_groups)
    await state.update_data(selected_groups=[])
    
    # Получаем список групп и оптомгрупп
    groups = await Database.get_active_groups()
    bulk_groups = await Database.get_bulk_groups()
    
    if not groups:
        await message.answer(
            "❌ У вас нет добавленных групп.\n"
            "Сначала добавьте хотя бы одну группу!"
        )
        await state.clear()
        return
        
    # Создаем клавиатуру с оптомгруппами и группами
    keyboard = []
    
    # Добавляем оптомгруппы
    if bulk_groups:
        keyboard.extend([
            [
                types.InlineKeyboardButton(
                    text=f"📦 {bg['name']} ({len(bg['groups'])} групп)",
                    callback_data=f"select_bulk_group_post_{bg['id']}"
                )
            ] for bg in bulk_groups
        ])
        # Добавляем разделитель
        keyboard.append([
            types.InlineKeyboardButton(
                text="➖ или выберите отдельные группы ➖",
                callback_data="separator"
            )
        ])
    
    # Добавляем отдельные группы
    keyboard.extend([
        [
            types.InlineKeyboardButton(
                text=f"⭕️ {group['title']}",
                callback_data=f"select_group_{group['id']}"
            )
        ] for group in groups
    ])
    
    # Добавляем кнопку подтверждения
    keyboard.append([
        types.InlineKeyboardButton(
            text="✅ Подтвердить выбор",
            callback_data="confirm_auto_groups"
        )
    ])
    
    markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    await message.answer(
        "👥 Выберите группы для автопостинга\n"
        "Нажмите на группу, чтобы выбрать её.\n"
        "Можно выбрать несколько групп или оптомгруппу.",
        reply_markup=markup
    )

@dp.callback_query(lambda c: c.data == "confirm_auto_groups")
async def confirm_auto_groups(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение выбора групп для автоматизированного поста"""
    data = await state.get_data()
    selected_groups = data.get('selected_groups', [])
    
    if not selected_groups:
        await callback.answer("❌ Выберите хотя бы одну группу!", show_alert=True)
        return
    
    # Переходим к выбору аккаунтов
    await state.set_state(PostStates.waiting_for_auto_accounts)
    
    # Получаем список активных аккаунтов
    accounts = await Database.get_active_accounts()
    if not accounts:
        await callback.message.edit_text(
            "❌ У вас нет активных аккаунтов.\n"
            "Сначала добавьте хотя бы один аккаунт!"
        )
        await state.clear()
        return
    
    # Создаем клавиатуру с аккаунтами
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=f"⭕️ {account['phone']}",
                    callback_data=f"select_account_{account['id']}"
                )
            ] for account in accounts
        ] + [
            [
                types.InlineKeyboardButton(
                    text="✅ Подтвердить выбор",
                    callback_data="confirm_auto_accounts"
                )
            ]
        ]
    )
    
    await callback.message.edit_text(
        "Выберите аккаунты для отправки:\n"
        "Нажмите на аккаунт, чтобы выбрать его.",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data == "confirm_auto_accounts")
async def confirm_auto_accounts(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение выбора аккаунтов для автоматизированного поста"""
    data = await state.get_data()
    selected_accounts = data.get('selected_accounts', [])
    
    if not selected_accounts:
        await callback.answer("❌ Выберите хотя бы один аккаунт!", show_alert=True)
        return
        
    # Переходим к вводу контента
    await state.set_state(PostStates.waiting_for_auto_content)
    await callback.message.edit_text(
        "📝 Отправьте контент для автоматизированного поста\n"
        "Это может быть текст, фото, видео или файл"
    )

@dp.callback_query(lambda c: c.data.startswith('edit_auto_content_'))
async def edit_auto_content(callback: types.CallbackQuery, state: FSMContext):
    """Редактирование контента автоматизированного поста"""
    try:
        # Очищаем предыдущее состояние
        await state.clear()
        
        # Получаем ID поста
        post_id = int(callback.data.split('_')[3])
        post = await Database.get_automated_post_by_id(post_id)
        
        if not post:
            logger.error(f"Пост с ID {post_id} не найден")
            await callback.answer("❌ Пост не найден", show_alert=True)
            return
            
        # Сохраняем только ID поста для редактирования
        await state.update_data(edit_post_id=post_id)
        
        # Показываем текущий контент и запрашиваем новый
        current_content = post['message'].get('text', '') or post['message'].get('caption', '')
        await state.set_state(PostStates.waiting_for_auto_content)
        
        # Создаем клавиатуру с кнопкой отмены
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data=f"auto_post_menu_{post_id}"
                    )
                ]
            ]
        )
        
        await callback.message.edit_text(
            f"📝 Текущий контент поста:\n\n"
            f"{current_content}\n\n"
            f"Отправьте новый контент для поста или нажмите отмена",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Ошибка при редактировании контента: {str(e)}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)
        await state.clear()

@dp.message(PostStates.waiting_for_auto_content)
async def process_auto_content(message: types.Message, state: FSMContext):
    """Обработка контента для автоматизированного поста"""
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        if not data:
            logger.error("Данные состояния не найдены")
            await message.answer("❌ Ошибка: данные не найдены")
            await state.clear()
            return
            
        edit_post_id = data.get('edit_post_id')
        
        # Формируем данные сообщения
        message_data = {
            "text": message.text,
            "caption": message.caption,
            "message_id": message.message_id,
            "user_id": message.from_user.id
        }
        
        if message.photo:
            message_data["photo"] = message.photo[-1].file_id
        elif message.video:
            message_data["video"] = message.video.file_id
        elif message.document:
            message_data["document"] = {
                "file_id": message.document.file_id,
                "file_name": message.document.file_name
            }
        
        if edit_post_id:
            # Если это редактирование существующего поста
            try:
                success = await Database.update_automated_post(edit_post_id, message_data=message_data)
                if success:
                    logger.info(f"Контент поста {edit_post_id} успешно обновлен")
                    await message.answer("✅ Контент поста успешно обновлен!")
                    # Возвращаемся к меню поста
                    await message.answer(
                        "🔄 Возвращаемся к настройкам поста...",
                        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                            [types.InlineKeyboardButton(
                                text="📝 Вернуться к настройкам поста",
                                callback_data=f"auto_post_menu_{edit_post_id}"
                            )]
                        ])
                    )
                else:
                    logger.error(f"Ошибка при обновлении контента поста {edit_post_id}")
                    await message.answer("❌ Ошибка при обновлении контента")
            except Exception as e:
                logger.error(f"Ошибка при сохранении контента: {str(e)}")
                await message.answer("❌ Ошибка при сохранении контента")
        else:
            # Если это создание нового поста
            await state.update_data(message_data=message_data)
            await state.set_state(PostStates.waiting_for_auto_times_count)
            await message.answer(
                "🔄 Укажите, сколько раз в день нужно отправлять этот пост\n"
                "Введите число от 1 до 24"
            )
            return
            
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при обработке контента: {str(e)}")
        await message.answer("❌ Произошла ошибка при обработке контента")
        await state.clear()

@dp.message(PostStates.waiting_for_auto_times_count)
async def process_auto_times_count(message: types.Message, state: FSMContext):
    """Обработка количества повторений для автоматизированного поста"""
    try:
        times_count = int(message.text)
        if not 1 <= times_count <= 24:
            await message.answer(
                "❌ Пожалуйста, введите корректное число от 1 до 24"
            )
            return
            
        data = await state.get_data()
        message_data = data.get('message_data')
        
        if not message_data:
            logger.error("Данные сообщения не найдены")
            await message.answer("❌ Ошибка: данные не найдены")
            await state.clear()
            return
            
        await state.update_data(times_count=times_count, times=[], current_time_index=0)
        
        # Переходим к вводу первого времени
        await state.set_state(PostStates.waiting_for_auto_time)
        await message.answer(
            "🕒 Укажите время для первой отправки (в формате ЧЧ:ММ)\n"
            "Например: 14:30"
        )
        
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите корректное число от 1 до 24"
        )

@dp.message(PostStates.waiting_for_auto_time)
async def process_auto_time(message: types.Message, state: FSMContext):
    """Обработка времени отправки для автоматизированного поста"""
    time_str = message.text.strip()
    
    # Проверяем формат времени
    if not re.match(r'^([01]?[0-9]|2[0-3]):([0-5][0-9])$', time_str):
        await message.answer(
            "❌ Пожалуйста, введите корректное время в формате ЧЧ:ММ\n"
            "Например: 14:30"
        )
        return
        
    data = await state.get_data()
    times = data.get('times', [])
    times_count = data.get('times_count', 1)
    current_time_index = data.get('current_time_index', 0)
    edit_post_id = data.get('edit_post_id')
    
    if time_str in times:
        await message.answer("❌ Это время уже добавлено в расписание")
        return
        
    times.append(time_str)
    current_time_index += 1
    await state.update_data(times=times, current_time_index=current_time_index)
    
    if current_time_index < times_count:
        # Запрашиваем следующее время
        await message.answer(
            f"🕒 Укажите время для {current_time_index + 1}-й отправки (в формате ЧЧ:ММ)\n"
            f"Например: 14:30\n\n"
            f"Добавлено {current_time_index} из {times_count}"
        )
        return
    
    # Сортируем времена перед сохранением
    times.sort()
    
    if edit_post_id:
        # Обновляем существующий пост
        await Database.update_automated_post(edit_post_id, times=times)
        await message.answer(
            "✅ Расписание поста успешно обновлено!\n"
            f"Времена отправки: {', '.join(times)}"
        )
        
        # Возвращаемся к меню поста
        await message.answer(
            "🔄 Возвращаемся к настройкам поста...",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(
                    text="📝 Вернуться к настройкам поста",
                    callback_data=f"auto_post_menu_{edit_post_id}"
                )]
            ])
        )
        await state.clear()
    else:
        # Создаем новый пост
        message_data = data.get('message_data')
        groups = data.get('selected_groups', [])
        accounts = data.get('selected_accounts', [])
        
        post_id = await Database.add_automated_post(
            message_data=message_data,
            groups=groups,
            accounts=accounts,
            times=times
        )
        
        await message.answer(
            "✅ Автоматизированный пост успешно создан!\n"
            f"ID поста: {post_id}\n\n"
            f"Времена отправки: {', '.join(times)}"
        )
        await state.clear()

async def check_automated_posts():
    """Проверка и отправка автоматизированных постов"""
    while True:
        try:
            # Получаем все активные автоматизированные посты
            posts = await Database.get_automated_posts()
            active_posts = [p for p in posts if p['status'] == 'active']
            
            if not active_posts:
                await asyncio.sleep(60)  # Если нет активных постов, проверяем раз в минуту
                continue
                
            current_time = datetime.now().strftime("%H:%M")
            
            for post in active_posts:
                if current_time in post['times']:
                    logger.info(f"Отправка автоматизированного поста #{post['id']}")
                    
                    # Создаем пул для отправки
                    posting_pool = PostingPool(MAX_THREADS)
                    
                    # Получаем аккаунты
                    accounts = []
                    for account_id in post['accounts']:
                        account = await Database.get_account_by_id(account_id)
                        if account and account['status'] == 'active':
                            accounts.append(account)
                    
                    if not accounts:
                        logger.error(f"Нет доступных аккаунтов для поста #{post['id']}")
                        continue
                    
                    # Получаем группы
                    groups = []
                    for group_id in post['groups']:
                        group = await Database.get_group_by_id(str(group_id))
                        if group:
                            groups.append(group)
                    
                    if not groups:
                        logger.error(f"Нет доступных групп для поста #{post['id']}")
                        continue
                    
                    # Распределяем группы между аккаунтами
                    groups_per_account = len(groups) // len(accounts)
                    if groups_per_account == 0:
                        groups_per_account = 1
                    
                    current_account_index = 0
                    current_group_index = 0
                    success_count = 0
                    error_count = 0
                    
                    while current_group_index < len(groups):
                        account = accounts[current_account_index]
                        
                        # Создаем клиент для текущего аккаунта
                        client = await session_manager.get_client(account['session_file'])
                        posting_manager = PostingManager(client, Database, bot)
                        
                        # Отправляем посты в группы через текущий аккаунт
                        for _ in range(groups_per_account):
                            if current_group_index >= len(groups):
                                break
                                
                            group = groups[current_group_index]
                            task = await posting_pool.add_posting_task(
                                posting_manager=posting_manager,
                                group_id=group['group_id'],
                                message_data=post['message']
                            )
                            
                            if task:
                                try:
                                    success, message = await task
                                    if success:
                                        success_count += 1
                                        logger.info(f"✅ Успешно отправлено в группу {group['title']} через аккаунт {account['phone']}")
                                    else:
                                        error_count += 1
                                        logger.error(f"❌ Ошибка при отправке в группу {group['title']}: {message}")
                                except Exception as e:
                                    error_count += 1
                                    logger.error(f"❌ Ошибка при отправке в группу {group['title']}: {str(e)}")
                            
                            current_group_index += 1
                        
                        current_account_index = (current_account_index + 1) % len(accounts)
                    
                    # Ждем завершения всех отправок
                    await posting_pool.wait_all()
                    
                    # Отправляем уведомление пользователю только если были успешные отправки
                    if success_count > 0:
                        try:
                            user_id = post['message'].get('user_id')
                            if user_id:
                                # Формируем список групп, в которые был отправлен пост
                                groups_text = "\n".join([f"• {g['title']}" for g in groups])
                                
                                await bot.send_message(
                                    user_id,
                                    f"✅ Автоматизированный пост #{post['id']} успешно отправлен!\n\n"
                                    f"📊 Статистика:\n"
                                    f"✅ Успешно: {success_count}\n"
                                    f"❌ Ошибок: {error_count}\n\n"
                                    f"📢 Группы:\n{groups_text}\n\n"
                                    f"⏰ Время отправки: {current_time}"
                                )
                        except Exception as e:
                            logger.error(f"Ошибка при отправке уведомления пользователю: {str(e)}")
                    
                    logger.info(f"Автоматизированный пост #{post['id']} отправлен")
            
            # Проверяем каждую минуту
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.exception(f"Ошибка при проверке автоматизированных постов: {str(e)}")
            await asyncio.sleep(60)

@dp.message(lambda m: m.text == "⚙️ Настройка автопостов")
async def automated_posts_settings(message: types.Message):
    """Настройки автоматизированных постов"""
    # Получаем все автоматизированные посты
    posts = await Database.get_automated_posts()
    
    if not posts:
        await message.answer(
            "📝 У вас нет автоматизированных постов.\n"
            "Создайте новый пост в разделе '🤖 Автоматизация постов'"
        )
        return
        
    # Создаем клавиатуру со списком постов
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=f"Пост #{post['id']} ({len(post['times'])} раз в день)",
                    callback_data=f"auto_post_menu_{post['id']}"
                )
            ] for post in posts
        ]
    )
    
    await message.answer(
        "📋 Список автоматизированных постов\n"
        "Выберите пост для управления:",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data.startswith('auto_post_menu_'))
async def auto_post_menu(callback: types.CallbackQuery):
    """Меню управления автоматизированным постом"""
    post_id = int(callback.data.split('_')[3])
    post = await Database.get_automated_post_by_id(post_id)
    
    if not post:
        await callback.answer("❌ Пост не найден", show_alert=True)
        return
        
    # Получаем информацию о группах и аккаунтах
    groups = await Database.get_active_groups()
    accounts = await Database.get_active_accounts()
    
    group_names = [
        group['title'] for group in groups 
        if group['id'] in post['groups']
    ]
    account_phones = [
        f"+{account['phone']}" for account in accounts 
        if account['id'] in post['accounts']
    ]
    
    # Создаем клавиатуру
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📝 Изменить контент",
                    callback_data=f"edit_auto_content_{post_id}"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="👥 Изменить группы",
                    callback_data=f"edit_auto_groups_{post_id}"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="👤 Изменить аккаунты",
                    callback_data=f"edit_auto_accounts_{post_id}"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🕒 Изменить расписание",
                    callback_data=f"edit_auto_schedule_{post_id}"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="⏸ Приостановить" if post['status'] == 'active' else "▶️ Возобновить",
                    callback_data=f"toggle_auto_post_{post_id}"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="❌ Удалить пост",
                    callback_data=f"delete_auto_post_{post_id}"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="◀️ Назад к списку",
                    callback_data="auto_posts_list"
                )
            ]
        ]
    )
    
    # Формируем текст сообщения
    message_text = (
        f"📝 Автоматизированный пост #{post_id}\n\n"
        f"📢 Группы ({len(group_names)}):\n"
        f"{chr(10).join('- ' + name for name in group_names)}\n\n"
        f"👤 Аккаунты ({len(account_phones)}):\n"
        f"{chr(10).join('- ' + phone for phone in account_phones)}\n\n"
        f"🕒 Времена отправки ({len(post['times'])}):\n"
        f"{chr(10).join('- ' + time for time in sorted(post['times']))}\n\n"
        f"📊 Статус: {'✅ Активен' if post['status'] == 'active' else '⏸ Приостановлен'}"
    )
    
    await callback.message.edit_text(
        message_text,
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data.startswith('toggle_auto_post_'))
async def toggle_auto_post(callback: types.CallbackQuery):
    """Приостановка/возобновление автоматизированного поста"""
    post_id = int(callback.data.split('_')[3])
    post = await Database.get_automated_post_by_id(post_id)
    
    if not post:
        await callback.answer("❌ Пост не найден", show_alert=True)
        return
        
    new_status = 'paused' if post['status'] == 'active' else 'active'
    await Database.update_automated_post(post_id, status=new_status)
    
    action = "приостановлен" if new_status == 'paused' else "возобновлен"
    await callback.answer(f"✅ Пост успешно {action}", show_alert=True)
    
    # Обновляем меню поста
    await auto_post_menu(callback)

@dp.callback_query(lambda c: c.data.startswith('delete_auto_post_'))
async def delete_auto_post(callback: types.CallbackQuery):
    """Удаление автоматизированного поста"""
    post_id = int(callback.data.split('_')[3])
    post = await Database.get_automated_post_by_id(post_id)
    
    if not post:
        await callback.answer("❌ Пост не найден", show_alert=True)
        return
        
    # Создаем клавиатуру для подтверждения
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✅ Да, удалить",
                    callback_data=f"confirm_delete_auto_{post_id}"
                ),
                types.InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"auto_post_menu_{post_id}"
                )
            ]
        ]
    )
    
    await callback.message.edit_text(
        f"⚠️ Вы действительно хотите удалить автоматизированный пост #{post_id}?",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data.startswith('confirm_delete_auto_'))
async def confirm_delete_auto_post(callback: types.CallbackQuery):
    """Подтверждение удаления автоматизированного поста"""
    post_id = int(callback.data.split('_')[3])
    
    await Database.delete_automated_post(post_id)
    await callback.answer("✅ Пост успешно удален", show_alert=True)
    
    # Возвращаемся к списку постов
    await automated_posts_settings(callback.message)

@dp.callback_query(lambda c: c.data == "auto_posts_list")
async def back_to_auto_posts_list(callback: types.CallbackQuery):
    """Возврат к списку автоматизированных постов"""
    await automated_posts_settings(callback.message)

@dp.callback_query(PostStates.waiting_for_auto_groups, lambda c: c.data.startswith('select_group_'))
async def select_auto_group(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора группы для автоматизированного поста"""
    group_id = int(callback.data.split('_')[2])
    
    # Получаем текущие выбранные группы
    data = await state.get_data()
    selected_groups = data.get('selected_groups', [])
    
    # Добавляем или удаляем группу из списка
    if group_id in selected_groups:
        selected_groups.remove(group_id)
    else:
        selected_groups.append(group_id)
    
    # Сохраняем обновленный список
    await state.update_data(selected_groups=selected_groups)
    
    # Обновляем клавиатуру
    groups = await Database.get_active_groups()
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=f"{'✅' if group['id'] in selected_groups else '⭕️'} {group['title']}",
                    callback_data=f"select_group_{group['id']}"
                )
            ] for group in groups
        ] + [
            [
                types.InlineKeyboardButton(
                    text="✅ Подтвердить выбор",
                    callback_data="confirm_auto_groups"
                )
            ]
        ]
    )
    
    # Обновляем сообщение
    await callback.message.edit_text(
        f"Выберите группы для автопостинга\n"
        f"Выбрано: {len(selected_groups)}",
        reply_markup=keyboard
    )

@dp.callback_query(PostStates.waiting_for_auto_groups, lambda c: c.data == "confirm_auto_groups")
async def confirm_auto_groups(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение выбора групп для автоматизированного поста"""
    data = await state.get_data()
    selected_groups = data.get('selected_groups', [])
    
    if not selected_groups:
        await callback.answer("❌ Выберите хотя бы одну группу!", show_alert=True)
        return
    
    # Переходим к выбору аккаунтов
    await state.set_state(PostStates.waiting_for_auto_accounts)
    
    # Получаем список активных аккаунтов
    accounts = await Database.get_active_accounts()
    if not accounts:
        await callback.message.edit_text(
            "❌ У вас нет активных аккаунтов.\n"
            "Сначала добавьте хотя бы один аккаунт!"
        )
        await state.clear()
        return
    
    # Создаем клавиатуру с аккаунтами
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=f"⭕️ {account['phone']}",
                    callback_data=f"select_account_{account['id']}"
                )
            ] for account in accounts
        ] + [
            [
                types.InlineKeyboardButton(
                    text="✅ Подтвердить выбор",
                    callback_data="confirm_auto_accounts"
                )
            ]
        ]
    )
    
    await callback.message.edit_text(
        "Выберите аккаунты для отправки:\n"
        "Нажмите на аккаунт, чтобы выбрать его.",
        reply_markup=keyboard
    )

@dp.callback_query(PostStates.waiting_for_auto_accounts, lambda c: c.data.startswith('select_account_'))
async def select_auto_account(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора аккаунта для автоматизированного поста"""
    account_id = int(callback.data.split('_')[2])
    data = await state.get_data()
    selected_accounts = data.get('selected_accounts', [])
    
    if account_id in selected_accounts:
        selected_accounts.remove(account_id)
    else:
        selected_accounts.append(account_id)
        
    await state.update_data(selected_accounts=selected_accounts)
    
    # Обновляем клавиатуру
    accounts = await Database.get_active_accounts()
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=f"{'✅' if account['id'] in selected_accounts else '⭕️'} {account['phone']}",
                    callback_data=f"select_account_{account['id']}"
                )
            ] for account in accounts
        ] + [
            [
                types.InlineKeyboardButton(
                    text="✅ Подтвердить выбор",
                    callback_data="confirm_auto_accounts"
                )
            ]
        ]
    )
    
    await callback.message.edit_text(
        f"Выберите аккаунты для автопостинга\n"
        f"Выбрано: {len(selected_accounts)}",
        reply_markup=keyboard
    )

@dp.callback_query(PostStates.waiting_for_auto_accounts, lambda c: c.data == "confirm_auto_accounts")
async def confirm_auto_accounts(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение выбора аккаунтов для автоматизированного поста"""
    data = await state.get_data()
    selected_accounts = data.get('selected_accounts', [])
    
    if not selected_accounts:
        await callback.answer("❌ Выберите хотя бы один аккаунт!", show_alert=True)
        return
        
    # Переходим к вводу контента
    await state.set_state(PostStates.waiting_for_auto_content)
    await callback.message.edit_text(
        "📝 Отправьте контент для автоматизированного поста\n"
        "Это может быть текст, фото, видео или файл"
    )

@dp.callback_query(lambda c: c.data.startswith('edit_auto_groups_'))
async def edit_auto_groups(callback: types.CallbackQuery, state: FSMContext):
    """Редактирование групп автоматизированного поста"""
    try:
        # Очищаем предыдущее состояние
        await state.clear()
        
        # Получаем ID поста
        post_id = int(callback.data.split('_')[3])
        post = await Database.get_automated_post_by_id(post_id)
        
        if not post:
            logger.error(f"Пост с ID {post_id} не найден")
            await callback.answer("❌ Пост не найден", show_alert=True)
            return
            
        # Сохраняем ID поста и текущие группы
        await state.update_data(
            edit_post_id=post_id,
            selected_groups=post.get('groups', []).copy()
        )
        
        logger.info(f"Начато редактирование групп для поста {post_id}")
        
        # Получаем список групп и создаем клавиатуру
        groups = await Database.get_active_groups()
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=f"{'✅' if group['id'] in post.get('groups', []) else '⭕️'} {group['title']}",
                        callback_data=f"select_edit_group_{group['id']}"
                    )
                ] for group in groups
            ] + [
                [
                    types.InlineKeyboardButton(
                        text="✅ Подтвердить выбор",
                        callback_data="confirm_edit_groups"
                    ),
                    types.InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data=f"auto_post_menu_{post_id}"
                    )
                ]
            ]
        )
        
        await callback.message.edit_text(
            f"Выберите группы для поста\n"
            f"Выбрано: {len(post.get('groups', []))}",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Ошибка при редактировании групп: {str(e)}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)
        await state.clear()

@dp.callback_query(lambda c: c.data.startswith('edit_auto_accounts_'))
async def edit_auto_accounts(callback: types.CallbackQuery, state: FSMContext):
    """Редактирование аккаунтов автоматизированного поста"""
    try:
        # Очищаем предыдущее состояние
        await state.clear()
        
        # Получаем ID поста
        post_id = int(callback.data.split('_')[3])
        post = await Database.get_automated_post_by_id(post_id)
        
        if not post:
            logger.error(f"Пост с ID {post_id} не найден")
            await callback.answer("❌ Пост не найден", show_alert=True)
            return
            
        # Сохраняем ID поста и текущие аккаунты
        await state.update_data(
            edit_post_id=post_id,
            selected_accounts=post.get('accounts', []).copy()
        )
        
        logger.info(f"Начато редактирование аккаунтов для поста {post_id}")
        
        # Получаем список аккаунтов и создаем клавиатуру
        accounts = await Database.get_active_accounts()
        if not accounts:
            await callback.answer("❌ Нет доступных аккаунтов", show_alert=True)
            return
            
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=f"{'✅' if account['id'] in post.get('accounts', []) else '⭕️'} {account['phone']}",
                        callback_data=f"select_edit_account_{account['id']}"
                    )
                ] for account in accounts
            ] + [
                [
                    types.InlineKeyboardButton(
                        text="✅ Подтвердить выбор",
                        callback_data="confirm_edit_accounts"
                    ),
                    types.InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data=f"auto_post_menu_{post_id}"
                    )
                ]
            ]
        )
        
        await callback.message.edit_text(
            f"Выберите аккаунты для поста\n"
            f"Выбрано: {len(post.get('accounts', []))}",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Ошибка при редактировании аккаунтов: {str(e)}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)
        await state.clear()

@dp.callback_query(lambda c: c.data.startswith('edit_auto_schedule_'))
async def edit_auto_schedule(callback: types.CallbackQuery, state: FSMContext):
    """Редактирование расписания автоматизированного поста"""
    post_id = int(callback.data.split('_')[3])
    post = await Database.get_automated_post_by_id(post_id)
    
    if not post:
        await callback.answer("❌ Пост не найден", show_alert=True)
        return
        
    # Сохраняем ID поста и текущие данные
    await state.update_data(
        edit_post_id=post_id,
        message_data=post['message'],
        selected_groups=post['groups'],
        selected_accounts=post['accounts']
    )
    
    # Переходим к вводу количества отправок
    await state.set_state(PostStates.waiting_for_auto_times_count)
    await callback.message.edit_text(
        "🔄 Укажите, сколько раз в день нужно отправлять этот пост\n"
        "Введите число от 1 до 24"
    )

@dp.callback_query(lambda c: c.data == "confirm_edit_groups")
async def confirm_edit_groups(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение изменения групп"""
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        if not data:
            await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
            await state.clear()
            return

        post_id = data.get('edit_post_id')
        bulk_group_id = data.get('edit_bulk_group_id')
        selected_groups = data.get('selected_groups', [])

        # Проверяем, что мы редактируем либо пост, либо оптомгруппу
        if post_id:
            # Логика для редактирования групп поста
            if not selected_groups:
                await callback.answer("❌ Выберите хотя бы одну группу!", show_alert=True)
                return

            success = await Database.update_automated_post(post_id, groups=selected_groups)
            if success:
                await callback.answer("✅ Группы успешно обновлены", show_alert=True)
                await state.clear()
                await auto_post_menu(callback)
            else:
                await callback.answer("❌ Ошибка при обновлении групп", show_alert=True)
                await state.clear()

        elif bulk_group_id:
            # Логика для редактирования оптомгруппы
            if not selected_groups:
                await callback.answer("❌ Выберите хотя бы одну группу!", show_alert=True)
                return

            success = await Database.update_bulk_group(bulk_group_id, group_ids=selected_groups)
            if success:
                # Получаем названия выбранных групп
                groups = await Database.get_active_groups()
                selected_titles = [
                    group['title'] for group in groups 
                    if group['id'] in selected_groups
                ]
                
                success_message = (
                    f"✅ Оптомгруппа обновлена!\n\n"
                    f"📋 Группы ({len(selected_groups)}):\n"
                    f"{chr(10).join('• ' + title for title in selected_titles)}"
                )
                
                await callback.message.edit_text(success_message)
                await list_bulk_groups(callback.message)
                await state.clear()
            else:
                await callback.answer("❌ Ошибка при обновлении групп", show_alert=True)
                await state.clear()
        else:
            await callback.answer("❌ Ошибка: не найден ID для обновления", show_alert=True)
            await state.clear()
            
    except Exception as e:
        logger.error(f"Ошибка при подтверждении изменений: {str(e)}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)
        await state.clear()

@dp.callback_query(lambda c: c.data == "confirm_edit_accounts")
async def confirm_edit_accounts(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение изменения аккаунтов"""
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        if not data:
            logger.error("Данные состояния не найдены")
            await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
            await state.clear()
            return

        post_id = data.get('edit_post_id')
        selected_accounts = data.get('selected_accounts', [])

        # Проверяем наличие post_id
        if not post_id:
            logger.error("post_id не найден в состоянии")
            await callback.answer("❌ Ошибка: пост не найден", show_alert=True)
            await state.clear()
            return

        # Проверяем наличие выбранных аккаунтов
        if not selected_accounts:
            await callback.answer("❌ Выберите хотя бы один аккаунт!", show_alert=True)
            return

        # Получаем пост для проверки
        post = await Database.get_automated_post_by_id(post_id)
        if not post:
            logger.error(f"Пост с ID {post_id} не найден в базе данных")
            await callback.answer("❌ Ошибка: пост не найден в базе данных", show_alert=True)
            await state.clear()
            return

        # Обновляем аккаунты в базе данных
        try:
            success = await Database.update_automated_post(post_id, accounts=selected_accounts)
            
            if success:
                logger.info(f"Аккаунты успешно обновлены для поста {post_id}. Новые аккаунты: {selected_accounts}")
                # Очищаем состояние
                await state.clear()
                # Возвращаемся к меню поста с обновленными данными
                await callback.answer("✅ Аккаунты успешно обновлены", show_alert=True)
                await auto_post_menu(callback)
            else:
                logger.error(f"Ошибка при обновлении аккаунтов для поста {post_id}")
                await callback.answer("❌ Ошибка при обновлении аккаунтов", show_alert=True)
                await state.clear()
        except Exception as db_error:
            logger.error(f"Ошибка базы данных при обновлении аккаунтов: {str(db_error)}")
            await callback.answer("❌ Ошибка при сохранении изменений", show_alert=True)
            await state.clear()
            
    except Exception as e:
        logger.error(f"Ошибка при подтверждении аккаунтов: {str(e)}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)
        await state.clear()

@dp.callback_query(lambda c: c.data.startswith('select_edit_group_'))
async def select_edit_group(callback: types.CallbackQuery, state: FSMContext):
    """Выбор группы при редактировании"""
    try:
        # Получаем ID группы из callback data
        group_id = int(callback.data.split('_')[3])
        
        # Получаем данные из состояния
        data = await state.get_data()
        if not data:
            logger.error("Данные состояния не найдены")
            await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
            await state.clear()
            return
            
        post_id = data.get('edit_post_id')
        if not post_id:
            logger.error("post_id не найден в состоянии")
            await callback.answer("❌ Ошибка: пост не найден", show_alert=True)
            await state.clear()
            return
            
        selected_groups = data.get('selected_groups', []).copy()
        
        # Добавляем или удаляем группу из списка
        if group_id in selected_groups:
            selected_groups.remove(group_id)
        else:
            selected_groups.append(group_id)
            
        # Сохраняем обновленный список
        await state.update_data(selected_groups=selected_groups)
        
        # Получаем список всех групп
        groups = await Database.get_active_groups()
        if not groups:
            logger.error("Нет доступных групп")
            await callback.answer("❌ Ошибка: нет доступных групп", show_alert=True)
            await state.clear()
            return
            
        # Создаем клавиатуру
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=f"{'✅' if group['id'] in selected_groups else '⭕️'} {group['title']}",
                        callback_data=f"select_edit_group_{group['id']}"
                    )
                ] for group in groups
            ] + [
                [
                    types.InlineKeyboardButton(
                        text="✅ Подтвердить выбор",
                        callback_data="confirm_edit_groups"
                    ),
                    types.InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data=f"auto_post_menu_{post_id}"
                    )
                ]
            ]
        )
        
        # Обновляем сообщение
        await callback.message.edit_text(
            f"Выберите группы для поста\n"
            f"Выбрано: {len(selected_groups)}",
            reply_markup=keyboard
        )
        await callback.answer()
        
    except ValueError as ve:
        logger.error(f"Ошибка при парсинге ID группы: {str(ve)}")
        await callback.answer("❌ Некорректный ID группы", show_alert=True)
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка при выборе группы: {str(e)}")
        await callback.answer("❌ Ошибка при выборе группы", show_alert=True)
        await state.clear()

@dp.callback_query(lambda c: c.data.startswith('select_edit_account_'))
async def select_edit_account(callback: types.CallbackQuery, state: FSMContext):
    """Выбор аккаунта при редактировании"""
    try:
        # Получаем ID аккаунта из callback data
        account_id = int(callback.data.split('_')[3])
        
        # Получаем данные из состояния
        data = await state.get_data()
        if not data:
            logger.error("Данные состояния не найдены")
            await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
            await state.clear()
            return
            
        post_id = data.get('edit_post_id')
        if not post_id:
            logger.error("post_id не найден в состоянии")
            await callback.answer("❌ Ошибка: пост не найден", show_alert=True)
            await state.clear()
            return
            
        selected_accounts = data.get('selected_accounts', []).copy()
        
        # Добавляем или удаляем аккаунт из списка
        if account_id in selected_accounts:
            selected_accounts.remove(account_id)
        else:
            selected_accounts.append(account_id)
            
        # Сохраняем обновленный список
        await state.update_data(selected_accounts=selected_accounts)
        
        # Получаем список всех аккаунтов
        accounts = await Database.get_active_accounts()
        if not accounts:
            logger.error("Нет доступных аккаунтов")
            await callback.answer("❌ Ошибка: нет доступных аккаунтов", show_alert=True)
            await state.clear()
            return
            
        # Создаем клавиатуру
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=f"{'✅' if account['id'] in selected_accounts else '⭕️'} {account['phone']}",
                        callback_data=f"select_edit_account_{account['id']}"
                    )
                ] for account in accounts
            ] + [
                [
                    types.InlineKeyboardButton(
                        text="✅ Подтвердить выбор",
                        callback_data="confirm_edit_accounts"
                    ),
                    types.InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data=f"auto_post_menu_{post_id}"
                    )
                ]
            ]
        )
        
        # Обновляем сообщение
        await callback.message.edit_text(
            f"Выберите аккаунты для поста\n"
            f"Выбрано: {len(selected_accounts)}",
            reply_markup=keyboard
        )
        await callback.answer()
        
    except ValueError as ve:
        logger.error(f"Ошибка при парсинге ID аккаунта: {str(ve)}")
        await callback.answer("❌ Некорректный ID аккаунта", show_alert=True)
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка при выборе аккаунта: {str(e)}")
        await callback.answer("❌ Ошибка при выборе аккаунта", show_alert=True)
        await state.clear()

@dp.message(lambda m: m.text not in [
    "➕ Добавить оптомгруппу",
    "📋 Список оптомгрупп",
    "✏️ Редактировать оптомгруппу",
    "❌ Удалить оптомгруппу",
    "◀️ Назад"
])
async def invalid_bulk_groups_input(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    
    # Если мы не в состоянии ожидания ввода для оптомгрупп, игнорируем
    if not current_state or not current_state.startswith('GroupStates:'):
        return
        
    # Если мы ожидаем ввод названия оптомгруппы
    if current_state == 'GroupStates:waiting_for_bulk_group_name':
        if len(message.text.strip()) < 3 or len(message.text.strip()) > 50:
            await message.answer(
                "❌ Ошибка: название должно быть от 3 до 50 символов\n"
                "Попробуйте еще раз или нажмите ◀️ Назад для отмены"
            )
            return
            
    # В остальных случаях возвращаем в меню оптомгрупп
    await bulk_groups_menu(message, state)

@dp.callback_query(GroupStates.waiting_for_bulk_group_selection, lambda c: c.data == "confirm_bulk_group_selection")
async def confirm_bulk_group_selection(callback: types.CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        selected_groups = data.get('selected_groups', [])
        name = data.get('bulk_group_name')
        
        logger.info(f"Подтверждение создания оптомгруппы '{name}' с группами: {selected_groups}")
        
        if not selected_groups:
            logger.warning("Попытка создания оптомгруппы без выбранных групп")
            await callback.answer("❌ Выберите хотя бы одну группу!", show_alert=True)
            return
            
        # Создаем новую оптомгруппу
        bulk_group_id = await Database.add_bulk_group(name, selected_groups)
        logger.info(f"Создана новая оптомгруппа с ID {bulk_group_id}")
        
        # Получаем названия выбранных групп
        groups = await Database.get_active_groups()
        selected_titles = [
            group['title'] for group in groups 
            if group['id'] in selected_groups
        ]
        
        success_message = (
            f"✅ Оптомгруппа '{name}' успешно создана!\n\n"
            f"📋 Группы ({len(selected_groups)}):\n"
            f"{chr(10).join('• ' + title for title in selected_titles)}"
        )
        
        await callback.message.edit_text(success_message)
        logger.info(f"Оптомгруппа '{name}' успешно создана с {len(selected_groups)} группами")
        
        # Показываем обновленный список оптомгрупп
        await list_bulk_groups(callback.message)
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при создании оптомгруппы: {str(e)}")
        await callback.answer("❌ Произошла ошибка при создании оптомгруппы", show_alert=True)
        await state.clear()

@dp.callback_query(GroupStates.waiting_for_bulk_group_selection, lambda c: c.data.startswith('select_bulk_group_'))
async def select_bulk_group_for_edit(callback: types.CallbackQuery, state: FSMContext):
    try:
        group_id = int(callback.data.split('_')[3])
        logger.info(f"Выбор группы {group_id} для редактирования оптомгруппы")
        
        # Получаем данные из состояния
        data = await state.get_data()
        selected_groups = data.get('selected_groups', [])
        bulk_group_name = data.get('bulk_group_name', '')
        edit_bulk_group_id = data.get('edit_bulk_group_id')
        
        if not edit_bulk_group_id:
            logger.error("ID редактируемой оптомгруппы не найден")
            await callback.answer("❌ Ошибка: группа не найдена", show_alert=True)
            await state.clear()
            return
        
        # Добавляем или удаляем группу из списка
        if group_id in selected_groups:
            selected_groups.remove(group_id)
            logger.info(f"Группа {group_id} удалена из выбранных")
        else:
            selected_groups.append(group_id)
            logger.info(f"Группа {group_id} добавлена к выбранным")
        
        # Сохраняем обновленный список
        await state.update_data(selected_groups=selected_groups)
        
        # Получаем список всех групп
        groups = await Database.get_active_groups()
        if not groups:
            logger.error("Нет доступных групп для выбора")
            await callback.answer("❌ Нет доступных групп", show_alert=True)
            return
        
        # Создаем клавиатуру
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=f"{'✅' if group['id'] in selected_groups else '⭕️'} {group['title']}",
                        callback_data=f"select_bulk_group_{group['id']}"
                    )
                ] for group in groups
            ] + [
                [
                    types.InlineKeyboardButton(
                        text="✅ Подтвердить изменения",
                        callback_data="confirm_bulk_group_edit"
                    )
                ]
            ]
        )
        
        # Обновляем сообщение
        await callback.message.edit_text(
            f"Редактирование оптомгруппы '{bulk_group_name}'\n"
            f"Выбрано: {len(selected_groups)} групп",
            reply_markup=keyboard
        )
        
        await callback.answer()
        
    except ValueError as e:
        logger.error(f"Ошибка при парсинге ID группы: {str(e)}")
        await callback.answer("❌ Некорректный формат ID группы", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при выборе группы: {str(e)}")
        await callback.answer("❌ Произошла ошибка при выборе группы", show_alert=True)

async def main():
    # Инициализация базы данных
    await init_db()
    
    # Запускаем проверку отложенных и автоматизированных постов
    asyncio.create_task(check_scheduled_posts())
    asyncio.create_task(check_automated_posts())
    
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(level=logging.INFO)
    logger.add("logs/bot.log", rotation="1 MB")
    
    # Запуск бота
    asyncio.run(main()) 