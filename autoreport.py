import asyncio
from threading import Thread

from telebot import *
import requests
from dotenv import load_dotenv
from os import getenv
# from rocketchat_API.rocketchat import RocketChat
from apscheduler.schedulers.background import BackgroundScheduler
import simplematrixbotlib as botlib
import re

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
    task = asyncio.create_task(element.api.send_markdown_message(room_id, REPORT))
    task.add_done_callback(raise_exc)
    return task

def raise_exc(_):
    time.sleep(5)
    raise Exception()

if __name__ == "__main__":
    schedule.add_job(send_report, "cron", day_of_week="fri", hour=19, args=('',))
    schedule.start()
    bot.polling()

