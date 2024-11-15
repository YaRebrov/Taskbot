import telebot
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage
import re
import sqlite3
from datetime import datetime, timedelta  # Added timedelta for time calculations
import logging
from collections import defaultdict
import sys
import signal
import time
import threading
import pandas as pd  # Added for export functionality
import tempfile
import os

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='bot_log.log'
)
logger = logging.getLogger(__name__)

ADMIN_ID = 442780487  # Администратор
SENDER_ID = 1846983750  # Менеджер
PROCESSOR_ID = 6674781903  # Бухгалтер

state_storage = StateMemoryStorage()
bot = telebot.TeleBot("7329953385:AAETw5G3BruiV5nYmBUyHrMnyuw_HAi6b7k", state_storage=state_storage)


def send_timed_admin_message(message, seconds=5):
    try:
        sent_message = bot.send_message(ADMIN_ID, message)

        def update_timer():
            remaining_time = seconds - 1
            while remaining_time > 0:
                time.sleep(1)
                remaining_time -= 1
                try:
                    updated_message = message + f"\n\n⏱ Сообщение будет удалено через {remaining_time} секунд"
                    bot.edit_message_text(
                        updated_message,
                        ADMIN_ID,
                        sent_message.message_id
                    )
                except Exception as e:
                    logger.error(f"Error updating admin message timer: {str(e)}")
                    break

            try:
                bot.delete_message(ADMIN_ID, sent_message.message_id)
            except Exception as e:
                logger.error(f"Error deleting admin message: {str(e)}")

        timer_thread = threading.Thread(target=update_timer)
        timer_thread.start()

    except Exception as e:
        logger.error(f"Error sending timed admin message: {str(e)}")


def send_admin_log(message):
    try:
        if "Бот запущен" in message:  # Don't auto-delete the bot startup message
            bot.send_message(ADMIN_ID, message)
        else:
            send_timed_admin_message(message)
    except Exception as e:
        logger.error(f"Error sending admin log: {str(e)}")


