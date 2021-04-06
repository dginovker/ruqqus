import os
import logging
import redis
import gevent
import mistletoe
from flask import *
from flask_socketio import *

from ruqqus.helpers.wrappers import *
from ruqqus.helpers.get import *
from ruqqus.helpers.sanitize import *
from ruqqus.helpers.markdown import CustomRenderer, preprocess
from ruqqus.__main__ import app, socketio, db_session

REDIS_URL = app.config["CACHE_REDIS_URL"]

#app = Flask(__name__)
#app.debug = 'DEBUG' in os.environ


SIDS={}

def v_rooms(v):

    output=[]
    for sid in SIDS.get(v.id,[]):
        for room in rooms(sid=sid):
            if room not in output:
                output.append(room)
    return output


def socket_auth_required(f):

    def wrapper(*args, **kwargs):

        g.db=db_session()

        v, client=get_logged_in_user()

        if client or not v:
            send("Not logged in")
            return

        if v.is_suspended:
            send("You're banned and can't access chat right now.")

        if request.sid not in SIDS.get(v.id, []):
            if v.id in SIDS:
                SIDS[v.id].append(request.sid)
            else:
                SIDS[v.id]=[request.sid]

        f(*args, v, **kwargs)

        g.db.close()

    wrapper.__name__=f.__name__
    return wrapper

def get_room(f):

    def wrapper(*args, **kwargs):

        data=args[0]
        guild=get_guild(data["guild"])

        if guild.is_banned:
            return

        f(*args, guild, **kwargs)

    wrapper.__name__=f.__name__
    return wrapper

@socketio.on('connect')
def socket_connect_auth_user():

    g.db=db_session()

    v, client=get_logged_in_user()

    if client or not v:
        emit("error", {"error":"Authentication required"})
        disconnect()

    if v.is_suspended:
        send("You're banned and can't access chat right now.")

    if v.id in SIDS:
        SIDS[v.id].append(request.sid)
    else:
        SIDS[v.id]=[request.sid]

    print(f"{v.username} connected")
    g.db.close()

@socketio.on('disconnect')
@socket_auth_required
def socket_disconnect_user(v):

    try:
        SIDS[v.id].remove(request.sid)
    except ValueError:
        pass

    for room in rooms():
        leave_room(room)
        send(f"← @{v.username} has left the chat", room=room)




@socketio.on('join room')
@socket_auth_required
@get_room
def join_guild_room(data, v, guild):

    if not guild.can_chat(v):
        send(f"You can't join the +{guild.name} chat right now.")
        return False

    join_room(guild.fullname)

    send(f"→ @{v.username} has entered the chat", room=guild.fullname)
    return True

@socketio.on('leave room')
@socket_auth_required
@get_room
def leave_guild_room(data, v, guild):
    leave_room(guild.fullname)
    send(f"← @{v.username} has left the chat", room=guild.fullname)


@socketio.on('speak')
@socket_auth_required
@get_room
def speak_guild(data, v, guild):

    if guild.fullname not in rooms():
        send("You aren't connected to that chat room. Trying to join...")
        x=join_guild_room(data)
        if not x:
            return



    raw_text=data['text'][0:1000].lstrip().rstrip()
    if not raw_text:
        return

    text=preprocess(raw_text)
    with CustomRenderer() as renderer:
        text = renderer.render(mistletoe.Document(text))
    text = sanitize(text, linkgen=True)



    if raw_text.startswith('/'):

        args=raw_text.split()

        if args[0]=="/here":

            ids=set()
            for uid in SIDS:
                for sid in SIDS[uid]:
                    if guild.fullname in rooms(sid=sid):
                        ids.add(uid)
                        break

            users=g.db.query(User.username).filter(User.id.in_(tuple(ids))).all()
            names=[x[0] for x in users]
            names=sorted(names)
            names = ", ".join(names)
            send(f"Users present: {names}")
            return

        elif args[0]=="/help":
            send("Universal Commands:")
            send("/here - Display a list of users currently in this channel")
            send("/help - Display this help information")
            send("Guildmaster Commands:")
            send("/kick <username> [reason] - Eject a user from this channel. They will be able to rejoin immediately after.")
            send("/ban <username> [reason] - Eject a user from this channel. They will not be able to rejoin until unbanned by a Guildmaster.")
            return


        if not guild.has_mod(v, perm="chat"):
            send("You don't have permission to use commands in this chat")
            return

        user=get_user(args[1], graceful=True)

        if not user:
            send(f"No user named {args[1]}")
            return

        if user.id==v.id:
            send("You can't kick/ban yourself!")
            return
        elif guild.has_mod(user):
            send(f"You can't kick/ban other guildmasters")
            return
        elif guild.has_contributor(user):
            send(f"@{user.username} is an approved contributor and can't currently be kicked or banned.")
            return

        if not any([x==guild.fullname for x in v_rooms(user)]):
            send(f"User {user.username} not present in chat")


        if args[0]=="/kick":
            reason= " ".join(args[2:]) if len(args)>=3 else "none"
            x=False
            for sid in SIDS[user.id]:
                for room in rooms(sid=sid):
                    if room==guild.fullname:
                        if not x:
                            send(f"← @{user.username} kicked by @{v.username}. Reason: {reason} ", to=guild.fullname)
                        leave_room(guild.fullname, sid=sid)
                        x=True

        elif args[0]=="/ban":
            reason= " ".join(args[2:]) if len(args)>=3 else "none"
            x=False
            for sid in SIDS[user.id]:
                for room in rooms(sid=sid):
                    if room==guild.fullname:
                        if not x:
                            send(f"← @{user.username} kicked and banned by @{v.username}. Reason: {reason}", to=guild.fullname)
                        leave_room(guild.fullname, sid=sid)
                        x=True
            if x:
                new_ban = ChatBan(user_id=user.id,
                                          board_id=guild.id,
                                          banning_mod_id=v.id)
                g.db.add(new_ban)

                ma=ModAction(
                    kind="chatban_user",
                    user_id=v.id,
                    target_user_id=user.id,
                    board_id=guild.id
                    )
                g.db.add(ma)
                g.db.commit()
            else:
                send(f"User {user.username} not present in chat")

        elif args[0]=="/unban":

            ban=g.db.query(ChatBan).filter_by(board_id=guild.id, target_user_id=user.id).first()
            if not ban:
                send(f"User {user.username} is not banned from chat.")
                return

            g.db.delete(ban)

            ma=ModAction(
                kind="unchatban_user",
                user_id=v.id,
                target_user_id=user.id,
                board_id=guild.id
                )
            g.db.add(ma)
            g.db.commit()
            send(f"@{user.username} un-chatbanned by @{v.username}.", to=guild.fullname)
    else:
        data={
            "avatar": v.profile_url,
            "username":v.username,
            "text":text,
            "room": guild.fullname
        }
        emit("speak", data, to=guild.fullname)






@app.route("/socket_home")
#@auth_required
def socket_home(v=None):

    return render_template("chat/chat_test.html", v=v)


@app.route("/+<guildname>/chat", methods=["GET"])
@is_not_banned
def guild_chat(guildname, v):

    guild=get_guild(guildname)

    return render_template("chat/chat.html", b=guild, v=v)