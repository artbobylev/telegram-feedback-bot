from os import getenv

from telegram import Message, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.helpers import escape_markdown
from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from feedbackbot import TELEGRAM_CHAT_ID, application, SITE_URL
from feedbackbot.db.curd import (
    add_mapping,
    get_topic,
    increment_incoming_stats,
    increment_usage_times,
    remove_user_mappings,
)
from feedbackbot.utils.telegram import create_topic_and_add_to_db, get_reply_to_message_id

default_message_text = "استلمنا رسالتك. سنرد عليك في أقرب وقت."
message_text = escape_markdown(
    getenv("MESSAGE_RECEIVED", default_message_text).replace("\\n", "\n")
)


async def forward_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_message is not None
    topic_id = get_topic(update.effective_chat.id)
    if not topic_id:
        topic = await create_topic_and_add_to_db(update, context)
        topic_id = topic.topic_id
    try:
        forwarded: Message = await update.effective_message.forward(
            chat_id=TELEGRAM_CHAT_ID,
            message_thread_id=topic_id,
            disable_notification=True,
        )
    except BadRequest as err:
        if err.message == "Message thread not found":
            # Topic was deleted, create a new one
            remove_user_mappings(update.effective_chat.id)
            topic = await create_topic_and_add_to_db(update, context)
            topic_id = topic.topic_id
            forwarded = await update.effective_message.forward(
                chat_id=TELEGRAM_CHAT_ID,
                message_thread_id=topic_id,
                disable_notification=True,
            )
        else:
            raise err
    add_mapping(
        update.effective_chat.id,
        update.effective_message.message_id,
        topic_id,
        forwarded.message_id,
    )
    await update.effective_message.reply_text(
        message_text, reply_to_message_id=get_reply_to_message_id(update)
    )
    increment_incoming_stats()
    increment_usage_times(update.effective_chat.id)

async def webapp_order_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_message is not None
    topic_id = get_topic(update.effective_chat.id)
    if not topic_id:
        topic = await create_topic_and_add_to_db(update, context)
        topic_id = topic.topic_id

    webapp_data = update.effective_message.web_app_data
    if webapp_data is not None:
        data = webapp_data.data
        data_json = json.loads(data)
        message_text = "Вы выбрали: \n\n"
        for product_id, product_info in data_json.items():
            message_text += "*" + str(product_info["name"]) + "*    " + str(product_info["price"]) + "₽     " + str(product_info["quantity"]) + "шт. \n" + SITE_URL + str(product_info["href"]) +"\n\n"
            keyboard = [
                [KeyboardButton(text="Да! Жду подробностей")]
            ]
            keyboard = ReplyKeyboardMarkup(keyboard)

            await update.effective_message.reply_text(
                message_text, reply_to_message_id=get_reply_to_message_id(update), parse_mode="Markdown"
            )
            await update.effective_message.reply_text("Всё верно?", reply_to_message_id=get_reply_to_message_id(update), reply_markup=keyboard)

            try:
                order_send: Message = await context.bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    message_thread_id=topic_id,
                    text=message_text,
                )
            except BadRequest as err:
                if err.message == "Message thread not found":
                    # Topic was deleted, create a new one
                    remove_user_mappings(update.effective_chat.id)
                    topic = await create_topic_and_add_to_db(update, context)
                    topic_id = topic.topic_id
                    order_send = await context.bot.send_message(
                        chat_id=TELEGRAM_CHAT_ID,
                        message_thread_id=topic_id,
                        text=message_text,
                    )
                else:
                    raise err

async def order_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_message is not None
    if "Да! Жду подробностей" in update.effective_message.text:
        await update.effective_message.reply_text(
            text='Отлично, наш менеджер Вам скоро ответит!',
            reply_to_message_id=get_reply_to_message_id(update),
            reply_markup=ReplyKeyboardRemove(),
        )
    await forward_handler(update, context)
    
application.add_handler(
    MessageHandler(filters.Regex(r'^Да! Жду подробностей$'), order_confirm_handler)
)

application.add_handler(
    MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp_order_handler)
)

application.add_handler(
    MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, forward_handler)
)
