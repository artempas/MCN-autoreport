import asyncio
import os
from threading import Thread
import time
import socketio
from telebot import *
import requests
from datetime import datetime
from dotenv import load_dotenv
from os import getenv
# from rocketchat_API.rocketchat import RocketChat
from apscheduler.schedulers.background import BackgroundScheduler
import simplematrixbotlib as botlib
import re
from statistics import fmean
import matplotlib.pyplot as plt
from traceback import format_exc

load_dotenv()

days_cnt=7
MESSAGE = """
📓**Отчёт за последние {days_cnt} дней**

{chatbot_tasks}

{contact_center_tasks}

{multichat_tasks}

{calltracking_tasks}

{other_tasks}

Всего задач выполнено: {total_done}
"""
TELEGRAM_MESSAGE = """
📓*Последние обновления*

{chatbot_tasks}

{multichat_tasks}
"""
BUG = "🪲"
TASK = "✔️"
EPIC = "⚡️"
IMPROVEMENT = "⬆️"
FEATURE = "❇️"
ELSE = "➕"
REPORT = MESSAGE
TELEGRAM_REPORT = TELEGRAM_MESSAGE

bot = TeleBot(getenv("TELETOKEN"))
# rocket = RocketChat(
#     user_id=getenv("ROCKET_CHAT_USER_ID"),
#     auth_token=getenv("ROCKET_CHAT_API_TOKEN"),
#     server_url=getenv("ROCKET_SERVER_URL"),
# )
element=botlib.Bot(botlib.Creds(getenv('ELEMENT_SERVER_URL'), getenv("ELEMENT_USERNAME"), getenv("ELEMENT_PASSWORD")))
schedule = BackgroundScheduler()
NOTIFY=False
ALERT=False
ALERT_MESSAGE=''
SKIP_HEALTHCHECK_COUNT=0
HEALTCHECK_PROGRESSIVE_REDUCER=0
SUPRESS_WARNING_UNTIL=0
GRAPH_FILE=''

RESPONSE_TIME=[]
TIMESTAMPS=[]

def get_tasks() -> dict:
    global days_cnt
    response = requests.get(
        "https://mcntelecom.atlassian.net/rest/api/2/search",
        headers={"Content-Type": "application/json"},
        params={"jql": f"project = NP AND (resolutionDate >= -{days_cnt}d AND status = Done) ORDER BY Rank ASC"},
        auth=("artem1459@gmail.com", getenv("jiraToken")),
    )
    return response.json()


def parse_to_components(tasks: list[dict]) -> dict[str, list[str]]:
    res = {}
    for task in tasks:
        if task["fields"].get("customfield_10052"):
            cur_task = ""
            match task["fields"]["issuetype"]["name"]:
                case "Improvement":
                    cur_task += IMPROVEMENT
                case "Task":
                    cur_task += TASK
                case "New Feature":
                    cur_task += FEATURE
                case "Bug":
                    cur_task += BUG
                case "Epic":
                    cur_task += EPIC
                case _:
                    cur_task += ELSE
            cur_task += task["fields"]["customfield_10052"].replace("\n", " ")
            cur_task += f" ([{task['key']}](https://mcntelecom.atlassian.net/browse/{task['key']}))"
            components = task["fields"].get("components")
            if components:
                for component in components:
                    if component["name"] in res:
                        res[component["name"]].append(cur_task)
                    else:
                        res[component["name"]] = [cur_task]
            else:
                if "OTHER" in res:
                    res["OTHER"].append(cur_task)
                else:
                    res["OTHER"] = [cur_task]
    return res


def component_to_text(tasks: list[str], component_name: str) -> str | None:
    if tasks is not None:
        res = component_name + "\n\t"
        res += "\n\t".join(tasks)
        return res
    else:
        return None


def make_report() -> (str, str):
    global days_cnt
    tasks = get_tasks()
    components = parse_to_components(tasks["issues"])
    report = MESSAGE.format(
        chatbot_tasks=component_to_text(components.get("CHATBOT"), "Чат-боты") or "",
        calltracking_tasks=component_to_text(components.get("CALLTRACKING"), "Коллтрекинг") or "",
        multichat_tasks=component_to_text(components.get("MULTICHAT"), "Мультичат") or "",
        contact_center_tasks=component_to_text(components.get("CONTACT-CENTER"), "Контакт-центр") or "",
        other_tasks=component_to_text(components.get("OTHER"), "Прочее") or "",
        total_done=tasks["total"],
        days_cnt=days_cnt
    )
    telegram_report = TELEGRAM_MESSAGE.format(
        chatbot_tasks=component_to_text(components.get("CHATBOT"), "Чат-боты") or "",
        multichat_tasks=component_to_text(components.get("MULTICHAT"), "Мультичат") or "",
    )
    while "\n\n\n" in report:
        report = report.replace("\n\n\n", "\n\n")
    return report, telegram_report