def signal_handler(signum, frame):
    logger.info("Received signal to terminate. Stopping bot gracefully...")
    bot.stop_polling()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def initialize_db():
    conn = sqlite3.connect('documents.db')
    c = conn.cursor()

    # Create tasks table
    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  order_number TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at DATETIME NOT NULL,
                  processed_at DATETIME,
                  sender_id INTEGER NOT NULL,
                  processor_id INTEGER)''')

    # Create documents table to track individual files
    c.execute('''CREATE TABLE IF NOT EXISTS task_documents
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  task_id INTEGER,
                  document_name TEXT NOT NULL,
                  uploaded_by INTEGER NOT NULL,
                  uploaded_at DATETIME NOT NULL,
                  FOREIGN KEY (task_id) REFERENCES tasks(id))''')

    conn.commit()
    conn.close()


def create_temp_message_db():
    try:
        temp_dir = tempfile.gettempdir()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        db_path = os.path.join(temp_dir, f'temp_messages_{timestamp}.db')

        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # Simplified messages table
        c.execute('''CREATE TABLE IF NOT EXISTS messages
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      message_id INTEGER,
                      user_id INTEGER,
                      document_name TEXT,
                      timestamp DATETIME)''')

        conn.commit()
        conn.close()
        return db_path
    except Exception as e:
        logger.error(f"Error creating temp database: {str(e)}")
        raise


class AdminStates(StatesGroup):
    viewing_messages = State()
    selecting_order = State()


@bot.message_handler(commands=['start'])
def send_welcome(message):
    if message.from_user.id == ADMIN_ID:
        welcome_text = """
👋 Добро пожаловать, Администратор! 
🤖 Я бот для обработки документов.

Доступные команды:
/status - Проверить статус документов
/whoami - Узнать свой ID и роль
/clear_queue - Очистить очередь задач
/view_sender_messages - Показать последние 20 сообщений от отправителя
/add_task <номер> - Добавить задачу из списка сообщений
/check_group - Проверить ID текущей группы/чата
/check_connection - Проверить подключение к группе и последние сообщения
/view_logs - Просмотр последних записей лога бота
/export - Экспортировать базу данных в Excel
/check_groups - Показать список групп и каналов где есть бот
/help - Показать это сообщение снова

⏱ Сообщение будет удалено через 15 секунд
"""
    else:
        welcome_text = """
👋 Добро пожаловать! 
🤖 Я бот для обработки документов.

Доступные команды:
/status - Проверить статус документов
/whoami - Узнать свой ID и роль
/clear_queue - Очистить очередь задач
/check_group - Проверить ID текущей группы/чата
/check_connection - Проверить подключение к группе и последние сообщения
/check_groups - Показать список групп и каналов где есть бот

⏱ Сообщение будет удалено через 15 секунд
"""
    sent_message = bot.reply_to(message, welcome_text)

    def update_timer():
        remaining_time = 14
        while remaining_time > 0:
            time.sleep(1)
            remaining_time -= 1
            try:
                updated_text = welcome_text.replace(
                    "⏱ Сообщение будет удалено через 15 секунд",
                    f"⏱ Сообщение будет удалено через {remaining_time} секунд"
                )
                bot.edit_message_text(
                    updated_text,
                    message.chat.id,
                    sent_message.message_id
                )
            except Exception as e:
                logger.error(f"Error updating welcome message timer: {str(e)}")
                break

        try:
            bot.delete_message(message.chat.id, message.message_id)
            bot.delete_message(message.chat.id, sent_message.message_id)
        except Exception as e:
            logger.error(f"Error deleting welcome messages: {str(e)}")

    timer_thread = threading.Thread(target=update_timer)
    timer_thread.start()


@bot.message_handler(commands=['view_sender_messages'], func=lambda message: message.from_user.id == ADMIN_ID)
def view_sender_messages(message):
    try:
        chat_id = message.chat.id
        logger.info(f"Starting view_sender_messages. chat_id={chat_id}, SENDER_ID={SENDER_ID}")
        conn = sqlite3.connect('documents.db')
        c = conn.cursor()

        # First check if we have any messages at all
        c.execute('SELECT COUNT(*) FROM task_documents')
        total_count = c.fetchone()[0]
        logger.info(f"Total messages in database: {total_count}")

        # Log messages for this sender
        c.execute('SELECT COUNT(*) FROM task_documents WHERE uploaded_by = ?', (SENDER_ID,))
        sender_count = c.fetchone()[0]
        logger.info(f"Total messages from sender {SENDER_ID}: {sender_count}")

        # Modified query - remove chat_id filter to see all messages
        sender_messages = c.execute('''SELECT document_name, uploaded_at, uploaded_by 
                                     FROM task_documents 
                                     WHERE uploaded_by = ?
                                     ORDER BY uploaded_at DESC LIMIT 20''',
                                    (SENDER_ID,)).fetchall()

        logger.info(f"Found {len(sender_messages)} messages matching criteria")

        if not sender_messages:
            bot.send_message(ADMIN_ID, "📭 Сообщений от отправителя не найдено")
            return

        response = "📋 Последние 20 сообщений от отправителя:\n\n"
        valid_orders = []

        for idx, (doc_name, timestamp, msg_uploaded_by) in enumerate(sender_messages, 1):
            order_number = extract_order_number(doc_name)
            if order_number:
                dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S.%f')
                formatted_time = dt.strftime('%d.%m.%Y %H:%M')
                response += f"{idx}. 📄 {order_number}\n"
                response += f"   📎 Файл: {doc_name}\n"
                response += f"   🕒 {formatted_time}\n"
                response += f"   👥 Отправитель: {msg_uploaded_by}\n\n"
                valid_orders.append((idx, order_number))

        if valid_orders:
            response += "\n📝 Для добавления задачи используйте:\n"
            response += "/add_task <номер_строки>"
        else:
            response += "\n❌ Нет сообщений с номерами заказов"

        bot.send_message(ADMIN_ID, response)
        bot.set_state(message.from_user.id, AdminStates.viewing_messages)

        conn.close()
    except Exception as e:
        logger.error(f"Error viewing sender messages: {str(e)}")
        bot.send_message(ADMIN_ID, "❌ Произошла ошибка при получении списка сообщений")


@bot.message_handler(commands=['add_task'], func=lambda message: message.from_user.id == ADMIN_ID)
def add_task_command(message):
    try:
        args = message.text.split()
        if len(args) != 2:
            bot.send_message(ADMIN_ID, "❌ Используйте формат: /add_task <номер_строки>")
            return

        try:
            message_index = int(args[1]) - 1
        except ValueError:
            bot.send_message(ADMIN_ID, "❌ Номер строки должен быть числом")
            return

        conn = sqlite3.connect('documents.db')
        c = conn.cursor()

        # Fetch the last uploaded document
        sender_message = c.execute('''SELECT document_name 
                                    FROM task_documents 
                                    WHERE uploaded_by = ? 
                                    ORDER BY uploaded_at DESC LIMIT ?, 1''',
                                   (SENDER_ID, message_index)).fetchone()

        if not sender_message:
            bot.send_message(ADMIN_ID, "❌ Сообщение не найдено")
            return

        document_name = sender_message[0]
        order_number = extract_order_number(document_name)

        if not order_number:
            bot.send_message(ADMIN_ID, "❌ Не удалось извлечь номер заказа из названия документа")
            return

        c.execute('''INSERT INTO tasks 
                    (order_number, status, created_at, sender_id)
                    VALUES (?, ?, ?, ?)''',
                  (order_number, 'waiting', datetime.now(), SENDER_ID))

        conn.commit()
        conn.close()

        admin_message = f"✅ Задача добавлена вручную\n" \
                        f"Номер заказа: {order_number}\n" \
                        f"Документ: {document_name}"
        bot.send_message(ADMIN_ID, admin_message)

    except Exception as e:
        logger.error(f"Error adding task: {str(e)}")


def extract_order_number(filename):
    try:
        patterns = [
            r'DOR[\s-]*EX[\s-]*(\d+)[\s-]*(\d+)',
            r'DOR[\s-]*EX[\s-]*(\d+)[\s-]*(\d+)[kKкК]\d*',
            r'DOR[\s-]*EX[\s-]*(\d+)[\s-]*(\d+).*'
        ]

        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                return f"DOR-EX {match.group(1)}-{match.group(2)}"
        return None
    except Exception as e:
        logger.error(f"Error extracting order number: {str(e)}")
        return None


@bot.message_handler(content_types=['document'])
def handle_docs(message):
    try:
        document_name = message.document.file_name
        order_number = extract_order_number(document_name)
        user_id = message.from_user.id

        if not order_number:
            return

        conn = sqlite3.connect('documents.db')
        c = conn.cursor()

        if user_id == SENDER_ID:
            # Check if task already exists
            c.execute('SELECT id, status FROM tasks WHERE order_number = ? ORDER BY created_at DESC LIMIT 1',
                      (order_number,))
            existing_task = c.fetchone()

            if not existing_task or existing_task[1] == 'processed':
                # Create new task
                c.execute('''INSERT INTO tasks 
                            (order_number, status, created_at, sender_id)
                            VALUES (?, ?, ?, ?)''',
                          (order_number, 'waiting', datetime.now(), SENDER_ID))
                task_id = c.lastrowid

                # Add document record
                c.execute('''INSERT INTO task_documents 
                            (task_id, document_name, uploaded_by, uploaded_at)
                            VALUES (?, ?, ?, ?)''',
                          (task_id, document_name, SENDER_ID, datetime.now()))

                admin_message = f"📥 Новая задача добавлена\n" \
                                f"Номер заказа: {order_number}\n" \
                                f"Документ: {document_name}"
                send_timed_admin_message(admin_message)

            else:
                # Just add document to existing task
                c.execute('''INSERT INTO task_documents 
                            (task_id, document_name, uploaded_by, uploaded_at)
                            VALUES (?, ?, ?, ?)''',
                          (existing_task[0], document_name, SENDER_ID, datetime.now()))

        elif user_id == PROCESSOR_ID:
            # Find waiting task
            c.execute('''UPDATE tasks 
                        SET status = 'processed', 
                            processed_at = ?, 
                            processor_id = ?
                        WHERE order_number = ? 
                        AND status = 'waiting' ''',
                      (datetime.now(), PROCESSOR_ID, order_number))

            if c.rowcount > 0:
                # Add processor's document
                task_id = c.execute('SELECT id FROM tasks WHERE order_number = ? ORDER BY created_at DESC LIMIT 1',
                                    (order_number,)).fetchone()[0]

                c.execute('''INSERT INTO task_documents 
                            (task_id, document_name, uploaded_by, uploaded_at)
                            VALUES (?, ?, ?, ?)''',
                          (task_id, document_name, PROCESSOR_ID, datetime.now()))

                admin_message = f"✅ Задача выполнена\n" \
                                f"Номер заказа: {order_number}\n" \
                                f"Обработчик ID: {PROCESSOR_ID}"
                send_timed_admin_message(admin_message)

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Error handling document: {str(e)}")
        send_timed_admin_message(f"❌ Ошибка обработки документа: {str(e)}")


@bot.message_handler(commands=['clear_queue'])
def clear_queue(message):
    try:
        conn = sqlite3.connect('documents.db')
        c = conn.cursor()
        c.execute('''DELETE FROM tasks''')
        c.execute('''DELETE FROM task_documents''')
        conn.commit()
        conn.close()

        admin_message = f"🗑 Очередь задач очищена\n" \
                        f"Пользователь ID: {message.from_user.id}"
        send_timed_admin_message(admin_message)
        logger.info(f"Queue cleared by user {message.from_user.id}")

    except Exception as e:
        logger.error(f"Error clearing queue: {str(e)}")


@bot.message_handler(commands=['status'])
def get_status(message):
    try:
        conn = sqlite3.connect('documents.db')
        c = conn.cursor()

        # Get waiting tasks
        c.execute('''SELECT order_number, created_at FROM tasks 
                    WHERE status = 'waiting' 
                    ORDER BY created_at''')
        waiting_tasks = c.fetchall()

        # Get processed tasks
        c.execute('''SELECT order_number, processed_at FROM tasks 
                    WHERE status = 'processed' 
                    ORDER BY processed_at DESC''')
        processed_tasks = c.fetchall()

        response = "📋 Статус обработки документов:\n\n"

        response += "⏳ Ожидают обработки:\n"
        for task in waiting_tasks:
            created_at = datetime.strptime(task[1], '%Y-%m-%d %H:%M:%S.%f')
            response += f"• {task[0]} (от {created_at.strftime('%d.%m.%Y %H:%M')})\n"

        response += "\n✅ Обработано:\n"
        for task in processed_tasks:
            processed_at = datetime.strptime(task[1], '%Y-%m-%d %H:%M:%S.%f')
            response += f"• {task[0]} (в {processed_at.strftime('%d.%m.%Y %H:%M')})\n"

        response += f"\nСтатистика (ожидает/обработано): {len(waiting_tasks)}/{len(processed_tasks)}"

        sent_message = bot.reply_to(message, response)

        # Add deletion timer
        def delete_timer():
            time.sleep(15)
            try:
                bot.delete_message(message.chat.id, message.message_id)
                bot.delete_message(message.chat.id, sent_message.message_id)
            except Exception as e:
                logger.error(f"Error deleting status messages: {str(e)}")

        threading.Thread(target=delete_timer).start()

        conn.close()

    except Exception as e:
        logger.error(f"Error generating status: {str(e)}")


@bot.message_handler(commands=['whoami'])
def whoami(message):
    user_id = message.from_user.id
    user_type = "неизвестный пользователь"
    if user_id == SENDER_ID:
        user_type = "отправитель заданий"
    elif user_id == PROCESSOR_ID:
        user_type = "обработчик заданий"
    elif user_id == ADMIN_ID:
        user_type = "администратор"

    bot.reply_to(message, f"Ваш ID: {user_id}\nВаша роль: {user_type}")


@bot.message_handler(commands=['check_group'])
def check_group(message):
    try:
        chat_id = message.chat.id
        chat_type = message.chat.type
        response = f"ℹ️ Информация о чате:\nID: {chat_id}\nТип: {chat_type}"
        bot.reply_to(message, response)
    except Exception as e:
        logger.error(f"Error checking group ID: {str(e)}")
        bot.reply_to(message, "❌ Ошибка при получении информации о группе")


@bot.message_handler(commands=['help'], func=lambda message: message.from_user.id == ADMIN_ID)
def admin_help(message):
    help_text = """
👨‍💼 Команды администратора:

/view_sender_messages - Показать последние 20 сообщений от отправителя
/add_task <номер> - Добавить задачу из списка сообщений
/status - Проверить статус всех задач
/clear_queue - Очистить очередь задач
/clear_db - Очистить всю базу данных
/check_group - Проверить ID текущей группы/чата
/check_connection - Проверить подключение к группе и последние сообщения
/view_logs - Просмотр последних записей лога бота
/export - Экспортировать базу данных в Excel
/check_groups - Показать список групп и каналов где есть бот
/verify_tasks - Ручная проверка выполненных задач
/check_last_messages - Просмотреть последние сообщения в группе

⏱ Сообщение будет удалено через 15 секунд
"""
    # Send and start deletion timer
    sent_message = bot.send_message(ADMIN_ID, help_text)


@bot.message_handler(commands=['export'], func=lambda message: message.from_user.id == ADMIN_ID)
def export_database(message):
    try:
        conn = sqlite3.connect('documents.db')

        # Get tasks with their documents and calculate processing time
        tasks_df = pd.read_sql_query('''
            SELECT 
                t.id as "ID задачи",
                t.order_number as "Номер заказа",
                CASE 
                    WHEN t.status = 'waiting' THEN 'Ожидает обработки'
                    WHEN t.status = 'processed' THEN 'Обработано'
                    ELSE t.status 
                END as "Статус",
                t.created_at as "Дата создания",
                t.processed_at as "Дата обработки",
                CASE 
                    WHEN t.sender_id = 1846983750 THEN 'Менеджер'
                    ELSE t.sender_id 
                END as "Отправитель",
                CASE 
                    WHEN t.processor_id = 6674781903 THEN 'Бухгалтер'
                    ELSE t.processor_id 
                END as "Обработчик",
                GROUP_CONCAT(td.document_name, '; ') as "Документы"
            FROM tasks t
            LEFT JOIN task_documents td ON t.id = td.task_id
            GROUP BY t.id
        ''', conn)

        # Calculate processing time for completed tasks
        def calculate_processing_time(row):
            if pd.isna(row['Дата обработки']) or pd.isna(row['Дата создания']):
                return ''
            created = pd.to_datetime(row['Дата создания'])
            processed = pd.to_datetime(row['Дата обработки'])
            delta = processed - created
            hours = int(delta.total_seconds() // 3600)
            minutes = int((delta.total_seconds() % 3600) // 60)
            seconds = int(delta.total_seconds() % 60)
            return f'{hours:02d}:{minutes:02d}:{seconds:02d}'

        tasks_df['Время обработки'] = tasks_df.apply(calculate_processing_time, axis=1)

        # Format dates
        tasks_df['Дата создания'] = pd.to_datetime(tasks_df['Дата создания']).dt.strftime('%d.%m.%Y %H:%M:%S')
        tasks_df['Дата обработки'] = pd.to_datetime(tasks_df['Дата обработки']).fillna('').dt.strftime(
            '%d.%m.%Y %H:%M:%S')

        # Export to Excel with custom formatting
        export_path = 'tasks_export.xlsx'
        with pd.ExcelWriter(export_path, engine='xlsxwriter') as writer:
            tasks_df.to_excel(writer, index=False, sheet_name='Задачи')

            # Get workbook and worksheet
            workbook = writer.book
            worksheet = writer.sheets['Задачи']

            # Add formats
            header_format = workbook.add_format({
                'bold': True,
                'bg_color': '#D9EAD3',
                'border': 1
            })

            # Apply formats
            for col_num, value in enumerate(tasks_df.columns.values):
                worksheet.write(0, col_num, value, header_format)
                worksheet.set_column(col_num, col_num, 20)  # Set column width

        # Send file to admin
        with open(export_path, 'rb') as file:
            bot.send_document(ADMIN_ID, file, caption="📊 Экспорт базы данных")

        # Cleanup
        import os
        os.remove(export_path)

    except Exception as e:
        logger.error(f"Error exporting database: {str(e)}")
        bot.send_message(ADMIN_ID, "❌ Ошибка при экспорте базы данных")


@bot.message_handler(commands=['clear_db'], func=lambda message: message.from_user.id == ADMIN_ID)
def clear_database(message):
    try:
        # Ask for confirmation
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(
            telebot.types.InlineKeyboardButton("Да, очистить", callback_data="clear_db_confirm"),
            telebot.types.InlineKeyboardButton("Отмена", callback_data="clear_db_cancel")
        )
        bot.reply_to(message, "⚠️ Вы уверены, что хотите очистить всю базу данных?", reply_markup=markup)
    except Exception as e:
        logger.error(f"Error initiating database clear: {str(e)}")
        bot.reply_to(message, "❌ Ошибка при попытке очистки базы данных")


@bot.callback_query_handler(func=lambda call: call.data.startswith("clear_db_"))
def clear_db_callback(call):
    try:
        if call.data == "clear_db_confirm":
            conn = sqlite3.connect('documents.db')
            c = conn.cursor()
            c.execute('DELETE FROM tasks')
            c.execute('DELETE FROM task_documents')
            conn.commit()
            conn.close()

            bot.edit_message_text(
                "✅ База данных успешно очищена",
                call.message.chat.id,
                call.message.message_id
            )

            # Log the action
            admin_message = f"🗑 База данных очищена администратором\n" \
                            f"ID администратора: {call.from_user.id}"
            send_timed_admin_message(admin_message)
            logger.info(f"Database cleared by admin {call.from_user.id}")

        elif call.data == "clear_db_cancel":
            bot.edit_message_text(
                "❌ Очистка базы данных отменена",
                call.message.chat.id,
                call.message.message_id
            )

    except Exception as e:
        logger.error(f"Error clearing database: {str(e)}")
        bot.answer_callback_query(call.id, "❌ Ошибка при очистке базы данных")


@bot.message_handler(commands=['view_logs'], func=lambda message: message.from_user.id == ADMIN_ID)
def view_logs(message):
    try:
        with open('bot_log.log', 'r') as log_file:
            # Get last 20 lines of logs
            logs = log_file.readlines()[-20:]

        response = "📋 Последние 20 записей лога:\n\n"
        for log in logs:
            response += f"{log.strip()}\n"

        sent_message = bot.send_message(ADMIN_ID, response)

        # Add deletion timer
        def delete_timer():
            time.sleep(15)
            try:
                bot.delete_message(message.chat.id, message.message_id)
                bot.delete_message(message.chat.id, sent_message.message_id)
            except Exception as e:
                logger.error(f"Error deleting log messages: {str(e)}")

        threading.Thread(target=delete_timer).start()

    except Exception as e:
        logger.error(f"Error viewing logs: {str(e)}")
        bot.send_message(ADMIN_ID, "❌ Ошибка при получении логов")


@bot.message_handler(commands=['check_connection'])
def check_connection(message):
    try:
        # Get chat info
        chat_id = message.chat.id
        chat = bot.get_chat(chat_id)
        chat_name = chat.title if chat.title else "Unnamed group"

        response = f"🔍 Проверка подключения к группе:\n\n"
        response += f"📢 Группа: {chat_name}\n"
        response += f"🆔 ID группы: {chat_id}\n\n"
        response += "📝 Последние 20 сообщений:\n\n"

        messages = []
        try:
            current_msg_id = message.message_id
            for _ in range(20):
                try:
                    msg = bot.forward_message(chat_id=chat_id,
                                              from_chat_id=chat_id,
                                              message_id=current_msg_id)
                    messages.append(msg)
                    bot.delete_message(chat_id, msg.message_id)  # Delete forwarded message
                except:
                    break
                current_msg_id -= 1
        except Exception as e:
            logger.error(f"Error getting messages: {str(e)}")

        for msg in messages:
            sender = msg.from_user.username if msg.from_user and msg.from_user.username else str(
                msg.from_user.id) if msg.from_user else "Unknown"
            content_type = "📄 Документ" if msg.document else "💬 Текст" if msg.text else "❓ Другое"
            time_str = msg.date.strftime("%d.%m.%Y %H:%M")

            response += f"• {time_str} | @{sender} | {content_type}\n"
            if msg.document:
                response += f"  📎 Файл: {msg.document.file_name}\n"
            elif msg.text:
                preview = msg.text[:50] + "..." if len(msg.text) > 50 else msg.text
                response += f"  📝 Текст: {preview}\n"
            response += "\n"

        # Send with auto-delete timer
        sent_message = bot.reply_to(message, response)

        def delete_timer():
            remaining_time = 14
            while remaining_time > 0:
                time.sleep(1)
                remaining_time -= 1
                try:
                    updated_response = response + f"\n⏱ Сообщение будет удалено через {remaining_time} секунд"
                    bot.edit_message_text(
                        updated_response,
                        message.chat.id,
                        sent_message.message_id
                    )
                except Exception as e:
                    logger.error(f"Error updating connection check timer: {str(e)}")
                    break

            try:
                bot.delete_message(message.chat.id, message.message_id)
                bot.delete_message(message.chat.id, sent_message.message_id)
            except Exception as e:
                logger.error(f"Error deleting connection check messages: {str(e)}")

        timer_thread = threading.Thread(target=delete_timer)
        timer_thread.start()

    except Exception as e:
        error_msg = f"❌ Ошибка проверки подключения:\n{str(e)}"
        logger.error(error_msg)
        bot.reply_to(message, error_msg)


@bot.message_handler(commands=['check_groups'])
def check_all_groups(message):
    try:
        if message.from_user.id != ADMIN_ID:
            return

        response = "📋 Список групп и каналов:\n\n"
        added_chats = set()

        # First check current chat
        current_chat = bot.get_chat(message.chat.id)
        if current_chat.type in ['group', 'supergroup', 'channel']:
            chat_info = f"• {current_chat.type.upper()}\n"
            chat_info += f"  📢 Название: {current_chat.title or 'Без названия'}\n"
            chat_info += f"  🆔 ID: {current_chat.id}\n"
            chat_info += f"  👥 Участников: {bot.get_chat_member_count(current_chat.id)}\n"
            response += chat_info + "\n"
            added_chats.add(current_chat.id)

        # Try to get bot's chat member updates
        for chat_id in [-1002361511573]:  # Add known GROUP_ID
            if chat_id in added_chats:
                continue
            try:
                chat = bot.get_chat(chat_id)
                if chat.type in ['group', 'supergroup', 'channel']:
                    chat_info = f"• {chat.type.upper()}\n"
                    chat_info += f"  📢 Название: {chat.title or 'Без названия'}\n"
                    chat_info += f"  🆔 ID: {chat.id}\n"
                    chat_info += f"  👥 Участников: {bot.get_chat_member_count(chat.id)}\n"
                    response += chat_info + "\n"
            except Exception as e:
                logger.error(f"Error getting chat {chat_id} info: {str(e)}")

        # Add note if no groups found
        if not response.strip():
            response = "❌ Бот не найден ни в одной группе или канале"

        # Send response with auto-delete timer
        sent_message = bot.send_message(message.chat.id, response)

        def delete_timer():
            remaining_time = 14
            while remaining_time > 0:
                time.sleep(1)
                remaining_time -= 1
                try:
                    updated_response = response + f"\n\n⏱ Сообщение будет удалено через {remaining_time} секунд"
                    bot.edit_message_text(
                        updated_response,
                        message.chat.id,
                        sent_message.message_id
                    )
                except Exception as e:
                    logger.error(f"Error updating groups list timer: {str(e)}")
                    break

            try:
                bot.delete_message(message.chat.id, message.message_id)
                bot.delete_message(message.chat.id, sent_message.message_id)
            except Exception as e:
                logger.error(f"Error deleting groups list messages: {str(e)}")

        timer_thread = threading.Thread(target=delete_timer)
        timer_thread.start()

    except Exception as e:
        error_msg = f"❌ Ошибка при получении списка групп:\n{str(e)}"
        logger.error(error_msg)
        bot.send_message(ADMIN_ID, error_msg)


@bot.message_handler(commands=['verify_tasks'], func=lambda message: message.from_user.id == ADMIN_ID)
def verify_tasks(message):
    try:
        GROUP_ID = -1002361511573  # The supergroup ID where bot is added
        initial_response = "🔄 Начинаю проверку сообщений в группе...\n\n"
        progress_message = bot.send_message(ADMIN_ID, initial_response)

        # Create temporary database
        temp_db_path = create_temp_message_db()
        conn = sqlite3.connect(temp_db_path)
        c = conn.cursor()

        try:
            chat = bot.get_chat(GROUP_ID)
            status_text = f"📢 Группа: {chat.title}\n"
            status_text += f"🆔 ID группы: {GROUP_ID}\n\n"

            bot.edit_message_text(initial_response + status_text + "🔍 Сканирование сообщений...",
                                  ADMIN_ID,
                                  progress_message.message_id)

            messages_checked = 0
            messages_found = 0
            five_hours_ago = datetime.now() - timedelta(hours=5)

            try:
                # Get messages using get_chat_history
                messages = bot.get_chat_history(GROUP_ID, limit=1000)

                for msg in messages:
                    msg_time = datetime.fromtimestamp(msg.date)

                    # Stop if message is older than 5 hours
                    if msg_time < five_hours_ago:
                        break

                    messages_checked += 1

                    # Store in temporary database
                    c.execute('''INSERT INTO messages 
                                (message_id, user_id, document_name, timestamp)
                                VALUES (?, ?, ?, ?)''',
                              (msg.message_id,
                               msg.from_user.id if msg.from_user else None,
                               msg.document.file_name if msg.document else None,
                               msg_time))

                    messages_found += 1
                    conn.commit()

                    if messages_checked % 5 == 0:
                        status = (f"{status_text}"
                                  f"📨 Проверено сообщений: {messages_checked}\n"
                                  f"📥 Найдено сообщений: {messages_found}\n"
                                  f"🔄 Продолжаю проверку...")
                        bot.edit_message_text(status, ADMIN_ID, progress_message.message_id)

                    # Send message info with auto-delete
                    msg_info = f"🔍 Проверяю сообщение #{msg.message_id}\n"
                    if msg.from_user:
                        msg_info += f"👤 От: {msg.from_user.username or msg.from_user.id}\n"
                    if msg.document:
                        msg_info += f"📎 Файл: {msg.document.file_name}\n"
                    msg_info += f"🕒 Время: {msg_time.strftime('%d.%m.%Y %H:%M')}"

                    info_message = bot.send_message(ADMIN_ID, msg_info)
                    threading.Thread(target=lambda: (time.sleep(2),
                                                     bot.delete_message(ADMIN_ID, info_message.message_id))).start()

            except Exception as e:
                logger.error(f"Error getting chat history: {str(e)}")
                # Fallback to older method if get_chat_history fails
                current_msg_id = message.message_id
                while messages_checked < 1000:
                    try:
                        msg = bot.copy_message(
                            chat_id=ADMIN_ID,
                            from_chat_id=GROUP_ID,
                            message_id=current_msg_id,
                            disable_notification=True
                        )

                        msg_time = datetime.fromtimestamp(msg.date)

                        if msg_time < five_hours_ago:
                            bot.delete_message(ADMIN_ID, msg.message_id)
                            break

                        # Store message in database
                        c.execute('''INSERT INTO messages 
                                    (message_id, user_id, document_name, timestamp)
                                    VALUES (?, ?, ?, ?)''',
                                  (msg.message_id,
                                   msg.from_user.id if msg.from_user else None,
                                   msg.document.file_name if msg.document else None,
                                   msg_time))

                        messages_found += 1
                        conn.commit()

                        # Delete copied message
                        bot.delete_message(ADMIN_ID, msg.message_id)

                    except Exception as e:
                        logger.debug(f"Message {current_msg_id} not found: {str(e)}")

                    current_msg_id -= 1
                    messages_checked += 1

                    if messages_checked % 5 == 0:
                        status = (f"{status_text}"
                                  f"📨 Проверено сообщений: {messages_checked}\n"
                                  f"📥 Найдено сообщений: {messages_found}\n"
                                  f"🔄 Продолжаю проверку...")
                        bot.edit_message_text(status, ADMIN_ID, progress_message.message_id)

            # Generate report
            df = pd.read_sql_query('''
                SELECT 
                    user_id AS "ID пользователя",
                    document_name AS "Имя документа",
                    datetime(timestamp, 'localtime') AS "Время сообщения"
                FROM messages 
                WHERE timestamp >= datetime('now', '-5 hours')
                ORDER BY timestamp DESC
            ''', conn)

            # Export to Excel
            export_path = 'message_analysis.xlsx'
            df.to_excel(export_path, index=False)

            final_status = (f"{status_text}"
                            f"✅ Проверка завершена\n"
                            f"📨 Всего проверено: {messages_checked}\n"
                            f"📥 Сохранено сообщений: {messages_found}")

            bot.edit_message_text(final_status, ADMIN_ID, progress_message.message_id)

            with open(export_path, 'rb') as file:
                bot.send_document(
                    ADMIN_ID,
                    file,
                    caption=f"📊 Отчет по проверке сообщений\n"
                            f"📂 Временная база: {os.path.basename(temp_db_path)}"
                )

            os.remove(export_path)

        except Exception as e:
            logger.error(f"Error in verification process: {str(e)}")
            bot.edit_message_text(f"❌ Ошибка при проверке: {str(e)}",
                                  ADMIN_ID,
                                  progress_message.message_id)

    except Exception as e:
        error_msg = f"❌ Ошибка запуска проверки: {str(e)}"
        logger.error(error_msg)
        bot.send_message(ADMIN_ID, error_msg)


@bot.message_handler(commands=['check_last_messages'], func=lambda message: message.from_user.id == ADMIN_ID)
def check_last_messages(message):
    try:
        GROUP_ID = -1002361511573

        status = "🔄 Получаю последние сообщения из группы..."
        progress_message = bot.send_message(ADMIN_ID, status)

        messages_found = []

        # Get chat info first
        chat = bot.get_chat(GROUP_ID)

        # Get chat administrators to verify bot permissions
        admins = bot.get_chat_administrators(GROUP_ID)
        bot_admin = next((admin for admin in admins if admin.user.id == bot.get_me().id), None)

        if not bot_admin:
            raise Exception("Бот не является администратором группы")

        # Get last messages using get_chat_history
        try:
            messages = bot.get_chat_history(GROUP_ID, limit=10)

            for msg in messages:
                msg_time = datetime.fromtimestamp(msg.date)
                msg_info = f"📝 Сообщение #{msg.message_id}\n"

                if msg.from_user:
                    msg_info += f"👤 От: {msg.from_user.username or msg.from_user.id}\n"

                if msg.document:
                    msg_info += f"📎 Файл: {msg.document.file_name}\n"
                elif msg.text:
                    msg_info += f"💬 Текст: {msg.text[:100]}...\n" if len(msg.text) > 100 else f"💬 Текст: {msg.text}\n"

                msg_info += f"🕒 Время: {msg_time.strftime('%d.%m.%Y %H:%M')}\n"
                msg_info += "───────────────────"

                messages_found.append(msg_info)

        except Exception as e:
            # Fallback to alternative method if get_chat_history fails
            current_msg_id = message.message_id
            for _ in range(10):
                try:
                    msg = bot.copy_message(
                        chat_id=ADMIN_ID,
                        from_chat_id=GROUP_ID,
                        message_id=current_msg_id,
                        disable_notification=True
                    )

                    msg_time = datetime.fromtimestamp(msg.date)
                    msg_info = f"📝 Сообщение #{msg.message_id}\n"

                    if msg.from_user:
                        msg_info += f"👤 От: {msg.from_user.username or msg.from_user.id}\n"

                    if msg.document:
                        msg_info += f"📎 Файл: {msg.document.file_name}\n"
                    elif msg.text:
                        msg_info += f"💬 Текст: {msg.text[:100]}...\n" if len(
                            msg.text) > 100 else f"💬 Текст: {msg.text}\n"

                    msg_info += f"🕒 Время: {msg_time.strftime('%d.%m.%Y %H:%M')}\n"
                    msg_info += "───────────────────"

                    messages_found.append(msg_info)

                    # Delete copied message
                    bot.delete_message(ADMIN_ID, msg.message_id)

                except Exception as e:
                    logger.debug(f"Message {current_msg_id} not found: {str(e)}")

                current_msg_id -= 1

        if messages_found:
            result = "📋 Последние сообщения в группе:\n\n" + "\n\n".join(messages_found)

            # Send messages info and delete after 5 seconds
            sent = bot.edit_message_text(result, ADMIN_ID, progress_message.message_id)

            def delete_timer():
                time.sleep(5)
                try:
                    bot.delete_message(ADMIN_ID, message.message_id)
                    bot.delete_message(ADMIN_ID, sent.message_id)
                except Exception as e:
                    logger.error(f"Error deleting messages: {str(e)}")

            threading.Thread(target=delete_timer).start()

        else:
            bot.edit_message_text("❌ Сообщения не найдены", ADMIN_ID, progress_message.message_id)

    except Exception as e:
        error_msg = f"❌ Ошибка при получении сообщений: {str(e)}"
        logger.error(error_msg)
        bot.send_message(ADMIN_ID, error_msg)


def main():
    try:
        initialize_db()
        logger.info("Bot started")
        send_admin_log("🤖 Бот запущен и готов к работе")
        while True:
            try:
                bot.polling(none_stop=True, timeout=60)
            except Exception as polling_error:
                logger.error(f"Polling error: {str(polling_error)}")
                time.sleep(5)
    except Exception as e:
        logger.error(f"Bot error: {str(e)}")
    finally:
        try:
            bot.stop_polling()
        except:
            pass


if __name__ == '__main__':
    main()