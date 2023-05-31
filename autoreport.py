from telebot import *
import requests
from dotenv import load_dotenv
from os import getenv
from rocketchat_API.rocketchat import RocketChat
from apscheduler.schedulers.background import BackgroundScheduler
import re

load_dotenv()

MESSAGE = """
📓*Отчёт за неделю*

{chatbot_tasks}

{multichat_tasks}

{calltracking_tasks}

{other_tasks}

Всего задач выполнено: {total_done}
"""
BUG = "🪲"
TASK = "✔️"
EPIC = "⚡️"
IMPROVMENT = "⬆️"
FEATURE = "❇️"
ELSE = "➕"
REPORT = MESSAGE

bot = TeleBot(getenv("TELETOKEN"))
rocket = RocketChat(
    user_id=getenv("ROCKET_CHAT_USER_ID"),
    auth_token=getenv("ROCKET_CHAT_API_TOKEN"),
    server_url=getenv("ROCKET_SERVER_URL"),
)
schedule = BackgroundScheduler()


def get_tasks() -> dict:
    response = requests.get(
        "https://mcntelecom.atlassian.net/rest/api/2/search",
        headers={"Content-Type": "application/json"},
        params={"jql": "project = NP AND (resolutionDate >= -1w AND status = Done) ORDER BY Rank ASC"},
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
                    cur_task += IMPROVMENT
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


def make_report() -> str:
    tasks = get_tasks()
    components = parse_to_components(tasks["issues"])
    report = MESSAGE.format(
        chatbot_tasks=component_to_text(components.get("CHATBOT"), "Чат-боты") or "",
        calltracking_tasks=component_to_text(components.get("CALLTRACKING"), "Коллтрекинг") or "",
        multichat_tasks=component_to_text(components.get("MULTICHAT"), "Мультичат") or "",
        other_tasks=component_to_text(components.get("OTHER"), "Прочее") or "",
        total_done=tasks["total"],
    )
    report = re.sub(r"\n{2,}", "\n", report)
    return report


def send_report():
    global REPORT
    REPORT = make_report()
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
    global REPORT
    resp=rocket.chat_post_message(REPORT, channel=getenv("ROCKET_CHANNEL_NAME")).json()
    rocket.chat_pin_message(resp['message']['_id'])
    bot.answer_callback_query(cb.id, "sent")


if __name__ == "__main__":
    schedule.add_job(send_report, "cron", day_of_week="fri", hour=19)
    schedule.start()
    send_report()
    print(bot.user.username)
    bot.polling()
