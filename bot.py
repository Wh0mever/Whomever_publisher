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
from telethon.errors import UserNotParticipantError
import time
from typing import Optional
import os
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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

class SettingsStates(StatesGroup):
    waiting_for_delay = State()
    waiting_for_threads = State()
    waiting_for_retries = State()

class GroupStates(StatesGroup):
    waiting_for_group = State()

# Инициализация менеджеров
session_manager = SessionManager()
posting_pool = PostingPool(max_threads=MAX_THREADS)

def get_main_keyboard() -> types.ReplyKeyboardMarkup:
    """Возвращает основную клавиатуру бота"""
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [
                types.KeyboardButton(text="📝 Создать пост"),
                types.KeyboardButton(text="⏰ Отложенный пост")
            ],
            [
                types.KeyboardButton(text="📋 Список постов"),
                types.KeyboardButton(text="🔍 Проверка групп")
            ],
            [
                types.KeyboardButton(text="👥 Управление группами"),
                types.KeyboardButton(text="👤 Управление аккаунтами")
            ],
            [
                types.KeyboardButton(text="⚙️ Настройки")
            ]
        ],
        resize_keyboard=True
    )

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
            'user_id': message.from_user.id  # Добавляем ID пользователя
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
        
        # Переходим к выбору групп
        groups = await Database.get_groups()
        if not groups:
            await message.answer("❌ Нет доступных групп для отправки")
            await state.clear()
            return
            
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=group['title'],
                        callback_data=f"select_group_{group['id']}"
                    )
                ] for group in groups
            ] + [
                [
                    types.InlineKeyboardButton(
                        text="✅ Подтвердить выбор",
                        callback_data="confirm_groups"
                    )
                ]
            ]
        )
        
        await state.update_data(selected_groups=[])
        await state.set_state(PostStates.waiting_for_groups)
        await message.answer(
            "📢 Выберите группы для отправки поста\n"
            "Можно выбрать несколько групп",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.exception(f"Ошибка при обработке контента поста: {str(e)}")
        await message.answer("❌ Произошла ошибка при обработке поста")
        await state.clear()

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
        groups = await Database.get_groups()
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text=f"{'✅ ' if group['id'] in selected_groups else ''}{group['title']}",
                        callback_data=f"select_group_{group['id']}"
                    )
                ] for group in groups
            ] + [
                [
                    types.InlineKeyboardButton(
                        text="✅ Подтвердить выбор",
                        callback_data="confirm_groups"
                    )
                ]
            ]
        )
        
        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await callback.answer()
        
    except Exception as e:
        logger.exception(f"Ошибка при выборе группы: {str(e)}")
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
    else:
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

# Обработчик ввода группы
@dp.message(GroupStates.waiting_for_group)
async def process_group_input(message: types.Message, state: FSMContext):
    group_input = message.text.strip()
    
    # Проверяем формат ввода
    if not (group_input.startswith('@') or group_input.startswith('-100')):
        await message.answer(
            "❌ Неверный формат!\n"
            "Отправьте @username группы или её ID, начинающийся с -100"
        )
        return
    
    try:
        # Получаем активный аккаунт для проверки доступа к группе
        accounts = await Database.get_active_accounts()
        if not accounts:
            await message.answer("❌ Нет доступных аккаунтов для проверки группы")
            await state.clear()
            return
        
        # Используем первый активный аккаунт для проверки
        client = await session_manager.get_client(accounts[0]['session_file'])
        
        try:
            # Пробуем получить информацию о группе
            entity = await client.get_entity(group_input)
            
            if not hasattr(entity, 'title'):
                await message.answer("❌ Указанный идентификатор не является группой")
                return
            
            # Добавляем группу в базу
            group_id = str(entity.id)
            await Database.add_group(group_id, entity.title, entity.username or '')
            
            await message.answer(
                f"✅ Группа успешно добавлена!\n\n"
                f"Название: {entity.title}\n"
                f"ID: {group_id}"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при проверке группы {group_input}: {str(e)}")
            await message.answer(
                "❌ Не удалось получить доступ к группе.\n"
                "Убедитесь, что:\n"
                "1. Указан верный @username или ID\n"
                "2. Группа существует и доступна\n"
                "3. Аккаунт является участником группы"
            )
        finally:
            await client.disconnect()
            
    except Exception as e:
        logger.exception(f"Ошибка при добавлении группы: {str(e)}")
        await message.answer("❌ Произошла ошибка при добавлении группы")
    
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

async def main():
    # Инициализация базы данных
    await init_db()
    
    # Запускаем проверку отложенных постов
    asyncio.create_task(check_scheduled_posts())
    
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(level=logging.INFO)
    logger.add("logs/bot.log", rotation="1 MB")
    
    # Запуск бота
    asyncio.run(main()) 