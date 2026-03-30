import logging
import json
import requests
from logging import StreamHandler, FileHandler 

class TelegramHandler(logging.Handler):
    def __init__(self, token, chat_id):
        super().__init__()
        self.token = token
        self.chat_id = chat_id

    def emit(self, record):
        log_entry = self.format(record)
        requests.post(f'https://api.telegram.org/bot{self.token}/sendMessage', data={
            'chat_id': self.chat_id,
            'text': log_entry
        })

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            'level': record.levelname,
            'message': record.getMessage(),
            'time': self.formatTime(record),
            'name': record.name,
        }
        return json.dumps(log_record)

def setup_logger(token, chat_id):
    logger = logging.getLogger('my_logger')
    logger.setLevel(logging.DEBUG)

    json_handler = StreamHandler()  
    json_handler.setFormatter(JSONFormatter())
    logger.addHandler(json_handler)

    telegram_handler = TelegramHandler(token, chat_id)
    telegram_handler.setFormatter(JSONFormatter())
    logger.addHandler(telegram_handler)

    file_handler = FileHandler('app.log')
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)

    return logger

if __name__ == '__main__':
    TOKEN = 'Your_Telegram_Bot_Token'
    CHAT_ID = 'Your_Telegram_Chat_ID'
    logger = setup_logger(TOKEN, CHAT_ID)

    # Example usage
    logger.info('This is an info message')
    logger.error('This is an error message')