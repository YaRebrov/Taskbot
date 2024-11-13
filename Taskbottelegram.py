import telebot
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage
import re
import sqlite3
from datetime import datetime
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='bot_log.log'
)
logger = logging.getLogger(__name__)

# Инициализация бота
state_storage = StateMemoryStorage()
bot = telebot.TeleBot("7329953385:AAETw5G3BruiV5nYmBUyHrMnyuw_HAi6b7k", state_storage=state_storage)

# ID пользователей
SENDER_ID = 1846983750
PROCESSOR_ID = 6674781903


# Приветственное сообщение
@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = """
👋 Добро пожаловать! 
🤖 Я бот для обработки документов.

Доступные команды:
/status - Проверить статус документов
/whoami - Узнать свой ID и роль
/clear_queue - Очистить очередь задач
"""
    bot.reply_to(message, welcome_text)


# Создание базы данных
def initialize_db():
    conn = sqlite3.connect('documents.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS documents
                 (order_number TEXT, 
                  document_name TEXT,
                  status TEXT,
                  sender_id INTEGER,
                  timestamp DATETIME,
                  processed BOOLEAN)''')
    conn.commit()
    conn.close()


# Извлечение номера заказа из имени файла
def extract_order_number(filename):
    # Поиск различных форматов DOR-EX с цифрами
    patterns = [
        r'DOR[\s-]?EX[\s-]?(\d+)[\s-]?(\d+)',  # Базовый формат
        r'DOR[\s-]?EX[\s-]?(\d+)[\s-]?(\d+)K\d*',  # Формат с K и цифрами после
        r'DOR[\s-]?EX[-\s]?(\d+)[-\s]?(\d+).*'  # Любой формат с доп. символами после
    ]

    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            # Извлекаем только цифровые части и форматируем в стандартный вид
            return f"DOR-EX {match.group(1)}-{match.group(2)}"
    return None


# Обработка входящих документов
@bot.message_handler(content_types=['document'])
def handle_docs(message):
    try:
        logger.info(f"Received message from user ID: {message.from_user.id}")

        if message.from_user.id not in [SENDER_ID, PROCESSOR_ID]:
            logger.warning(f"Unauthorized access attempt from user ID: {message.from_user.id}")
            bot.reply_to(message, "У вас нет доступа к этому боту.")
            return

        document_name = message.document.file_name
        order_number = extract_order_number(document_name)

        if order_number:
            conn = sqlite3.connect('documents.db')
            c = conn.cursor()

            if message.from_user.id == SENDER_ID:
                status = 'requested'
                processed = False

            else:  # Processor handling
                c.execute('''SELECT COUNT(*) 
                            FROM documents 
                            WHERE order_number = ? AND sender_id = ? AND status = 'requested' ''',
                          (order_number, SENDER_ID))
                if c.fetchone()[0] > 0:
                    c.execute('''UPDATE documents 
                               SET processed = TRUE, status = 'processed' 
                               WHERE order_number = ? AND sender_id = ?''',
                              (order_number, SENDER_ID))
                status = 'processed'
                processed = True

            c.execute('''INSERT INTO documents 
                        (order_number, document_name, status, sender_id, timestamp, processed) 
                        VALUES (?, ?, ?, ?, ?, ?)''',
                      (order_number, document_name, status, message.from_user.id,
                       datetime.now(), processed))

            conn.commit()
            conn.close()

        else:
            bot.reply_to(message,
                         f"❌ Некорректный формат номера заказа в названии файла\n"
                         f"📄 Название документа: {document_name}\n"
                         f"⚠️ Номер заказа должен быть в формате: DOR-EX XXX-XX")

    except Exception as e:
        logger.error(f"Error processing document: {str(e)}")
        error_message = (f"❌ Произошла ошибка при обработке документа.\n"
                         f"📄 Название документа: {document_name}\n"
                         f"🔍 Найденный номер заказа: {order_number if 'order_number' in locals() else 'не найден'}")
        bot.reply_to(message, error_message)


# Команда для очистки очереди задач
@bot.message_handler(commands=['clear_queue'])
def clear_queue(message):
    try:
        if message.from_user.id not in [SENDER_ID, PROCESSOR_ID]:
            bot.reply_to(message, "❌ У вас нет прав для очистки очереди задач.")
            return

        conn = sqlite3.connect('documents.db')
        c = conn.cursor()
        c.execute('''DELETE FROM documents''')  # Очищаем все записи
        conn.commit()
        conn.close()

        logger.info(f"Queue cleared by user {message.from_user.id}")

    except Exception as e:
        logger.error(f"Error clearing queue: {str(e)}")


# Команда для получения статистики
@bot.message_handler(commands=['status'])
def get_status(message):
    try:
        conn = sqlite3.connect('documents.db')
        c = conn.cursor()

        # Получаем неоработанные заказы
        c.execute('''SELECT DISTINCT order_number FROM documents 
                    WHERE sender_id = ? AND status = 'requested' ''', (SENDER_ID,))
        requested_orders = c.fetchall()

        # Получаем обработанные заказы
        c.execute('''SELECT DISTINCT order_number FROM documents 
                    WHERE sender_id = ? AND status = 'processed' ''', (SENDER_ID,))
        processed_orders = c.fetchall()

        # Подсчет количества задач
        requested_count = len(requested_orders)
        processed_count = len(processed_orders)

        response = "📋 Статус обработки документов:\n\n"

        response += "⏳ Ожидают обработки:\n"
        for order in requested_orders:
            response += f"{order[0]}\n"

        response += "\nОбработано:\n"
        for order in processed_orders:
            response += f"{order[0]}\n"

        # Добавляем статистику
        response += f"\nСтатистика (ожидает/обработано): {requested_count}/{processed_count}"

        bot.reply_to(message, response)
        conn.close()

    except Exception as e:
        logger.error(f"Error generating status: {str(e)}")
        bot.reply_to(message, "Произошла ошибка при формировании статуса.")


# Команда для проверки ID и роли пользователя
@bot.message_handler(commands=['whoami'])
def whoami(message):
    user_id = message.from_user.id
    user_type = "неизвестный пользователь"
    if user_id == SENDER_ID:
        user_type = "отправитель заданий"
    elif user_id == PROCESSOR_ID:
        user_type = "обработчик заданий"

    bot.reply_to(message, f"Ваш ID: {user_id}\nВаша роль: {user_type}")


# Инициализация и запуск бота
def main():
    try:
        initialize_db()
        logger.info("Bot started")
        bot.polling(none_stop=True)
    except Exception as e:
        logger.error(f"Bot error: {str(e)}")


if __name__ == '__main__':
    main()