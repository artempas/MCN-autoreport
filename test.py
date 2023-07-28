from os import getenv

import nio
import simplematrixbotlib as botlib
from dotenv import load_dotenv

load_dotenv()
bot=botlib.Bot(botlib.Creds(getenv('ELEMENT_SERVER_URL'), getenv("ELEMENT_USERNAME"), getenv("ELEMENT_PASSWORD")))
@bot.listener.on_message_event
async def echo(room:nio.rooms.MatrixRoom, message):
    """
    Example function that "echoes" arguements.
    Usage:
    example_user- !echo say something
    echo_bot- say something
    """
    print(f"{room.room_id=}, {message=}")
    await bot.api.send_text_message('!irLHvXSVpQoKGypvfY:mcn.hu', 'rfasdd')
