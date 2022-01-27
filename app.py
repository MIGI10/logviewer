__version__ = "1.1"

import os
import requests


from motor.motor_asyncio import AsyncIOMotorClient
from sanic import Sanic, response
from sanic.exceptions import abort, NotFound
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

        user = requests.get('https://discord.com/api/v9/users/@me', headers=headers)
        user = user.json()

        print("{}#{} with ID {} accessing site".format(user["username"], user["discriminator"], user["id"]))

        member = requests.get('https://discord.com/api/v9/users/@me/guilds/739552045123764275/member', headers=headers)
        member = member.json()

        if 'roles' not in member:
            return "403"

        if '739552527288107109' not in member["roles"] and document["title"] == "admin":
            return "403"
        
        if '822253899700371488' not in member["roles"]:
            if '739552877911212144' in member["roles"]:
                pass
            elif document["title"] == "minecraft" and '771566558899994645' in member["roles"]:
                pass
            elif document["title"] == "rust" and '933073057453588580' in member["roles"]:
                pass
            else:
                return "403"

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

    if not request.query_args:
        return render_template("index")
    
    return response.redirect('http://' + request.host + prefix + '/' + request.query_args[1][1] + '?code=' + request.query_args[0][1])


@app.get(prefix + "/raw/<key>")
async def get_raw_logs_file(request, key):

    document = await app.ctx.db.logs.find_one({"key": key})

    if document is None:
        return abort(404)

    action = await oauth_check(request, document, key)

    if action is not None:
        if action == "404":
            abort(404)
        elif action == "403":
            abort(403)
        else:
            response.redirect(action)

    log_entry = LogEntry(app, document)

    return log_entry.render_plain_text()


@app.get(prefix + "/<key>")
async def get_logs_file(request, key):

    document = await app.ctx.db.logs.find_one({"key": key})

    if document is None:
        return abort(404)

    action = await oauth_check(request, document, key)

    if action is not None:
        if action == "404":
            return abort(404)
        elif action == "403":
            return abort(403)
        else:
            return response.redirect(action)

    log_entry = LogEntry(app, document)

    return log_entry.render_html()


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=os.getenv("PORT", 8000),
        debug=bool(os.getenv("DEBUG", False)),
    )