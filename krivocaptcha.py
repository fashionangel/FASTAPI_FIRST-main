"""
Упоротая капча «Чекбокс-непоседа».

Чекбокс «Я не робот» убегает от курсора и дерзит. Реплики и стикеры выдаёт сервер:
он же считает промахи, палит автокликеры, проверяет тайминги и выдаёт токен.
После 5 промахов чекбокс зазнаётся, останавливается посреди поля посмеяться
над тобой — и именно в этот момент его можно поймать.
"""

import random
import secrets
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/krivo-captcha")

TOKEN_TTL = 10 * 60        # сертификат человечности живёт 10 минут
GLOAT_AFTER = 5            # промахов, после которых чекбокс зазнаётся
MAX_TRIES = 3              # попыток пройти (штрафуются только подозрительные действия)
MIN_TOTAL_SECONDS = 3.5    # быстрее всей погони — подозрительно
MISS_SPAM_GAP = 0.25       # промахи чаще этого = автокликер

INTRO_TEXT = "Нажми на чекбокс «Я не робот». Он против. Он очень против."

# (реплика, стикер) — по нарастающей наглости
TAUNTS = [
    ("не-а 😌", "🐥"),
    ("мимо. я даже не ускорился", "🐒"),
    ("слишком медленно. с уважением, чекбокс", "🐢"),
    ("ема ты лошара 💀 (но мы это никому не скажем)", "💀"),
    ("робот бы уже попал. или ты робот, просто сломанный?", "🤖"),
    ("мама говорила, я стану великим бегуном. спасибо за практику", "🏃"),
]
GLOAT_TAUNTS = [  # если промазал по зазнавшемуся чекбоксу
    ("ой, рефлексы. не ожидал от себя", "😅"),
    ("я не трус, я осторожный", "🐔"),
]
SUCCESS_TEXTS = [
    "🏅 Галочка поставлена. Чекбокс ушёл переписывать резюме.",
    "🏅 Официально: ты не робот. Чекбокс об этом ещё пожалеет.",
    "🏅 Пойман с поличным... то есть ты поймал. Молодец, короче.",
]
RESTART_MSG = "Чекбокс сбежал вместе с прогрессом. Начинаем погоню заново."


def _fail(request: Request, st: dict, msg: str) -> JSONResponse:
    st["tries"] = int(st.get("tries", 0)) + 1
    request.session["krivo_captcha"] = st
    if st["tries"] >= MAX_TRIES:
        request.session.pop("krivo_captcha", None)
        return JSONResponse({"ok": False, "restart": True, "error": RESTART_MSG})
    return JSONResponse({"ok": False, "error": msg, "tries_left": MAX_TRIES - st["tries"]})


def _finish(request: Request) -> JSONResponse:
    token = secrets.token_hex(16)
    request.session.pop("krivo_captcha", None)
    request.session["krivo_captcha_token"] = {"t": token, "ts": time.time()}
    return JSONResponse({
        "ok": True, "done": True, "token": token,
        "success_text": random.choice(SUCCESS_TEXTS),
    })


@router.post("/new")
async def new_captcha(request: Request):
    request.session["krivo_captcha"] = {
        "misses": 0, "last_miss": None, "started": time.time(), "tries": 0, "gloat": False,
    }
    return JSONResponse({
        "ok": True, "stage": "dodge",
        "title": "Чекбокс-непоседа",
        "text": INTRO_TEXT,
    })


@router.post("/answer")
async def answer(request: Request):
    st = request.session.get("krivo_captcha")
    if not st:
        return JSONResponse({
            "ok": False, "restart": True,
            "error": "Чекбокс ушёл по своим делам и забыл про погоню. Начнём заново.",
        })
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError
    except Exception:
        return _fail(request, st, "Чекбокс ждёт JSON. Он культурный.")

    action = body.get("action")
    now = time.time()

    if action == "miss":
        # анти-автокликер: промахи чаще 4 раз в секунду — не человек
        if st.get("last_miss") and now - st["last_miss"] < MISS_SPAM_GAP:
            return _fail(request, st,
                         "Клик чаще 4 раз в секунду? Автокликер детектед. "
                         "Признавайся, ты Puppeteer в маске человека.")
        st["last_miss"] = now
        st["misses"] = int(st.get("misses", 0)) + 1

        if st.get("gloat"):
            text, sticker = random.choice(GLOAT_TAUNTS)
            request.session["krivo_captcha"] = st
            return JSONResponse({"ok": True, "stage": "gloat", "taunt": text, "sticker": sticker})

        if st["misses"] >= GLOAT_AFTER:
            st["gloat"] = True
            request.session["krivo_captcha"] = st
            return JSONResponse({
                "ok": True, "stage": "gloat",
                "taunt": "ахах, ты НИКОГДА меня не пойма... стой. почему я стою на месте?!",
                "sticker": "😏",
            })

        request.session["krivo_captcha"] = st
        text, sticker = TAUNTS[min(st["misses"] - 1, len(TAUNTS) - 1)]
        return JSONResponse({
            "ok": True, "stage": "dodge", "taunt": text, "sticker": sticker,
            "misses": st["misses"],
        })

    if action == "caught":
        if not st.get("gloat"):
            # без штрафа: просто рано
            return JSONResponse({
                "ok": False,
                "error": "Рановато! Чекбокс ещё даже не разогнался. Погоняй его как следует.",
            })
        elapsed = now - st["started"]
        if elapsed < MIN_TOTAL_SECONDS:
            return _fail(request, st,
                         f"Ты справился за {elapsed:.1f} сек. Роботы такие быстрые. Люди — нет.")
        return _finish(request)

    return _fail(request, st, "Чекбокс не понял, чего ты хочешь. Он и не должен.")


def verify(request: Request, token: str, consume: bool = True) -> bool:
    """Проверяет сертификат человечности. consume=True — токен сгорает после проверки."""
    rec = request.session.get("krivo_captcha_token")
    if not rec or not token:
        return False
    if not secrets.compare_digest(str(token), str(rec.get("t", ""))):
        return False
    if time.time() - float(rec.get("ts", 0)) > TOKEN_TTL:
        request.session.pop("krivo_captcha_token", None)
        return False
    if consume:
        request.session.pop("krivo_captcha_token", None)
    return True