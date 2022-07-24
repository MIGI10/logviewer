__version__ = "1.1"

import os
import requests
import math


from motor.motor_asyncio import AsyncIOMotorClient
from sanic import Sanic, response
from sanic.exceptions import NotFound, Forbidden, SanicException
from jinja2 import Environment, FileSystemLoader

from core.models import LogEntry


if "URL_PREFIX" in os.environ:
    print("Using the legacy config var `URL_PREFIX`, rename it to `LOG_URL_PREFIX`")
    prefix = os.environ["URL_PREFIX"]
else:
    prefix = os.getenv("LOG_URL_PREFIX", "/logs")

if prefix == "NONE":
    prefix = ""

app = Sanic(__name__)

app.static("/static", "./static")

jinja_env = Environment(loader=FileSystemLoader("templates"))


def render_template(name, *args, **kwargs):
    template = jinja_env.get_template(name + ".html")
    return response.html(template.render(*args, **kwargs))


async def oauth_check(request, document, key):

    if "raw" in request.path:
        key = key + "@"
    
    redirect_uri = os.getenv("OAUTH_URI") + "&state=" + key

    if request.query_args:

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        data = {
            'client_id': os.getenv("OAUTH_CLIENT_ID"),
            'client_secret': os.getenv("OAUTH_CLIENT_SECRET"),
            'grant_type': 'authorization_code',
            'code': request.query_args[0][1],
            'redirect_uri': os.getenv("OAUTH_REDIRECT_URI")
        }

        oauth = requests.post('https://discord.com/api/v9/oauth2/token', data=data, headers=headers)
        oauth = oauth.json()

        if "error" in oauth: 
            return redirect_uri

        headers = {
            'authorization': oauth["token_type"] + ' ' + oauth["access_token"]
        }

        member = requests.get('https://discord.com/api/v9/users/@me/guilds/739552045123764275/member', headers=headers)
        member = member.json()
        print(member)

        if 'user' not in member:
            user = requests.get('https://discord.com/api/v9/users/@me', headers=headers)
            user = user.json()
            print(user)
            print("---- {}#{} with ID {} accessing site".format(user["username"], user["discriminator"], user["id"]))
        else:
            print("---- {}#{} with ID {} accessing site".format(member["user"]["username"], member["user"]["discriminator"], member["user"]["id"]))

        if 'global' in member:
            print("---- Ratelimit by Discord API")
            return "Retry after " + str(math.ceil(member["retry_after"])) + " seconds"

        if 'roles' not in member:
            print("---- User not in guild")
            return "You're not a server member"

        if '822253899700371488' not in member["roles"] and '739552877911212144' not in member["roles"]:
            print("---- User without Discord/Twitch staff role")
            return "You're not a staff member"

        if document["title"] == "admin" and '739552527288107109' not in member["roles"]:
            print("---- Admin ticket, user without admin role")
            return "Admin ticket, you're not an admin/manager"

        return None

    else:
        return redirect_uri

app.ctx.render_template = render_template

db_name = os.getenv("MONGO_DB_NAME")

@app.listener("before_server_start")
async def init(app, loop):
    app.ctx.db = AsyncIOMotorClient(os.getenv("MONGO_URI"))[db_name]

@app.exception(NotFound)
async def not_found(request, exc):
    return render_template("not_found")


@app.get("/")
async def index(request):
    return render_template("index")


@app.get("/return")
async def redirect_to_log(request):

    global prefix

    if not request.query_args:
        return render_template("index")

    key = request.query_args[1][1]

    if "@" in key or "%40" in key:
        prefix = prefix + "/raw"
        if "@" in key:
            key = key[:-1]
        else:
            key = key[:-3]
    
    return response.redirect('http://' + request.host + prefix + '/' + key + '?code=' + request.query_args[0][1])


@app.get(prefix + "/raw/<key>")
async def get_raw_logs_file(request, key):

    document = await app.ctx.db.logs.find_one({"key": key})

    if document is None:
        raise NotFound()

    action = await oauth_check(request, document, key)

    if action is not None:
        if "discord.com" in action:
            return response.redirect(action)
        elif "Retry after" in action:
            raise SanicException(status_code=429, message=action)
        else:
            raise Forbidden(message=action)

    log_entry = LogEntry(app, document)

    return log_entry.render_plain_text()


@app.get(prefix + "/<key>")
async def get_logs_file(request, key):

    document = await app.ctx.db.logs.find_one({"key": key})

    if document is None:
        raise NotFound()

    action = await oauth_check(request, document, key)

    if action is not None:
        if "discord.com" in action:
            return response.redirect(action)
        elif "Retry after" in action:
            raise SanicException(status_code=429, message=action)
        else:
            raise Forbidden(message=action)

    log_entry = LogEntry(app, document)

    return log_entry.render_html()


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=os.getenv("PORT", 8000),
        debug=bool(os.getenv("DEBUG", False)),
    )