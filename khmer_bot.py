from telegram import InputMedia
from telegram.ext import ExtBot

from localization import translate_reply_markup, translate_ui_text


def _translate_kwargs(kwargs):
    result = dict(kwargs)
    for key in ("text", "caption"):
        if key in result:
            result[key] = translate_ui_text(result[key])
    if "reply_markup" in result:
        result["reply_markup"] = translate_reply_markup(result["reply_markup"])
    return result


class KhmerExtBot(ExtBot):
    async def send_message(self, *args, **kwargs):
        return await super().send_message(*args, **_translate_kwargs(kwargs))

    async def edit_message_text(self, *args, **kwargs):
        return await super().edit_message_text(*args, **_translate_kwargs(kwargs))

    async def send_photo(self, *args, **kwargs):
        return await super().send_photo(*args, **_translate_kwargs(kwargs))

    async def send_document(self, *args, **kwargs):
        return await super().send_document(*args, **_translate_kwargs(kwargs))

    async def send_video(self, *args, **kwargs):
        return await super().send_video(*args, **_translate_kwargs(kwargs))

    async def edit_message_caption(self, *args, **kwargs):
        return await super().edit_message_caption(
            *args, **_translate_kwargs(kwargs)
        )

    async def edit_message_reply_markup(self, *args, **kwargs):
        return await super().edit_message_reply_markup(
            *args, **_translate_kwargs(kwargs)
        )

    async def edit_message_media(self, *args, **kwargs):
        translated = _translate_kwargs(kwargs)
        media = translated.get("media")
        if isinstance(media, InputMedia) and media.caption:
            media._unfreeze()
            media.caption = translate_ui_text(media.caption)
            media._freeze()
        return await super().edit_message_media(*args, **translated)