@bot.message_handler(commands=['start'])
def send_report(_=None):
    global REPORT, TELEGRAM_REPORT
    REPORT, TELEGRAM_REPORT = make_report()
    pattern = re.compile(r"\(\[NP-[0-9]+]\(https://mcntelecom\.atlassian\.net/browse/NP-[0-9]+\)\)", re.IGNORECASE)
    TELEGRAM_REPORT = pattern.sub('', TELEGRAM_REPORT)
    bot.send_message(
        getenv("CHAT_ID"),
        REPORT,
        reply_markup=util.quick_markup(
            {"publish report": {"callback_data": "publish"}, "regenerate report": {"callback_data": "regenerate"}}
        ),
        parse_mode="Markdown",
    )


@bot.callback_query_handler(lambda c: c.data == "regenerate")
def regenerate_cb(cb: types.CallbackQuery):
    send_report()
    bot.answer_callback_query(cb.id, "Regenerated")


@bot.message_handler(commands=["generate"])
def regenerate_msg(_):
    send_report()


@bot.callback_query_handler(lambda c: c.data == "publish")
def publish_report(cb: types.CallbackQuery):
    global REPORT, TELEGRAM_REPORT
    #resp=rocket.chat_post_message(REPORT, channel=getenv("ROCKET_CHANNEL_NAME")).json()
    # rocket.chat_pin_message(resp['message']['_id'])
    bot.send_message(getenv("TELEGRAM_CHANNEL_CHAT_ID"), TELEGRAM_REPORT, parse_mode='Markdown')
    bot.answer_callback_query(cb.id, "sent")
    NOTIFY=True
    th = Thread(target=element.run)
    th.start()

@bot.message_handler(content_types=['text'])
def set_days(msg):
    global days_cnt
    if (msg.text.isnumeric()):
        days_cnt=int(msg.text)
    bot.send_message(msg.chat.id, f"Number of days set to {days_cnt}")

@element.listener.on_startup
async def send_to_element(room_id):
    global NOTIFY
    global ALERT
    global ALERT_MESSAGE
    global GRAPH_FILE
    print(room_id)
    task=None
    if (room_id==getenv('ELEMENT_NOTIFICATION_ROOM_ID') and NOTIFY):
        print('sending report')
        task = await asyncio.create_task(element.api.send_markdown_message(room_id, REPORT))
        NOTIFY=False
        raise Exception('Gracefully stopping thread')
    elif (room_id==getenv('ELEMENT_ALERT_ROOM_ID') and ALERT):
        print('sending alert')
        if ALERT_MESSAGE:
            await asyncio.create_task(element.api.send_markdown_message(room_id, ALERT_MESSAGE))
            ALERT_MESSAGE=''
        if GRAPH_FILE:
            await asyncio.create_task(element.api.send_image_message(room_id, GRAPH_FILE))
            os.remove(GRAPH_FILE)
            GRAPH_FILE=''
        ALERT=False
        raise Exception('Gracefully stopping thread')
    elif not (NOTIFY or ALERT):
        raise Exception('Neither NOTIFY nor ALERT are True. Stopping')
    return task

def raise_exc(_):
    time.sleep(5)
    raise Exception()

def widget_healthcheck():
    global SKIP_HEALTHCHECK_COUNT
    global SUPRESS_WARNING_UNTIL
    global HEALTCHECK_PROGRESSIVE_REDUCER
    global ALERT
    global ALERT_MESSAGE
    warning_text=''
    if SKIP_HEALTHCHECK_COUNT:
        SKIP_HEALTHCHECK_COUNT-=1
        return
    try:
        print('Performing healthcheck')
        platform_user_id=f"healthCheckUser{time.time()}"
        print(platform_user_id)
        chat_user_id_req = requests.post('https://chatbots.mcn.ru/adapter/public/webhook/defprefix/2896/67093/mcn-widget', json={
        "platform_user_id": platform_user_id,
        "type": "getChatUser",
        "widget_referrer": 'healthcheck'
        })
        if chat_user_id_req.status_code//100 != 2:
            raise Exception(f'**Chatbots wasn\'t able to create chat_user. Status code: {chat_user_id_req.status_code}**')
        if not chat_user_id_req.text.isdecimal():
            raise Exception(f'**Chatbots wasn\'t able to create chat_user. Wrong response** ```{chat_user_id_req.text}```')
        chat_user_id=int(chat_user_id_req.text)
        with socketio.SimpleClient() as sio:
            sio.connect(f'https://chatbots.mcn.ru/adapter/public_ws?platform_user_id={platform_user_id}&chat_user_id={chat_user_id}&chat_id=2896&token=75d697af25',
                        socketio_path='adapter/public_ws',
            )
            message_req=requests.post('https://chatbots.mcn.ru/adapter/public/webhook/defprefix/2896/67093/mcn-widget', json={
                "platform_user_id": platform_user_id,
                "type": "message",
                "message": {
                    "text": "/start"
                }
            })
            if message_req.status_code//100 != 2:
                raise Exception(f'**Chatbots wasn\'t able to receive message. Status code: {message_req.status_code}**')
            message_received=False
            wait_for=1
            start_time=time.time()
            try:
                message=sio.receive(timeout=10)
                assert message[0]=='message' and message[1]['message_data']['data']['text']=='/start'
                message=sio.receive(timeout=10)
                assert message[0]=='message' and message[1]['sender_type']=='bot'
                message_received=True
            except TimeoutError:
                warning_text='Unable to receive update via WS'
        def time_passed():
            return time.time()-start_time
        while not message_received:
            last_messages_response = requests.get(f'https://chatbots.mcn.ru/api/public/api/get_last_messages_by_token?token=75d697af25&chat_user_id={chat_user_id}')
            if chat_user_id_req.status_code//100 != 2:
                raise Exception(f'**Chatbots wasn\'t able to return messages. Status code:** {last_messages_response.status_code}')
            if not last_messages_response.json().get('ok'):
                raise Exception(f'**Error getting last messages. Response:** ```{last_messages_response.json()}```')
            if len(last_messages_response.json()['messages'])<2:
                print('got not enough messages')
                if time_passed()<30: 
                    wait_for+=1
                    time.sleep(wait_for)
                    continue
                else:
                    HEALTCHECK_PROGRESSIVE_REDUCER+=1
                    SKIP_HEALTHCHECK_COUNT=HEALTCHECK_PROGRESSIVE_REDUCER
                    raise Exception(f'**Chatbots were unable to respond to message in {time_passed():.1f}sec! Next check will be performed in {(SKIP_HEALTHCHECK_COUNT+1)*30/60} minutes**')
            else:
                message_received=True
        
        print(f'Healthcheck performed in {time_passed()}sec')
        TIMESTAMPS.append(datetime.now())
        RESPONSE_TIME.append(time_passed())
        if HEALTCHECK_PROGRESSIVE_REDUCER>0:
            HEALTCHECK_PROGRESSIVE_REDUCER=0
            raise Exception(f'Chatbots are back to normal. Response time: {time_passed():.1f}sec')
        if time_passed()>10:
            warning_text += f'Warning. Chatbots response time is {time_passed():.1f} seconds'
        if warning_text and time.time()>SUPRESS_WARNING_UNTIL:
            warning_text+='\n _Warnings won\'t be shown in next 10 minutes_'
            SUPRESS_WARNING_UNTIL=time.time()+10*60
            ALERT=True
            ALERT_MESSAGE=warning_text
            th = Thread(target=element.run)
            th.start()
        requests.delete('https://chatbots.mcn.ru/api/protected/api/chat_user', json={'chat_user_id': chat_user_id}, headers={'Authorization': f'Bearer {getenv("MCN_PROTECTED_API_KEY")}'})


    except Exception as exc:
        traceback.print_exc()
        ALERT=True
        ALERT_MESSAGE=str(exc)
        th = Thread(target=element.run)
        th.start()

def average_response_time():
    global ALERT
    global ALERT_MESSAGE
    global GRAPH_FILE
    global TIMESTAMPS
    global RESPONSE_TIME
    today=datetime.today().strftime("%d.%m.%Y")
    plt.plot(TIMESTAMPS,RESPONSE_TIME)
    plt.grid()
    plt.title(f'{today} Average response time: {fmean(RESPONSE_TIME):.2f}sec')
    plt.ylabel('Seconds')
    plt.savefig(f"{today}.png")
    plt.clf()
    RESPONSE_TIME=[]
    TIMESTAMPS=[]
    ALERT=True
    ALERT_MESSAGE=f'Report for {today}'
    GRAPH_FILE=f'{today}.png'
    th = Thread(target=element.run)
    th.start()



if __name__ == "__main__":
    schedule.add_job(send_report, "cron", day_of_week="fri", hour=19, args=('',))
    schedule.add_job(widget_healthcheck, "interval", seconds=30)
    schedule.add_job(average_response_time, 'cron', hour=10)
    schedule.start()
    bot.polling()

